# custom_components/polar_recorder/number.py
from __future__ import annotations

import contextlib
import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import PolarCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Polar Recorder UI number entities."""
    coord: PolarCoordinator = entry.runtime_data
    _LOGGER.debug("[%s] Setting up number platform entities", DOMAIN)

    base = _device_info(entry)
    entities: list[NumberEntity] = [
        _PolarIntNumber(
            entry.entry_id,
            coord,
            "polar_edit_twa",
            "Polar Edit TWA",
            "mdi:angle-acute",
            0,
            180,
            1,
            0,
            base,
        ),
        _PolarIntNumber(
            entry.entry_id,
            coord,
            "polar_edit_tws",
            "Polar Edit TWS",
            "mdi:windsock",
            0,
            100,
            1,
            10,
            base,
        ),
        _PolarFloatNumber(
            entry.entry_id,
            coord,
            "polar_edit_bsp",
            "Polar Edit BSP",
            "mdi:speedometer",
            0.0,
            50.0,
            0.1,
            6.0,
            base,
        ),
        _PolarFloatNumber(
            entry.entry_id,
            coord,
            "polar_scale_factor",
            "Polar Scale Factor",
            "mdi:chart-bell-curve",
            0.01,
            10.0,
            0.01,
            1.00,
            base,
        ),
    ]
    for e in entities:
        _LOGGER.debug(
            "[%s] Adding number entity %s (unique_id=%s)", DOMAIN, e.name, e.unique_id
        )

    async_add_entities(entities, update_before_add=True)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Polar Recorder",
        manufacturer="Polar Recorder",
        model="Polar Editor",
        entry_type=DeviceEntryType.SERVICE,
    )


class _PolarIntNumber(NumberEntity, RestoreEntity):
    """Integer number entity for TWA/TWS bins."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        unique_prefix: str,
        coord: PolarCoordinator,
        key: str,
        name: str,
        icon: str,
        min_value: int,
        max_value: int,
        step: int,
        default: int,
        device_info: DeviceInfo,
    ) -> None:
        self._coord = coord
        self._key = key
        self._attr_unique_id = f"{unique_prefix}-{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_min_value = int(min_value)
        self._attr_native_max_value = int(max_value)
        self._attr_native_step = int(step)
        self._value = int(default)
        self._attr_device_info = device_info

    @property
    def native_value(self) -> int | None:
        return int(self._value)

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None:
            with contextlib.suppress(TypeError, ValueError):
                self._value = int(float(last.state))

    async def async_set_native_value(self, value: float) -> None:
        self._value = round(value)
        self.async_write_ha_state()


class _PolarFloatNumber(NumberEntity, RestoreEntity):
    """Floating point number entity for BSP and scale factor."""

    _attr_should_poll = False
    _attr_has_entity_name = False
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        unique_prefix: str,
        coord: PolarCoordinator,
        key: str,
        name: str,
        icon: str,
        min_value: float,
        max_value: float,
        step: float,
        default: float,
        device_info: DeviceInfo,
    ) -> None:
        self._coord = coord
        self._key = key
        self._attr_unique_id = f"{unique_prefix}-{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_min_value = float(min_value)
        self._attr_native_max_value = float(max_value)
        self._attr_native_step = float(step)
        self._value = float(default)
        self._attr_device_info = device_info

    @property
    def native_value(self) -> float | None:
        return float(self._value)

    async def async_added_to_hass(self) -> None:
        last = await self.async_get_last_state()
        if last is not None:
            with contextlib.suppress(TypeError, ValueError):
                self._value = float(last.state)

    async def async_set_native_value(self, value: float) -> None:
        self._value = float(value)
        self.async_write_ha_state()
