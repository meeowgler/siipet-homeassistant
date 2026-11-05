"""Tests for the device state coordinator and its link."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.siipet.api import CameraShadows
from custom_components.siipet.const import DOMAIN

from .common import (
    DEVICE_STATE,
    SHADOWS,
    TODAY,
    FakeShadowLink,
    mirror_visit,
    mock_s3,
    serve_days,
    setup_integration,
    setup_mirror,
)


async def _push(hass: HomeAssistant, link: FakeShadowLink, sn: str = "SN0001") -> None:
    link.on_state(sn, DEVICE_STATE)
    await hass.async_block_till_done()


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_link_starts_after_setup(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Setup starts one link with the shadows of each camera."""
    await setup_integration(hass, config_entry)
    [link] = shadow_links
    assert link.running
    assert link.cameras == {"SN0001": SHADOWS, "SN0002": SHADOWS}
    assert link.label("SN0002") == "Hallway"
    assert link.label("SN0099") == "a removed camera"
    assert link.fetch_credentials == mock_client.get_iot_credentials
    assert config_entry.runtime_data.device_state.data == {}


async def test_state_is_stored(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A state from the link is stored by serial number."""
    await setup_integration(hass, config_entry)
    await _push(hass, shadow_links[0])
    device_state = config_entry.runtime_data.device_state
    assert device_state.data == {"SN0001": DEVICE_STATE}
    assert device_state.last_update_success


async def test_dropped_state_is_removed(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A `None` state removes the camera from the data and keeps the coordinator working."""
    await setup_integration(hass, config_entry)
    link = shadow_links[0]
    await _push(hass, link)
    await _push(hass, link, "SN0002")
    device_state = config_entry.runtime_data.device_state
    updates: list[None] = []
    device_state.async_add_listener(lambda: updates.append(None))
    link.on_state("SN0001", None)
    await hass.async_block_till_done()
    assert device_state.data == {"SN0002": DEVICE_STATE}
    assert device_state.last_update_success
    assert len(updates) == 1
    link.on_state("SN0001", None)
    await hass.async_block_till_done()
    assert len(updates) == 1


async def test_state_of_unknown_camera_is_ignored(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A state for a camera that is not in the list is dropped."""
    await setup_integration(hass, config_entry)
    await _push(hass, shadow_links[0], "SN0099")
    assert config_entry.runtime_data.device_state.data == {}


async def test_firmware_goes_to_the_device(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The firmware version becomes the software version of the camera device."""
    await setup_integration(hass, config_entry)
    await _push(hass, shadow_links[0])
    registry = dr.async_get(hass)
    identifier = (DOMAIN, "SN0001")
    device = registry.async_get_device_by_identifier(identifier, config_entry.entry_id)
    assert device.sw_version == "1.2.3"
    shadow_links[0].on_state("SN0001", replace(DEVICE_STATE, firmware="1.2.4"))
    await hass.async_block_till_done()
    device = registry.async_get_device_by_identifier(identifier, config_entry.entry_id)
    assert device.sw_version == "1.2.4"


async def test_grace_before_failure(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The coordinator fails only after 15 minutes without a connection."""
    await setup_integration(hass, config_entry)
    link = shadow_links[0]
    device_state = config_entry.runtime_data.device_state
    await _push(hass, link)
    link.on_connection(False)
    await _tick(hass, freezer, timedelta(minutes=14))
    assert device_state.last_update_success
    await _tick(hass, freezer, timedelta(minutes=1, seconds=1))
    assert not device_state.last_update_success
    link.on_connection(True)
    await _push(hass, link)
    assert device_state.last_update_success


async def test_reconnect_stops_the_grace(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A new connection within the grace keeps the coordinator working."""
    await setup_integration(hass, config_entry)
    link = shadow_links[0]
    await _push(hass, link)
    link.on_connection(False)
    link.on_connection(True)
    await _tick(hass, freezer, timedelta(minutes=16))
    assert config_entry.runtime_data.device_state.last_update_success


async def test_grace_starts_before_the_first_connection(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A link that never connects fails the coordinator after 15 minutes."""
    await setup_integration(hass, config_entry)
    device_state = config_entry.runtime_data.device_state
    await _tick(hass, freezer, timedelta(minutes=14))
    assert device_state.last_update_success
    await _tick(hass, freezer, timedelta(minutes=1, seconds=1))
    assert not device_state.last_update_success


async def test_camera_list_change(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A camera sync that drops a camera updates the link and drops its state."""
    await setup_integration(hass, config_entry)
    link = shadow_links[0]
    await _push(hass, link, "SN0002")
    cameras = dict(mock_client.get_cameras.return_value)
    del cameras["SN0002"]
    mock_client.get_cameras.return_value = cameras
    await _tick(hass, freezer, timedelta(hours=1))
    assert link.cameras == {"SN0001": SHADOWS}
    assert "SN0002" not in config_entry.runtime_data.device_state.data


async def test_shadow_rename_drops_the_state(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A camera sync that renames the shadows of a camera drops its old state."""
    await setup_integration(hass, config_entry)
    link = shadow_links[0]
    await _push(hass, link)
    cameras = dict(mock_client.get_cameras.return_value)
    new_shadows = CameraShadows(config="next_configInfo", system="next_systemInfo")
    cameras["SN0001"] = replace(cameras["SN0001"], shadows=new_shadows)
    mock_client.get_cameras.return_value = cameras
    await _tick(hass, freezer, timedelta(hours=1))
    assert "SN0001" not in config_entry.runtime_data.device_state.data
    assert link.cameras["SN0001"] == new_shadows


async def test_firmware_cache_drops_removed_cameras(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A camera that leaves and comes back gets its firmware written again."""
    await setup_integration(hass, config_entry)
    link = shadow_links[0]
    await _push(hass, link, "SN0002")
    registry = dr.async_get(hass)
    identifier = (DOMAIN, "SN0002")
    device = registry.async_get_device_by_identifier(identifier, config_entry.entry_id)
    assert device.sw_version == "1.2.3"
    cameras = dict(mock_client.get_cameras.return_value)
    mock_client.get_cameras.return_value = {
        sn: camera for sn, camera in cameras.items() if sn != "SN0002"
    }
    await _tick(hass, freezer, timedelta(hours=1))
    assert link.cameras == {"SN0001": SHADOWS}
    # The device can be removed and made again while the camera is away.
    # Then it has no version.
    registry.async_update_device(device.id, sw_version=None)
    mock_client.get_cameras.return_value = cameras
    await _tick(hass, freezer, timedelta(hours=1))
    assert link.cameras == {"SN0001": SHADOWS, "SN0002": SHADOWS}
    await _push(hass, link, "SN0002")
    device = registry.async_get_device_by_identifier(identifier, config_entry.entry_id)
    assert device.sw_version == "1.2.3"


async def test_unload_stops_the_link(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Unload stops the link and the grace timer."""
    await setup_integration(hass, config_entry)
    shadow_links[0].on_connection(False)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert shadow_links[0].stopped


# The frozen clock stops asyncio timers. The signal timer of pytest-timeout
# still fires, so a setup that waits for the link fails instead of hanging.
@pytest.mark.timeout(10)
async def test_link_runs_as_a_background_task(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The link runs in the background, so setup never waits for it."""
    monkeypatch.setattr(FakeShadowLink, "keep_running", True)
    await setup_integration(hass, config_entry)
    link = shadow_links[0]
    assert link.running
    assert not link.stopped
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert link.stopped
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_link_runs_next_to_the_local_media_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    shadow_links: list[FakeShadowLink],
) -> None:
    """With the local media copy on, setup starts both, and unload stops both."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    [link] = shadow_links
    assert link.running
    mirror = config_entry.runtime_data.mirror
    assert mirror is not None
    assert mirror.running
    await _push(hass, link)
    assert config_entry.runtime_data.device_state.data == {"SN0001": DEVICE_STATE}
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert link.stopped
    assert not mirror.running
