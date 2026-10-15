"""Tests for the fill-light select of the cameras."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siipet.api import DeviceState
from custom_components.siipet.api.lrtm import LrtmError

from .common import DEVICE_STATE, FakeShadowLink, setup_integration

SELECT = "select.bathroom_night_light_brightness"


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


async def _select(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": option},
        blocking=True,
    )


async def test_shows_reported_level(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The select shows the reported level and the three options."""
    await _setup(hass, config_entry, shadow_links)
    state = hass.states.get(SELECT)
    assert state.state == "medium"
    assert state.attributes["options"] == ["low", "medium", "high"]


async def test_select_sends_command(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Choosing a level sends the full fill-light payload for that level."""
    await _setup(hass, config_entry, shadow_links)
    await _select(hass, "high")
    mock_control.send.assert_awaited_once_with(
        "SN0001",
        "config.fillLight",
        {"autoLight": True, "brightness2": 120, "level": 3, "lowLight": True},
    )
    # The new level shows at once, before the camera reports it back.
    assert hass.states.get(SELECT).state == "high"


async def test_reported_state_clears_pending(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A later reported state takes over from the pending value."""
    await _setup(hass, config_entry, shadow_links)
    await _select(hass, "low")
    assert hass.states.get(SELECT).state == "low"
    shadow_links[0].on_state("SN0001", replace(DEVICE_STATE, fill_light=3))
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "high"


async def test_failed_command_raises_and_reverts(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A rejected command raises and the select returns to the reported level."""
    await _setup(hass, config_entry, shadow_links)
    mock_control.send.side_effect = LrtmError("offline")
    with pytest.raises(HomeAssistantError):
        await _select(hass, "high")
    assert hass.states.get(SELECT).state == "medium"


async def test_absent_before_first_state(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The select is created once the camera first reports, like the sensors."""
    await setup_integration(hass, config_entry)
    shadow_links[0].on_connection(True)
    await hass.async_block_till_done()
    assert hass.states.get(SELECT) is None
