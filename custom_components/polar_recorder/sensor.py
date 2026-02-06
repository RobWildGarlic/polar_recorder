from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_BSP,
    CONF_FOLD_0_180,
    CONF_INTERPOLATE,
    CONF_TWA,
    CONF_TWA_MAX,
    CONF_TWA_MIN,
    CONF_TWA_STEP,
    CONF_TWS,
    CONF_TWS_MAX,
    CONF_TWS_MIN,
    CONF_TWS_STEP,
)
from .coordinator import PolarCoordinator

# ---------- shared helpers ----------


def _nearest_value(
    coord: PolarCoordinator,
    matrix: dict,
    twa: float,
    tws: float,
    a0: float,
    a1: float,
    s0: float,
    s1: float,
    a_step: float,
    s_step: float,
):
    """Pick the nearest populated corner among (a0|s0),(a1|s0),(a0|s1),(a1|s1)."""
    candidates = []
    for a in {a0, a1}:
        for s in {s0, s1}:
            key = f"{coord._bin_key(a, a_step)}|{coord._bin_key(s, s_step)}"
            v = matrix.get(key)
            if v is not None:
                candidates.append((abs(twa - a) + abs(tws - s), v))
    if not candidates:
        return None
    return round(min(candidates, key=lambda x: x[0])[1], 2)


def _bilinear_value(
    coord: PolarCoordinator,
    matrix: dict,
    twa: float,
    tws: float,
    a0: float,
    a1: float,
    s0: float,
    s1: float,
    a_step: float,
    s_step: float,
):
    """Bilinear interpolation between four surrounding bins; falls back to nearest if any missing."""
    bk_a0 = coord._bin_key(a0, a_step)
    bk_a1 = coord._bin_key(a1, a_step)
    bk_s0 = coord._bin_key(s0, s_step)
    bk_s1 = coord._bin_key(s1, s_step)
    v00 = matrix.get(f"{bk_a0}|{bk_s0}")
    v10 = matrix.get(f"{bk_a1}|{bk_s0}")
    v01 = matrix.get(f"{bk_a0}|{bk_s1}")
    v11 = matrix.get(f"{bk_a1}|{bk_s1}")
    if None in (v00, v10, v01, v11):
        return _nearest_value(coord, matrix, twa, tws, a0, a1, s0, s1, a_step, s_step)

    ax = 0 if a1 == a0 else (twa - a0) / (a1 - a0)
    sx = 0 if s1 == s0 else (tws - s0) / (s1 - s0)
    v0 = v00 * (1 - ax) + v10 * ax
    v1 = v01 * (1 - ax) + v11 * ax
    return round(v0 * (1 - sx) + v1 * sx, 2)


# ---------- entities ----------


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: PolarCoordinator = entry.runtime_data

    entities: list[SensorEntity] = [
        PolarMatrixEntity(entry.entry_id, coord),
        PolarTargetSpeedEntity(entry.entry_id, coord),
        PolarPerformanceEntity(entry.entry_id, coord),
    ]

    async_add_entities(entities, update_before_add=True)


class _BaseEntity(SensorEntity):
    _attr_should_poll = False

    def __init__(self, unique_prefix: str, coord: PolarCoordinator) -> None:
        self._coord = coord
        self._attr_unique_id = f"{unique_prefix}-{self._suffix()}"

    def _suffix(self) -> str:
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        # Refresh on coordinator notifications
        self._coord.register(self.async_write_ha_state)

    def _state_float(self, entity_id: str):
        st = self.hass.states.get(entity_id)
        if not st:
            return None
        try:
            return float(st.state)
        except (TypeError, ValueError):
            return None


class PolarMatrixEntity(_BaseEntity):
    _attr_has_entity_name = True
    _attr_name = "Polar Matrix"
    _attr_icon = "mdi:sail-boat"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def _suffix(self) -> str:
        return "polar-matrix"

    @property
    def native_value(self):
        # Show human-friendly state instead of a timestamp
        return "Recording" if self._coord.recording_enabled else "Idle"

    @property
    def extra_state_attributes(self):
        cfg = self._coord.cfg
        # Optional: keep timestamps as attributes (both raw and readable)
        import time as _t

        ts = self._coord.last_update_ts
        nice = _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(ts)) if ts else None
        return {
            "recording": self._coord.recording_enabled,
            "last_update_ts": ts,
            "last_update": nice,
            "matrix": self._coord.matrix,  # LARGE attr
            "twa_min": cfg[CONF_TWA_MIN],
            "twa_max": cfg[CONF_TWA_MAX],
            "twa_step": cfg[CONF_TWA_STEP],
            "tws_min": cfg[CONF_TWS_MIN],
            "tws_max": cfg[CONF_TWS_MAX],
            "tws_step": cfg[CONF_TWS_STEP],
            "fold_to_180": cfg.get(CONF_FOLD_0_180, True),
            "interpolate": cfg.get(CONF_INTERPOLATE, False),
            # persisted rotating backups (exposed here)
            "backup_latest": self._coord.backup_b1,
            "backup_previous": self._coord.backup_b2,
            "backup_oldest": self._coord.backup_b3,
            "backup_latest_ts": self._coord.backup_t1,
            "backup_previous_ts": self._coord.backup_t2,
            "backup_oldest_ts": self._coord.backup_t3,
        }


class PolarTargetSpeedEntity(_BaseEntity):
    _attr_has_entity_name = True
    _attr_name = "Polar Target Speed"
    _attr_icon = "mdi:speedometer"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def _suffix(self) -> str:
        return "polar-target"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        cfg = self._coord.cfg
        self._unsubs = [
            async_track_state_change_event(self.hass, [cfg[CONF_TWA]], self._on_src),
            async_track_state_change_event(self.hass, [cfg[CONF_TWS]], self._on_src),
        ]

    async def async_will_remove_from_hass(self) -> None:
        for u in getattr(self, "_unsubs", []):
            u()
        self._unsubs = []

    async def _on_src(self, _event) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self):
        return self._compute_target()

    def _compute_target(self):
        cfg = self._coord.cfg
        twa = self._state_float(cfg[CONF_TWA])
        tws = self._state_float(cfg[CONF_TWS])
        if twa is None or tws is None:
            return None
        if cfg.get(CONF_FOLD_0_180, True):
            twa = self._coord._fold_0_180(twa)

        if not (cfg[CONF_TWA_MIN] <= twa <= cfg[CONF_TWA_MAX]) or not (
            cfg[CONF_TWS_MIN] <= tws <= cfg[CONF_TWS_MAX]
        ):
            return None

        a_step, s_step = cfg[CONF_TWA_STEP], cfg[CONF_TWS_STEP]
        a0 = self._coord._bin_floor(twa, a_step, cfg[CONF_TWA_MIN], cfg[CONF_TWA_MAX])
        s0 = self._coord._bin_floor(tws, s_step, cfg[CONF_TWS_MIN], cfg[CONF_TWS_MAX])
        a1 = min(a0 + a_step, cfg[CONF_TWA_MAX])
        s1 = min(s0 + s_step, cfg[CONF_TWS_MAX])

        m = self._coord.matrix
        if not cfg.get(CONF_INTERPOLATE, False) or a1 == a0 or s1 == s0:
            return _nearest_value(
                self._coord, m, twa, tws, a0, a1, s0, s1, a_step, s_step
            )
        return _bilinear_value(self._coord, m, twa, tws, a0, a1, s0, s1, a_step, s_step)


class PolarPerformanceEntity(_BaseEntity):
    """Current BSP vs Target (%)."""

    _attr_has_entity_name = True
    _attr_name = "Polar Performance"
    _attr_icon = "mdi:percent-outline"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def _suffix(self) -> str:
        return "polar-perf"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        cfg = self._coord.cfg
        self._unsubs = [
            async_track_state_change_event(self.hass, [cfg[CONF_BSP]], self._on_src),
            async_track_state_change_event(self.hass, [cfg[CONF_TWA]], self._on_src),
            async_track_state_change_event(self.hass, [cfg[CONF_TWS]], self._on_src),
        ]

    async def async_will_remove_from_hass(self) -> None:
        for u in getattr(self, "_unsubs", []):
            u()
        self._unsubs = []

    async def _on_src(self, _event) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self):
        bsp = self._state_float(self._coord.cfg[CONF_BSP])
        tgt = self._compute_target_like_target_sensor()
        if bsp is None or tgt is None or tgt <= 0:
            return None
        return round(100.0 * bsp / tgt, 1)

    @property
    def extra_state_attributes(self):
        cfg = self._coord.cfg
        bsp = self._state_float(cfg[CONF_BSP])
        tgt = self._compute_target_like_target_sensor()
        delta = None if (bsp is None or tgt is None) else round(bsp - tgt, 2)
        return {
            "boat_speed": None if bsp is None else round(bsp, 2),
            "target_speed": tgt,
            "delta_kn": delta,
            "interpolate": cfg.get(CONF_INTERPOLATE, False),
            "fold_to_180": cfg.get(CONF_FOLD_0_180, True),
        }

    def _compute_target_like_target_sensor(self):
        cfg = self._coord.cfg
        twa = self._state_float(cfg[CONF_TWA])
        tws = self._state_float(cfg[CONF_TWS])
        if twa is None or tws is None:
            return None
        if cfg.get(CONF_FOLD_0_180, True):
            twa = self._coord._fold_0_180(twa)

        if not (cfg[CONF_TWA_MIN] <= twa <= cfg[CONF_TWA_MAX]) or not (
            cfg[CONF_TWS_MIN] <= tws <= cfg[CONF_TWS_MAX]
        ):
            return None

        a_step, s_step = cfg[CONF_TWA_STEP], cfg[CONF_TWS_STEP]
        a0 = self._coord._bin_floor(twa, a_step, cfg[CONF_TWA_MIN], cfg[CONF_TWA_MAX])
        s0 = self._coord._bin_floor(tws, s_step, cfg[CONF_TWS_MIN], cfg[CONF_TWS_MAX])
        a1 = min(a0 + a_step, cfg[CONF_TWA_MAX])
        s1 = min(s0 + s_step, cfg[CONF_TWS_MAX])

        m = self._coord.matrix
        if not cfg.get(CONF_INTERPOLATE, False) or a1 == a0 or s1 == s0:
            return _nearest_value(
                self._coord, m, twa, tws, a0, a1, s0, s1, a_step, s_step
            )
        return _bilinear_value(self._coord, m, twa, tws, a0, a1, s0, s1, a_step, s_step)
