"""Tests for the device state sensors of the cameras."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import logging
from unittest.mock import AsyncMock, PropertyMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.siipet.api import DeviceState

from .common import DEVICE_STATE, FakeShadowLink, setup_integration


async def _setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    link_list: list[FakeShadowLink],
    state: DeviceState = DEVICE_STATE,
) -> None:
    await setup_integration(hass, config_entry)
    link_list[0].on_connection(True)
    link_list[0].on_state("SN0001", state)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("entity_id", "state"),
    [
        ("sensor.bathroom_battery", "72"),
        ("sensor.bathroom_last_report", "2026-09-26T11:55:00+00:00"),
        ("sensor.bathroom_fill_light", "medium"),
        ("sensor.bathroom_motion_sensitivity", "high"),
        ("sensor.bathroom_firmware_update_mode", "automatic"),
    ],
)
async def test_camera_state_sensors(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    entity_id: str,
    state: str,
) -> None:
    """Each sensor shows its device state value."""
    await _setup(hass, config_entry, shadow_links)
    assert hass.states.get(entity_id).state == state


async def test_battery_attributes(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The battery sensor is a percentage measurement."""
    await _setup(hass, config_entry, shadow_links)
    attributes = hass.states.get("sensor.bathroom_battery").attributes
    assert attributes["device_class"] == "battery"
    assert attributes["unit_of_measurement"] == "%"
    assert attributes["state_class"] == "measurement"


@pytest.mark.parametrize(
    ("battery", "charging", "icon"),
    [
        (72, False, None),
        (72, None, None),
        (None, True, None),
        (0, True, "mdi:battery-charging-outline"),
        (9, True, "mdi:battery-charging-outline"),
        (10, True, "mdi:battery-charging-10"),
        (19, True, "mdi:battery-charging-10"),
        (20, True, "mdi:battery-charging-20"),
        (75, True, "mdi:battery-charging-70"),
        (99, True, "mdi:battery-charging-90"),
        (100, True, "mdi:battery-charging"),
        (130, True, "mdi:battery-charging"),
        (-5, True, "mdi:battery-charging-outline"),
    ],
)
async def test_battery_charging_icon(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    battery: int | None,
    charging: bool | None,
    icon: str | None,
) -> None:
    """A charging camera gets a charging battery icon. Otherwise the sensor sets none."""
    await _setup(
        hass,
        config_entry,
        shadow_links,
        replace(DEVICE_STATE, battery=battery, charging=charging),
    )
    assert hass.states.get("sensor.bathroom_battery").attributes.get("icon") == icon


async def test_battery_icon_follows_charging(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The charging icon comes and goes with the pushed charging state."""
    await _setup(hass, config_entry, shadow_links)
    shadow_links[0].on_state("SN0001", replace(DEVICE_STATE, charging=True))
    await hass.async_block_till_done()
    attributes = hass.states.get("sensor.bathroom_battery").attributes
    assert attributes["icon"] == "mdi:battery-charging-70"
    shadow_links[0].on_state("SN0001", DEVICE_STATE)
    await hass.async_block_till_done()
    assert "icon" not in hass.states.get("sensor.bathroom_battery").attributes


async def test_unavailable_battery_has_no_icon(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A battery sensor without a camera state sets no icon."""
    await _setup(hass, config_entry, shadow_links, replace(DEVICE_STATE, charging=True))
    shadow_links[0].on_state("SN0001", None)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.bathroom_battery")
    assert state.state == STATE_UNAVAILABLE
    assert "icon" not in state.attributes


async def test_enum_options(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The enum sensors list the options that the app names."""
    await _setup(hass, config_entry, shadow_links)
    options = hass.states.get("sensor.bathroom_fill_light").attributes["options"]
    assert options == ["low", "medium", "high"]


async def test_wifi_signal_is_disabled(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The Wi-Fi signal sensor exists, but it is disabled by default."""
    await _setup(hass, config_entry, shadow_links)
    entry = entity_registry.async_get("sensor.bathroom_wi_fi_signal")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get("sensor.bathroom_wi_fi_signal") is None


async def test_wifi_signal(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """When enabled, the Wi-Fi signal shows the RSSI in dBm."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        await _setup(hass, config_entry, shadow_links)
    state = hass.states.get("sensor.bathroom_wi_fi_signal")
    assert state.state == "-61"
    assert state.attributes["unit_of_measurement"] == "dBm"


async def test_unknown_code(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A code that the app does not name gives an unknown state and one log line."""
    caplog.set_level(logging.DEBUG, logger="custom_components.siipet")
    await _setup(hass, config_entry, shadow_links, replace(DEVICE_STATE, fill_light=7))
    assert hass.states.get("sensor.bathroom_fill_light").state == STATE_UNKNOWN
    shadow_links[0].on_state("SN0001", replace(DEVICE_STATE, fill_light=7, battery=70))
    await hass.async_block_till_done()
    lines = [r for r in caplog.records if "unknown code 7" in r.getMessage()]
    assert len(lines) == 1
    assert "sensor.bathroom_fill_light" in lines[0].getMessage()


async def test_first_state_adds_entities(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Only a camera with a state gets device state entities."""
    await setup_integration(hass, config_entry)
    assert hass.states.get("sensor.bathroom_battery") is None
    shadow_links[0].on_state("SN0001", DEVICE_STATE)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.bathroom_battery").state == "72"
    assert hass.states.get("sensor.hallway_battery") is None


async def test_unavailable_after_grace(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The entities become unavailable 15 minutes after the connection drops."""
    await _setup(hass, config_entry, shadow_links)
    shadow_links[0].on_connection(False)
    freezer.tick(timedelta(minutes=15, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.bathroom_battery").state == STATE_UNAVAILABLE
    shadow_links[0].on_connection(True)
    shadow_links[0].on_state("SN0001", DEVICE_STATE)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.bathroom_battery").state == "72"


async def test_removed_camera_is_unavailable(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A camera that leaves the account turns its entities unavailable."""
    await _setup(hass, config_entry, shadow_links)
    cameras = dict(mock_client.get_cameras.return_value)
    del cameras["SN0001"]
    mock_client.get_cameras.return_value = cameras
    freezer.tick(timedelta(hours=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.bathroom_battery").state == STATE_UNAVAILABLE


async def test_manual_update_keeps_the_state(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A manual entity update keeps the device state and its coordinator working."""
    await _setup(hass, config_entry, shadow_links)
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.services.async_call(
        "homeassistant",
        "update_entity",
        {"entity_id": "sensor.bathroom_battery"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert config_entry.runtime_data.device_state.last_update_success
    assert hass.states.get("sensor.bathroom_battery").state == "72"


async def test_missing_value_is_unknown(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A value that the shadow does not have gives an unknown state."""
    await _setup(hass, config_entry, shadow_links, replace(DEVICE_STATE, battery=None))
    assert hass.states.get("sensor.bathroom_battery").state == STATE_UNKNOWN


async def test_dropped_state_turns_entities_unavailable(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A camera whose state is dropped turns its entities unavailable."""
    await _setup(hass, config_entry, shadow_links)
    assert hass.states.get("sensor.bathroom_battery").state == "72"
    shadow_links[0].on_state("SN0001", None)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.bathroom_battery").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.bathroom_online").state == STATE_UNAVAILABLE
