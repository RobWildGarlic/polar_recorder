from __future__ import annotations
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector, EntitySelectorConfig,
    NumberSelector, NumberSelectorConfig,
)

from .const import (
    DOMAIN,
    CONF_TWA, CONF_TWS, CONF_BSP,
    CONF_TWA_MIN, CONF_TWA_MAX, CONF_TWA_STEP,
    CONF_TWS_MIN, CONF_TWS_MAX, CONF_TWS_STEP,
    CONF_FOLD_0_180, CONF_INTERPOLATE,
    CONF_RECORD_GATE,
    CONF_MIN_TWS, CONF_MIN_BSP,
    # NEW: Smart2000ESP cooperation
    CONF_SMART_FAST_SECONDS,
    SMART2000ESP_DOMAIN, SMART2000ESP_SERVICE_SET_UPDATE,
    DEFAULTS,
)


def _schema(hass, defaults: dict[str, Any]) -> vol.Schema:
    """Build the (options) form schema with optional fields."""
    s: dict[Any, Any] = {
        # Required core sensors
        vol.Required(CONF_TWA, default=defaults.get(CONF_TWA, "")):
            EntitySelector(EntitySelectorConfig(domain=["sensor"])),
        vol.Required(CONF_TWS, default=defaults.get(CONF_TWS, "")):
            EntitySelector(EntitySelectorConfig(domain=["sensor"])),
        vol.Required(CONF_BSP, default=defaults.get(CONF_BSP, "")):
            EntitySelector(EntitySelectorConfig(domain=["sensor"])),

        # Binning / ranges
        vol.Optional(CONF_TWA_MIN, default=defaults.get(CONF_TWA_MIN, DEFAULTS[CONF_TWA_MIN])):
            NumberSelector(NumberSelectorConfig(min=0, max=360, step=1, mode="box")),
        vol.Optional(CONF_TWA_MAX, default=defaults.get(CONF_TWA_MAX, DEFAULTS[CONF_TWA_MAX])):
            NumberSelector(NumberSelectorConfig(min=1, max=360, step=1, mode="box")),
        vol.Optional(CONF_TWA_STEP, default=defaults.get(CONF_TWA_STEP, DEFAULTS[CONF_TWA_STEP])):
            NumberSelector(NumberSelectorConfig(min=1, max=90, step=1, mode="box")),
        vol.Optional(CONF_TWS_MIN, default=defaults.get(CONF_TWS_MIN, DEFAULTS[CONF_TWS_MIN])):
            NumberSelector(NumberSelectorConfig(min=0, max=100, step=0.1, mode="box")),
        vol.Optional(CONF_TWS_MAX, default=defaults.get(CONF_TWS_MAX, DEFAULTS[CONF_TWS_MAX])):
            NumberSelector(NumberSelectorConfig(min=1, max=100, step=0.1, mode="box")),
        vol.Optional(CONF_TWS_STEP, default=defaults.get(CONF_TWS_STEP, DEFAULTS[CONF_TWS_STEP])):
            NumberSelector(NumberSelectorConfig(min=0.5, max=20, step=0.5, mode="box")),

        # Behaviour
        vol.Optional(CONF_FOLD_0_180, default=defaults.get(CONF_FOLD_0_180, DEFAULTS[CONF_FOLD_0_180])): bool,
        vol.Optional(CONF_INTERPOLATE, default=defaults.get(CONF_INTERPOLATE, DEFAULTS[CONF_INTERPOLATE])): bool,

        # Thresholds (OPTIONAL)
        vol.Optional(CONF_MIN_TWS, default=defaults.get(CONF_MIN_TWS, DEFAULTS[CONF_MIN_TWS])):
            NumberSelector(NumberSelectorConfig(min=0, max=100, step=0.1, mode="box")),
        vol.Optional(CONF_MIN_BSP, default=defaults.get(CONF_MIN_BSP, DEFAULTS[CONF_MIN_BSP])):
            NumberSelector(NumberSelectorConfig(min=0, max=50, step=0.1, mode="box")),
    }

    # Record gate OPTIONAL (no default when empty; avoids “required” behavior)
    rec_default = defaults.get(CONF_RECORD_GATE)
    if rec_default:
        s[vol.Optional(CONF_RECORD_GATE, default=rec_default)] = EntitySelector(
            EntitySelectorConfig(domain=["input_boolean", "switch", "binary_sensor"], multiple=False)
        )
    else:
        s[vol.Optional(CONF_RECORD_GATE)] = EntitySelector(
            EntitySelectorConfig(domain=["input_boolean", "switch", "binary_sensor"], multiple=False)
        )

    # Smart2000ESP fast interval (only if integration/service is present)
    try:
        show_smart = hass.services.has_service(SMART2000ESP_DOMAIN, SMART2000ESP_SERVICE_SET_UPDATE)
    except Exception:
        show_smart = False

    if show_smart:
        s[vol.Optional(
            CONF_SMART_FAST_SECONDS,
            default=defaults.get(CONF_SMART_FAST_SECONDS, DEFAULTS[CONF_SMART_FAST_SECONDS]),
        )] = NumberSelector(
            NumberSelectorConfig(min=0.1, max=10.0, step=0.1, mode="box")
        )

    return vol.Schema(s)


class PolarFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            # Normalize optional gate: missing/None => empty string
            if not user_input.get(CONF_RECORD_GATE):
                user_input[CONF_RECORD_GATE] = ""
            return self.async_create_entry(title="Polar Recorder", data=user_input)

        form_schema = _schema(self.hass, DEFAULTS)
        return self.async_show_form(
            step_id="user",
            data_schema=form_schema,
            description_placeholders={},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PolarOptionsFlow(config_entry)


class PolarOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            if not user_input.get(CONF_RECORD_GATE):
                user_input[CONF_RECORD_GATE] = ""
            return self.async_create_entry(title="", data=user_input)

        data = {**DEFAULTS, **self.entry.data, **self.entry.options}
        form_schema = _schema(self.hass, data)
        return self.async_show_form(step_id="init", data_schema=form_schema)