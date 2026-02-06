from __future__ import annotations
import logging, time, base64, json, zlib
from typing import Any, Callable, Dict, List, Optional
import time as _time
from homeassistant.core import HomeAssistant, Event, State
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from .const import (
    DOMAIN, STORAGE_KEY, STORAGE_VERSION,
    CONF_TWA, CONF_TWS, CONF_BSP,
    CONF_TWA_MIN, CONF_TWA_MAX, CONF_TWA_STEP,
    CONF_TWS_MIN, CONF_TWS_MAX, CONF_TWS_STEP,
    CONF_FOLD_0_180, CONF_INTERPOLATE,
    CONF_RECORD_GATE, CONF_MIN_TWS, CONF_MIN_BSP,
    CONF_TWS_EMA_ALPHA, CONF_LULL_GUARD_DELTA,
    DEFAULTS,
)

_LOGGER = logging.getLogger(__name__)

Subscriber = Callable[[], None]

class PolarCoordinator:
    """Maintain a (twa|tws)->max_bsp matrix and expose helpers."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._listeners: List[Callable[[], None]] = []
        self._subs: List[Subscriber] = []
        self.matrix: Dict[str, float] = {}
        self.last_update_ts: Optional[float] = None
        self.recording_enabled: bool = True
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        # rotating backups (persisted)
        self.backup_b1: Optional[str] = None
        self.backup_b2: Optional[str] = None
        self.backup_b3: Optional[str] = None
        self.backup_t1: Optional[str] = None   # "yy-mm-dd HH:MM:SS"
        self.backup_t2: Optional[str] = None
        self.backup_t3: Optional[str] = None
        # lull guard state
        self._ema_tws: Optional[float] = None

    async def async_setup(self) -> None:
        await self._async_load()

        # Always start Idle after (re)start so users explicitly enable recording.
        self.recording_enabled = False
        await self._async_save()

        self._attach_listeners()

    async def async_unload(self) -> None:
        for u in self._listeners:
            u()
        self._listeners.clear()

    # ---- persistence ----
    async def _async_load(self) -> None:
        data = await self.store.async_load() or {}
        self.matrix = data.get("matrix", {})
        self.last_update_ts = data.get("ts")
        # previous persisted flag is ignored at startup; we force Idle in async_setup
        self.recording_enabled = data.get("recording", False)

        b = data.get("backups", {})
        self.backup_b1 = b.get("b1")
        self.backup_b2 = b.get("b2")
        self.backup_b3 = b.get("b3")
        self.backup_t1 = b.get("t1")
        self.backup_t2 = b.get("t2")
        self.backup_t3 = b.get("t3")

    async def _async_save(self) -> None:
        await self.store.async_save({
            "matrix": self.matrix,
            "ts": self.last_update_ts,
            "recording": self.recording_enabled,
            "backups": {
                "b1": self.backup_b1, "b2": self.backup_b2, "b3": self.backup_b3,
                "t1": self.backup_t1, "t2": self.backup_t2, "t3": self.backup_t3,
            },
        })

    # ---- config view ----
    @property
    def cfg(self) -> dict[str, Any]:
        cfg = dict(DEFAULTS)
        cfg.update(self.entry.data or {})
        cfg.update(self.entry.options or {})
        return cfg

    # ---- entity subscription ----
    def register(self, cb: Subscriber) -> None:
        self._subs.append(cb)

    def _notify(self) -> None:
        for cb in list(self._subs):
            try:
                cb()
            except Exception as e:
                _LOGGER.debug("Subscriber callback error: %s", e)

    # ---- recording control ----
    async def async_set_recording(self, on: bool) -> None:
        self.recording_enabled = bool(on)
        await self._async_save()
        self._notify()

    # ---- event listeners ----
    def _attach_listeners(self) -> None:
        ents = [self.cfg[CONF_TWA], self.cfg[CONF_TWS], self.cfg[CONF_BSP]]
        for ent in ents:
            self._listeners.append(async_track_state_change_event(self.hass, [ent], self._on_any_change))

    async def _on_any_change(self, _event: Event) -> None:
        if not self._should_record_now():
            return

        twa = self._state_float(self.cfg[CONF_TWA])
        tws = self._state_float(self.cfg[CONF_TWS])
        bsp = self._state_float(self.cfg[CONF_BSP])
        if twa is None or tws is None or bsp is None:
            return

        # ---- EMA update + Lull guard (pre-filtering) ----
        # Pull user-configurable parameters (fallback to defaults if missing)
        alpha = float(self.cfg.get(CONF_TWS_EMA_ALPHA, 0.20))
        alpha = min(1.0, max(0.0, alpha))  # clamp to [0,1]
        guard = float(self.cfg.get(CONF_LULL_GUARD_DELTA, 0.5))

        # Seed EMA on first sample, then update
        if self._ema_tws is None:
            self._ema_tws = tws
        else:
            self._ema_tws = alpha * tws + (1.0 - alpha) * self._ema_tws

        # If we're below recent average by more than the guard delta, skip (likely a lull after a gust)
        if tws < (self._ema_tws - guard):
            return

        if self.cfg.get(CONF_FOLD_0_180, True):
            twa = self._fold_0_180(twa)

        if not (self.cfg[CONF_TWA_MIN] <= twa <= self.cfg[CONF_TWA_MAX]):
            return
        if not (self.cfg[CONF_TWS_MIN] <= tws <= self.cfg[CONF_TWS_MAX]):
            return

        a_step, s_step = self.cfg[CONF_TWA_STEP], self.cfg[CONF_TWS_STEP]
        a_bin = self._bin_floor(twa, a_step, self.cfg[CONF_TWA_MIN], self.cfg[CONF_TWA_MAX])
        s_bin = self._bin_floor(tws, s_step, self.cfg[CONF_TWS_MIN], self.cfg[CONF_TWS_MAX])
        key = f"{self._bin_key(a_bin, a_step)}|{self._bin_key(s_bin, s_step)}"

        old = float(self.matrix.get(key, 0))
        if bsp > old:
            self.matrix[key] = round(bsp, 3)
            self.last_update_ts = time.time()
            await self._async_save()
            self._notify()

    def _should_record_now(self) -> bool:
        """
        Service override: Start/Stop are the master switch.
        - If recording_enabled is False -> never record.
        - If recording_enabled is True  -> record (ignore Record Gate).
        """
        return bool(self.recording_enabled)

    # ---- utilities ----
    def _entity_truthy(self, entity_id: str) -> bool:
        st = self.hass.states.get(entity_id)
        if not st:
            return False
        s = st.state.lower()
        if s in ("on", "true", "open"):
            return True
        try:
            return float(st.state) != 0.0
        except (TypeError, ValueError):
            return False

    def _state_float(self, entity_id: str) -> Optional[float]:
        st: Optional[State] = self.hass.states.get(entity_id)
        if not st:
            return None
        try:
            return float(st.state)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fold_0_180(v: float) -> float:
        # normalize -180..180 or 0..360 into 0..180 symmetry
        if v < 0:
            v = (v + 360) % 360
        return 360 - v if v > 180 else v

    @staticmethod
    def _bin_floor(v: float, step: float, vmin: float, vmax: float) -> float:
        b = int(v // step) * step
        return max(vmin, min(b, vmax - step))

    # ---- CSV / export ----
    def build_csv(self) -> str:
        c = self.cfg
        a_bins = self._gen_bins(c[CONF_TWA_MIN], c[CONF_TWA_MAX], c[CONF_TWA_STEP])
        s_bins = self._gen_bins(c[CONF_TWS_MIN], c[CONF_TWS_MAX], c[CONF_TWS_STEP])

        header = ["TWA \\ TWS"] + [self._bin_key(s, c[CONF_TWS_STEP]) for s in s_bins]
        lines = [",".join(header)]

        for a in a_bins:
            row = [self._bin_key(a, c[CONF_TWA_STEP])]
            for s in s_bins:
                key = f"{self._bin_key(a, c[CONF_TWA_STEP])}|{self._bin_key(s, c[CONF_TWS_STEP])}"
                v = self.matrix.get(key)
                row.append("" if v is None else f"{v:.2f}")
            lines.append(",".join(row))
        return "\n".join(lines)

    async def async_export_csv(self, path: str) -> None:
        csv = self.build_csv()
        await self.hass.async_add_executor_job(self._write_file, path, csv)

    @staticmethod
    def _write_file(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    # Helpers inside PolarCoordinator
    def _bin_key(self, v: float, step: float) -> str:
        """Stable text key for a bin edge based on step granularity."""
        s = str(step)
        decimals = 0
        if "." in s:
            decimals = len(s.split(".")[-1].rstrip("0"))
        if decimals <= 0:
            return f"{int(round(v))}"
        return f"{round(v, decimals):.{decimals}f}"

    def _gen_bins(self, start: float, stop: float, step: float) -> list[float]:
        """Generate [start, start+step, ... < stop] with float steps."""
        bins = []
        v = float(start)
        eps = max(1e-9, abs(step) * 1e-6)  # avoid float drift at upper bound
        while v < float(stop) - eps:
            bins.append(v)
            v += float(step)
        return bins

    def export_payload(self) -> dict:
        """All state needed for a backup blob."""
        c = self.cfg
        return {
            "version": 1,
            "matrix": self.matrix,
            "twa_min": c[CONF_TWA_MIN],
            "twa_max": c[CONF_TWA_MAX],
            "twa_step": c[CONF_TWA_STEP],
            "tws_min": c[CONF_TWS_MIN],
            "tws_max": c[CONF_TWS_MAX],
            "tws_step": c[CONF_TWS_STEP],
            "fold_to_180": c.get(CONF_FOLD_0_180, True),
            "ts": self.last_update_ts,
            "recording": self.recording_enabled,
        }

    def export_blob(self) -> str:
        """Return gz+b64 JSON – safe to store in an attribute."""
        data = json.dumps(self.export_payload(), separators=(",", ":")).encode()
        comp = zlib.compress(data, 9)
        return base64.b64encode(comp).decode()

    def import_blob(self, blob: str) -> None:
        """Load a gz+b64 JSON blob into live state."""
        comp = base64.b64decode(blob)
        data = json.loads(zlib.decompress(comp).decode())
        if data.get("version") != 1:
            raise ValueError("Unsupported polar backup version")

        # restore only the volatile bits (keep current config unless you WANT to override)
        self.matrix = data.get("matrix", {})
        self.last_update_ts = data.get("ts")
        self.recording_enabled = data.get("recording", True)

    def _now_str(self) -> str:
        return time.strftime("%y-%m-%d %H:%M:%S", time.localtime())

    async def async_rotate_backup_with_blob(self, blob: str) -> None:
        """Rotate: oldest <- previous <- latest <- new blob."""
        self.backup_b3, self.backup_t3 = self.backup_b2, self.backup_t2
        self.backup_b2, self.backup_t2 = self.backup_b1, self.backup_t1
        self.backup_b1, self.backup_t1 = blob, self._now_str()
        await self._async_save()
        self._notify()

    async def async_import_blob(self, blob: str) -> None:
        """Async wrapper for import + save + notify."""
        self.import_blob(blob)
        await self._async_save()
        self._notify()

    def get_backup_blob(self, which: str) -> str | None:
        w = (which or "latest").lower()
        if w == "latest":
            return self.backup_b1
        if w == "previous":
            return self.backup_b2
        if w == "oldest":
            return self.backup_b3
        return None

    # ---- CSV / import ----
    async def async_import_csv_file(self, path: str, *, merge: bool = False, fill_missing: bool = False) -> None:
        """Import a CSV from disk into the matrix.

        Format:
          Row 1:   TWA \ TWS, <tws1>, <tws2>, ...
          Rows 2+: <twa>, <bsp at tws1>, <bsp at tws2>, ...

        Empty cells are allowed; when fill_missing is True we attempt a simple
        neighbor-based fill for conservative interpolation.
        """
        import csv

        # Read file and sniff delimiter
        def _read():
            with open(path, "r", encoding="utf-8") as f:
                data = f.read()
            dialect = csv.Sniffer().sniff(data, delimiters=[",", ";", "\t"])
            rows = list(csv.reader(data.splitlines(), dialect))
            return rows

        rows = await self.hass.async_add_executor_job(_read)
        if not rows or len(rows[0]) < 2:
            raise ValueError("CSV has no header or not enough columns")

        # parse number helper
        def _num(s: str) -> Optional[float]:
            s = (s or "").strip().replace("°", "").replace("kn", "")
            if s == "" or s == "-":
                return None
            try:
                return float(s.replace(",", "."))  # allow comma decimal
            except (ValueError, TypeError):
                return None

        # Respect current config bins; snap imported values to bin floors
        c = self.cfg
        a_step, s_step = c[CONF_TWA_STEP], c[CONF_TWS_STEP]
        a_min, a_max = c[CONF_TWA_MIN], c[CONF_TWA_MAX]
        s_min, s_max = c[CONF_TWS_MIN], c[CONF_TWS_MAX]

        # Header: TWS values
        tws_vals_raw = rows[0][1:]
        tws_vals = [_num(x) for x in tws_vals_raw]
        if not any(v is not None for v in tws_vals):
            raise ValueError("No numeric TWS headers found in CSV")

        # Prepare staging matrix
        new_matrix: Dict[str, float] = {} if not merge else dict(self.matrix)

        # Walk body rows
        for r in rows[1:]:
            if not r or len(r) < 2:
                continue
            twa_raw = _num(r[0])
            if twa_raw is None:
                continue

            # Fold if current config folds
            if c.get(CONF_FOLD_0_180, True):
                twa_raw = self._fold_0_180(twa_raw)

            # Bounds
            if not (a_min <= twa_raw <= a_max):
                continue

            # Snap TWA to bin floor
            a_bin = self._bin_floor(twa_raw, a_step, a_min, a_max)
            bk_a = self._bin_key(a_bin, a_step)

            # Each TWS column
            for idx, cell in enumerate(r[1:]):
                tws_raw = tws_vals[idx]
                if tws_raw is None:
                    continue
                if not (s_min <= tws_raw <= s_max):
                    continue

                v = _num(cell)
                if v is None:
                    continue  # missing cell OK

                s_bin = self._bin_floor(tws_raw, s_step, s_min, s_max)
                bk_s = self._bin_key(s_bin, s_step)
                key = f"{bk_a}|{bk_s}"

                # keep maximum if merging; otherwise overwrite
                if merge:
                    old = float(new_matrix.get(key, 0))
                    if v > old:
                        new_matrix[key] = float(v)
                else:
                    new_matrix[key] = float(v)

        # Optionally fill missing via a simple neighbor average
        if fill_missing:
            self._fill_missing_bins_inplace(new_matrix)

        # Commit: replace live matrix and persist
        self.matrix = new_matrix
        self.last_update_ts = time.time()
        await self._async_save()
        self._notify()

    def _fill_missing_bins_inplace(self, mat: Dict[str, float]) -> None:
        """Try to fill gaps by averaging available neighbors (conservative)."""
        c = self.cfg
        a_step, s_step = c[CONF_TWA_STEP], c[CONF_TWS_STEP]
        a_bins = self._gen_bins(c[CONF_TWA_MIN], c[CONF_TWA_MAX], a_step)
        s_bins = self._gen_bins(c[CONF_TWS_MIN], c[CONF_TWS_MAX], s_step)

        def key(a, s): return f"{self._bin_key(a, a_step)}|{self._bin_key(s, s_step)}"

        changed = True
        for _ in range(3):  # a few passes
            if not changed:
                break
            changed = False
            for a in a_bins:
                for s in s_bins:
                    k = key(a, s)
                    if k in mat:
                        continue
                    neighbors = []
                    for da, ds in ((-a_step, 0), (a_step, 0), (0, -s_step), (0, s_step)):
                        aa = a + da
                        ss = s + ds
                        if aa < c[CONF_TWA_MIN] or aa >= c[CONF_TWA_MAX]:
                            continue
                        if ss < c[CONF_TWS_MIN] or ss >= c[CONF_TWS_MAX]:
                            continue
                        v = mat.get(key(aa, ss))
                        if v is not None:
                            neighbors.append(v)
                    if len(neighbors) >= 2:
                        mat[k] = round(sum(neighbors) / len(neighbors), 2)
                        changed = True
                        
    # -------- Editable Polar: direct cell/line mutations --------
    async def async_set_cell(self, *, twa: float, tws: float, bsp: float) -> None:
        """Set/override one bin value (BSP) at (TWA, TWS). Bypasses gates/thresholds."""
        c = self.cfg
        # fold if configured
        if c.get(CONF_FOLD_0_180, True):
            twa = self._fold_0_180(twa)
        # keep within configured ranges
        if not (c[CONF_TWA_MIN] <= twa < c[CONF_TWA_MAX]) or not (c[CONF_TWS_MIN] <= tws < c[CONF_TWS_MAX]):
            raise ValueError("TWA/TWS outside configured ranges")

        a_step, s_step = float(c[CONF_TWA_STEP]), float(c[CONF_TWS_STEP])
        a0 = self._bin_floor(twa, a_step, c[CONF_TWA_MIN], c[CONF_TWA_MAX])
        s0 = self._bin_floor(tws, s_step, c[CONF_TWS_MIN], c[CONF_TWS_MAX])
        key = f"{self._bin_key(a0, a_step)}|{self._bin_key(s0, s_step)}"

        self.matrix[key] = round(float(bsp), 3)
        self.last_update_ts = _time.time()
        await self._async_save()
        self._notify()

    async def async_clear_cell(self, *, twa: float, tws: float) -> None:
        """Delete one bin value at (TWA, TWS)."""
        c = self.cfg
        if c.get(CONF_FOLD_0_180, True):
            twa = self._fold_0_180(twa)
        if not (c[CONF_TWA_MIN] <= twa < c[CONF_TWA_MAX]) or not (c[CONF_TWS_MIN] <= tws < c[CONF_TWS_MAX]):
            raise ValueError("TWA/TWS outside configured ranges")

        a_step, s_step = float(c[CONF_TWA_STEP]), float(c[CONF_TWS_STEP])
        a0 = self._bin_floor(twa, a_step, c[CONF_TWA_MIN], c[CONF_TWA_MAX])
        s0 = self._bin_floor(tws, s_step, c[CONF_TWS_MIN], c[CONF_TWS_MAX])
        key = f"{self._bin_key(a0, a_step)}|{self._bin_key(s0, s_step)}"

        if key in self.matrix:
            del self.matrix[key]
            self.last_update_ts = _time.time()
            await self._async_save()
            self._notify()

    async def async_scale_line(self, *, tws: float, factor: float) -> None:
        """Multiply all cells in the TWS line by factor (>0)."""
        if factor <= 0:
            raise ValueError("factor must be > 0")
        c = self.cfg
        # snap target TWS to its bin edge
        s_step = float(c[CONF_TWS_STEP])
        s0 = self._bin_floor(tws, s_step, c[CONF_TWS_MIN], c[CONF_TWS_MAX])
        s_key = self._bin_key(s0, s_step)

        a_step = float(c[CONF_TWA_STEP])
        a_vals = self._gen_bins(c[CONF_TWA_MIN], c[CONF_TWA_MAX], a_step)

        any_change = False
        for a in a_vals:
            key = f"{self._bin_key(a, a_step)}|{s_key}"
            if key in self.matrix:
                self.matrix[key] = round(self.matrix[key] * factor, 3)
                any_change = True

        if any_change:
            self.last_update_ts = _time.time()
            await self._async_save()
            self._notify()