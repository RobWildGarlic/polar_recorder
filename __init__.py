from __future__ import annotations
import asyncio

import logging
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry

# Only import DOMAIN; define PLATFORMS locally to avoid const import issues
from .const import DOMAIN
from .coordinator import PolarCoordinator

# Smart2000ESP integration cooperation
from .const import (
    SMART2000ESP_DOMAIN,
    SMART2000ESP_SERVICE_SET_UPDATE,
    # use configured value instead of a fixed constant:
    CONF_SMART_FAST_SECONDS,
    DEFAULTS,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "number"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Polar Recorder from a config entry."""
    coord = PolarCoordinator(hass, entry)
    await coord.async_setup()
    entry.runtime_data = coord  # make coordinator accessible to platform & services

    # Set up platforms (sensors)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ---- helper: talk to Smart2000ESP best-effort ----
    async def _smart_set_interval(seconds: float | None) -> None:
        """Set (or reset) Smart2000ESP update interval if service exists."""
        try:
            if not hass.services.has_service(SMART2000ESP_DOMAIN, SMART2000ESP_SERVICE_SET_UPDATE):
                return
            data = {} if seconds is None else {"seconds": seconds}
            await hass.services.async_call(
                SMART2000ESP_DOMAIN,
                SMART2000ESP_SERVICE_SET_UPDATE,
                data,
                blocking=False,
            )
        except Exception as err:
            # Be quiet in production; this is advisory
            _LOGGER.debug(
                "smart2000esp.set_update_interval failed (%s): %s",
                "reset-default" if seconds is None else f"{seconds}s",
                err,
            )

    def _coerce_float(x, default=None):
        try:
            return float(x)
        except (TypeError, ValueError):
            return default

    def _state_float(hass: HomeAssistant, entity_id: str, default=None):
        st = hass.states.get(entity_id)
        return _coerce_float(st.state, default) if st else default


    # --- Services ---
    async def svc_export_csv(call: ServiceCall) -> None:
        path = call.data.get("path") or "/config/www/polars.csv"
        await coord.async_export_csv(path)

    async def svc_reset(_call: ServiceCall) -> None:
        coord.matrix = {}
        coord.last_update_ts = None
        await coord._async_save()
        coord._notify()
        # Note: do NOT touch Smart2000ESP interval on reset; only start/stop/toggle manage it

    async def svc_start(_call: ServiceCall) -> None:
        await coord.async_set_recording(True)  # includes save + notify
        # Speed up Smart2000ESP while recording, using configured fast interval
        fast = coord.cfg.get(CONF_SMART_FAST_SECONDS, DEFAULTS[CONF_SMART_FAST_SECONDS])
        try:
            fast = float(fast)
        except Exception:
            fast = DEFAULTS[CONF_SMART_FAST_SECONDS]
        await _smart_set_interval(fast)

    async def svc_stop(_call: ServiceCall) -> None:
        await coord.async_set_recording(False)  # includes save + notify
        # Revert Smart2000ESP to its default (no 'seconds' key)
        await _smart_set_interval(None)

    async def _svc_toggle(_call: ServiceCall) -> None:
        new_state = not coord.recording_enabled
        await coord.async_set_recording(new_state)
        # Apply corresponding Smart2000ESP behavior using configured value
        if new_state:
            fast = coord.cfg.get(CONF_SMART_FAST_SECONDS, DEFAULTS[CONF_SMART_FAST_SECONDS])
            try:
                fast = float(fast)
            except Exception:
                fast = DEFAULTS[CONF_SMART_FAST_SECONDS]
            await _smart_set_interval(fast)
        else:
            await _smart_set_interval(None)

# Edit services ---
    async def svc_set_cell(call: ServiceCall) -> None:
        # Let any just-changed number entities settle
        await asyncio.sleep(0.08)  # ~80ms is enough; feel free to make 0.05–0.10

        twa = _coerce_float(call.data.get("twa"))
        tws = _coerce_float(call.data.get("tws"))
        bsp = _coerce_float(call.data.get("bsp"))

        if twa is None:
            twa = _state_float(hass, "number.polar_edit_twa")
        if tws is None:
            tws = _state_float(hass, "number.polar_edit_tws")
        if bsp is None:
            bsp = _state_float(hass, "number.polar_edit_bsp")

        if None in (twa, tws, bsp):
            raise ValueError("Missing TWA/TWS/BSP (set numbers or pass values)")
        await coord.async_set_cell(twa=float(twa), tws=float(tws), bsp=float(bsp))

    async def svc_clear_cell(call: ServiceCall) -> None:
        await asyncio.sleep(0.08)

        twa = _coerce_float(call.data.get("twa"))
        tws = _coerce_float(call.data.get("tws"))
        if twa is None:
            twa = _state_float(hass, "number.polar_edit_twa")
        if tws is None:
            tws = _state_float(hass, "number.polar_edit_tws")
        if None in (twa, tws):
            raise ValueError("Missing TWA/TWS (set numbers or pass values)")
        await coord.async_clear_cell(twa=float(twa), tws=float(tws))

    async def svc_scale_line(call: ServiceCall) -> None:
        await asyncio.sleep(0.08)

        tws = _coerce_float(call.data.get("tws"))
        factor = _coerce_float(call.data.get("factor"))
        if tws is None:
            tws = _state_float(hass, "number.polar_edit_tws")
        if factor is None:
            factor = _state_float(hass, "number.polar_scale_factor", 1.0)
        if tws is None or factor is None:
            raise ValueError("Missing TWS/factor (set numbers or pass values)")
        await coord.async_scale_line(tws=float(tws), factor=float(factor))


    async def svc_backup(_call: ServiceCall) -> None:
        blob = coord.export_blob()
        await coord.async_rotate_backup_with_blob(blob)  # save + notify inside

    async def svc_restore(call: ServiceCall) -> None:
        which = (call.data.get("which") or "latest").lower()
        blob = coord.get_backup_blob(which)
        if not blob:
            raise ValueError(f"No '{which}' backup available.")
        await coord.async_import_blob(blob)  # import + save + notify

    async def svc_import_csv(call: ServiceCall) -> None:
        path = call.data.get("path")
        if not path:
            raise ValueError("Provide a CSV path (e.g. /config/www/polars.csv)")
        merge = bool(call.data.get("merge", False))
        fill_missing = bool(call.data.get("fill_missing", False))

        # 1) auto-backup current state
        blob = coord.export_blob()
        await coord.async_rotate_backup_with_blob(blob)

        # 2) import from CSV
        await coord.async_import_csv_file(path, merge=merge, fill_missing=fill_missing)

    hass.services.async_register(DOMAIN, "export_csv", svc_export_csv)
    hass.services.async_register(DOMAIN, "reset", svc_reset)
    hass.services.async_register(DOMAIN, "start_recording", svc_start)
    hass.services.async_register(DOMAIN, "stop_recording", svc_stop)
    hass.services.async_register(DOMAIN, "toggle_recording", _svc_toggle)
    hass.services.async_register(DOMAIN, "backup_matrix", svc_backup)
    hass.services.async_register(DOMAIN, "restore_matrix", svc_restore)
    hass.services.async_register(DOMAIN, "import_csv", svc_import_csv)
    hass.services.async_register(DOMAIN, "set_cell", svc_set_cell)
    hass.services.async_register(DOMAIN, "clear_cell", svc_clear_cell)
    hass.services.async_register(DOMAIN, "scale_line", svc_scale_line)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coord: PolarCoordinator = entry.runtime_data
    await coord.async_unload()
    # Best-effort service cleanup (in case of single-entry use)
    try:
        hass.services.async_remove(DOMAIN, "export_csv")
        hass.services.async_remove(DOMAIN, "reset")
        hass.services.async_remove(DOMAIN, "start_recording")
        hass.services.async_remove(DOMAIN, "stop_recording")
        hass.services.async_remove(DOMAIN, "toggle_recording")
        hass.services.async_remove(DOMAIN, "backup_matrix")
        hass.services.async_remove(DOMAIN, "restore_matrix")
        hass.services.async_remove(DOMAIN, "import_csv")
    except Exception:
        pass
    return unloaded