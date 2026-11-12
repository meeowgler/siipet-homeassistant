"""Tests for the camera setting selects."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import ANY, AsyncMock

from homeassistant.const import STATE_UNKNOWN, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.siipet.api import DeviceState, LrtmServerError

from .common import DEVICE_STATE, FakeShadowLink, camera_reports, setup_integration

LEVEL = "select.bathroom_night_light_brightness"
MOTION = "select.bathroom_motion_sensitivity"


async def _setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    links: list[FakeShadowLink],
    state: DeviceState = DEVICE_STATE,
) -> FakeShadowLink:
    await setup_integration(hass, config_entry)
    links[0].on_connection(True)
    links[0].on_state("SN0001", state)
    await hass.async_block_till_done()
    return links[0]


async def _select(hass: HomeAssistant, entity_id: str, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": option},
        blocking=True,
    )


async def test_selects_show_reported_levels(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    entity_registry: er.EntityRegistry,
) -> None:
    """Both selects show the reported level with the app's labels."""
    await _setup(hass, config_entry, shadow_links)
    level = hass.states.get(LEVEL)
    assert level.state == "standard"
    assert level.attributes["options"] == ["low", "standard", "high"]
    motion = hass.states.get(MOTION)
    assert motion.state == "high"
    assert motion.attributes["options"] == ["standard", "high"]
    for entity_id in (LEVEL, MOTION):
        entry = entity_registry.async_get(entity_id)
        assert entry.entity_category is EntityCategory.CONFIG


async def test_level_outside_the_options(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A level the app does not offer shows as unknown."""
    await _setup(hass, config_entry, shadow_links, replace(DEVICE_STATE, fill_light=0))
    assert hass.states.get(LEVEL).state == STATE_UNKNOWN


async def test_select_level(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Choosing a level sends the full fill light object and shows the reported level."""
    link = await _setup(hass, config_entry, shadow_links)
    mock_control.send.side_effect = camera_reports(link, fill_light=3)
    await _select(hass, LEVEL, "high")
    mock_control.send.assert_awaited_once_with(
        "SN0001",
        "config.fillLight",
        {"level": 3, "brightness2": 120, "autoLight": True, "lowLight": True},
        limit=ANY,
        still_wanted=ANY,
    )
    assert hass.states.get(LEVEL).state == "high"


async def test_select_motion(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Choosing standard sends level 2 with its sense value."""
    link = await _setup(hass, config_entry, shadow_links)
    mock_control.send.side_effect = camera_reports(link, motion_level=2)
    await _select(hass, MOTION, "standard")
    mock_control.send.assert_awaited_once_with(
        "SN0001",
        "config.pir.sense",
        {"sense": 75, "level": 2},
        limit=ANY,
        still_wanted=ANY,
    )
    assert hass.states.get(MOTION).state == "standard"


async def test_select_error(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A failed change raises a translated error and keeps the reported level."""
    await _setup(hass, config_entry, shadow_links)
    mock_control.send.side_effect = LrtmServerError(103)
    with pytest.raises(HomeAssistantError) as err:
        await _select(hass, MOTION, "standard")
    assert err.value.translation_key == "change_partial"
    assert hass.states.get(MOTION).state == "high"
