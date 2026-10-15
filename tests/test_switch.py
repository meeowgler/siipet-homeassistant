"""Tests for the fill-light switches of the cameras."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siipet.api import DeviceState
from custom_components.siipet.api.lrtm import LrtmError

from .common import DEVICE_STATE, FakeShadowLink, setup_integration

AUTO = "switch.bathroom_auto_fill_light"
NIGHT = "switch.bathroom_night_vision_fill_light"


async def _setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    links: list[FakeShadowLink],
    state: DeviceState = DEVICE_STATE,
) -> None:
    await setup_integration(hass, config_entry)
    links[0].on_connection(True)
    links[0].on_state("SN0001", state)
    await hass.async_block_till_done()


async def _switch(hass: HomeAssistant, entity_id: str, on: bool) -> None:
    await hass.services.async_call(
        "switch",
        "turn_on" if on else "turn_off",
        {"entity_id": entity_id},
        blocking=True,
    )


async def test_shows_reported_values(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Both switches show the reported fill-light fields."""
    await _setup(hass, config_entry, shadow_links)
    assert hass.states.get(AUTO).state == STATE_ON
    assert hass.states.get(NIGHT).state == STATE_ON


async def test_turn_off_auto(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Turning off auto sends the payload with autoLight false, keeping the rest."""
    await _setup(hass, config_entry, shadow_links)
    await _switch(hass, AUTO, False)
    mock_control.send.assert_awaited_once_with(
        "SN0001",
        "config.fillLight",
        {"autoLight": False, "brightness2": 70, "level": 2, "lowLight": True},
    )
    assert hass.states.get(AUTO).state == STATE_OFF


async def test_turn_off_night_vision(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Turning off night vision sends lowLight false and keeps auto and level."""
    await _setup(hass, config_entry, shadow_links)
    await _switch(hass, NIGHT, False)
    mock_control.send.assert_awaited_once_with(
        "SN0001",
        "config.fillLight",
        {"autoLight": True, "brightness2": 70, "level": 2, "lowLight": False},
    )
    assert hass.states.get(NIGHT).state == STATE_OFF


async def test_reported_state_clears_pending(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A later reported state takes over from the pending value."""
    await _setup(hass, config_entry, shadow_links)
    await _switch(hass, NIGHT, False)
    assert hass.states.get(NIGHT).state == STATE_OFF
    shadow_links[0].on_state("SN0001", replace(DEVICE_STATE, fill_light_low=True))
    await hass.async_block_till_done()
    assert hass.states.get(NIGHT).state == STATE_ON


async def test_failed_command_raises_and_reverts(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A rejected command raises and the switch returns to its reported value."""
    await _setup(hass, config_entry, shadow_links)
    mock_control.send.side_effect = LrtmError("offline")
    with pytest.raises(HomeAssistantError):
        await _switch(hass, AUTO, False)
    assert hass.states.get(AUTO).state == STATE_ON


async def test_absent_before_first_state(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The switches are created once the camera first reports, like the sensors."""
    await setup_integration(hass, config_entry)
    shadow_links[0].on_connection(True)
    await hass.async_block_till_done()
    assert hass.states.get(AUTO) is None
