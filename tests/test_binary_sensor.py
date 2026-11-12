"""Tests for the SiiPet binary sensors."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant.common import MockConfigEntry

from .common import DEVICE_STATE, FakeShadowLink, setup_integration


@pytest.mark.parametrize(
    ("entity_id", "state", "category"),
    [
        ("binary_sensor.bathroom_charging", "off", None),
        ("binary_sensor.bathroom_online", "on", "diagnostic"),
        ("binary_sensor.bathroom_cloud_storage", "on", "diagnostic"),
    ],
)
async def test_binary_sensor_states(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    entity_id: str,
    state: str,
    category: str | None,
) -> None:
    """Each binary sensor shows its device state value."""
    await setup_integration(hass, config_entry)
    shadow_links[0].on_state("SN0001", DEVICE_STATE)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == state
    entry = entity_registry.async_get(entity_id)
    assert entry.unique_id == f"SN0001_{entity_id.split('bathroom_')[1]}"
    assert (entry.entity_category or None) == category


async def test_binary_sensor_device_classes(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Charging and online use the Home Assistant device classes."""
    await setup_integration(hass, config_entry)
    shadow_links[0].on_state("SN0001", DEVICE_STATE)
    await hass.async_block_till_done()
    charging = hass.states.get("binary_sensor.bathroom_charging")
    assert charging.attributes["device_class"] == "battery_charging"
    online = hass.states.get("binary_sensor.bathroom_online")
    assert online.attributes["device_class"] == "connectivity"


async def test_missing_value_is_unknown(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A value that the shadow does not have gives an unknown state."""
    await setup_integration(hass, config_entry)
    shadow_links[0].on_state("SN0001", replace(DEVICE_STATE, charging=None))
    await hass.async_block_till_done()
    state = hass.states.get("binary_sensor.bathroom_charging")
    assert state.state == STATE_UNKNOWN
