# custom_components/polar_recorder/const.py

from __future__ import annotations

# --- Core ---
DOMAIN = "polar_recorder"
# You can keep PLATFORMS here or define it locally in __init__.py.
PLATFORMS: list[str] = ["sensor"]

# Storage for the matrix/backups
STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION = 1

# --- Entity / sensor config keys (used in config_flow, coordinator, sensor) ---
CONF_TWA = "entity_twa"          # True Wind Angle sensor entity_id
CONF_TWS = "entity_tws"          # True Wind Speed sensor entity_id
CONF_BSP = "entity_bsp"          # Boat speed (STW) sensor entity_id

# Binning / ranges
CONF_TWA_MIN = "twa_min"
CONF_TWA_MAX = "twa_max"
CONF_TWA_STEP = "twa_step"

CONF_TWS_MIN = "tws_min"
CONF_TWS_MAX = "tws_max"
CONF_TWS_STEP = "tws_step"

# Behaviour flags
CONF_FOLD_0_180 = "fold_to_180"
CONF_INTERPOLATE = "interpolate"

# Optional recording gate
CONF_RECORD_GATE = "record_gate_entity"

# Thresholds (optional)
CONF_MIN_TWS = "min_tws"
CONF_MIN_BSP = "min_bsp"

# Lull guard & smoothing (user-tunable via DEFAULTS or UI if you add selectors)
CONF_TWS_EMA_ALPHA = "tws_ema_alpha"        # 0..1 smoothing factor for TWS EMA
CONF_LULL_GUARD_DELTA = "lull_guard_delta"  # kn below EMA considered lull

# Smart2000ESP cooperation (optional)
SMART2000ESP_DOMAIN = "smart2000esp"
SMART2000ESP_SERVICE_SET_UPDATE = "set_update_interval"
CONF_SMART_FAST_SECONDS = "smart_fast_seconds"  # fast poll while recording

# --- Defaults used when keys are omitted ---
DEFAULTS: dict[str, float | int | bool | str] = {
    # Binning defaults
    CONF_TWA_MIN: 0,
    CONF_TWA_MAX: 180,
    CONF_TWA_STEP: 10,
    CONF_TWS_MIN: 0.0,
    CONF_TWS_MAX: 30.0,
    CONF_TWS_STEP: 2.0,

    # Behaviour
    CONF_FOLD_0_180: True,
    CONF_INTERPOLATE: True,

    # Thresholds
    CONF_MIN_TWS: 2.0,    # ignore calms by default
    CONF_MIN_BSP: 0.5,    # ignore near-zero boat speed

    # Lull guard & smoothing
    CONF_TWS_EMA_ALPHA: 0.20,       # 20% new / 80% history
    CONF_LULL_GUARD_DELTA: 0.5,     # 0.5 kn below EMA -> skip

    # Smart2000ESP fast interval while recording
    CONF_SMART_FAST_SECONDS: 0.5,
}