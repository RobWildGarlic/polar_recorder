from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

DOMAIN = "polar_recorder"


@pytest.mark.asyncio
async def test_setup_component(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
