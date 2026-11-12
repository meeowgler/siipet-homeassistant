"""Tests for the device state coordinator and its link."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from datetime import timedelta
from typing import Any
from unittest.mock import ANY, AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.siipet.api import (
    CameraShadows,
    DeviceState,
    FeatureRules,
    LrtmServerError,
    LrtmTransportError,
    LrtmUnconfirmedError,
    ShadowWriteError,
    SiiPetAuthError,
)
from custom_components.siipet.api.settings import (
    FillLightChange,
    MotionChange,
    PrivacyChange,
)
from custom_components.siipet.api.shadow_link import WriteResult
from custom_components.siipet.const import CHANGE_TIMEOUT, DOMAIN
from custom_components.siipet.device_state import SiiPetDeviceCoordinator

from .common import (
    DEVICE_STATE,
    SHADOWS,
    TODAY,
    FakeShadowLink,
    camera_reports,
    mirror_visit,
    mock_s3,
    serve_days,
    setup_integration,
    setup_mirror,
)

# The frozen clock stops asyncio timers. The signal timer of pytest-timeout
# still fires, so a setup that waits for the link, or a change that waits for
# a report, fails instead of hanging.
pytestmark = pytest.mark.timeout(10)


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


FILL_PAYLOAD_HIGH = {
    "level": 3,
    "brightness2": 120,
    "autoLight": True,
    "lowLight": True,
}


async def _hub(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    state: DeviceState = DEVICE_STATE,
) -> tuple[SiiPetDeviceCoordinator, FakeShadowLink]:
    await setup_integration(hass, config_entry)
    link = shadow_links[0]
    link.on_connection(True)
    link.on_state("SN0001", state)
    await hass.async_block_till_done()
    return config_entry.runtime_data.device_state, link


async def _expire(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(CHANGE_TIMEOUT + timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _until_awaited(method: AsyncMock, count: int = 1) -> None:
    for _ in range(100):
        if method.await_count >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError("The call did not start")


async def _until_sent(mock_control: AsyncMock, count: int = 1) -> None:
    await _until_awaited(mock_control.send, count)


def _remove_camera(config_entry: MockConfigEntry, sn: str = "SN0001") -> None:
    """Drop a camera from the camera list, as a camera sync does."""
    coordinator = config_entry.runtime_data.coordinator
    cameras = {
        key: camera for key, camera in coordinator.data.cameras.items() if key != sn
    }
    coordinator.async_set_updated_data(replace(coordinator.data, cameras=cameras))


async def test_apply_fill_light(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The change writes desired, sends the command, and returns on the camera's report."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    mock_control.send.side_effect = camera_reports(link, fill_light=3)
    await hub.async_apply("SN0001", FillLightChange(level=3))
    link.update_desired.assert_awaited_once_with(
        "SN0001", "fillLight", FILL_PAYLOAD_HIGH, limit=ANY
    )
    mock_control.send.assert_awaited_once_with(
        "SN0001",
        "config.fillLight",
        FILL_PAYLOAD_HIGH,
        limit=ANY,
        still_wanted=ANY,
    )
    mock_client.get_device_settings.assert_awaited_once_with("SN0001", "1.2.3")
    assert hub.data["SN0001"].fill_light == 3


async def test_device_settings_are_cached(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A second change of the same firmware reads no detail again."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    mock_control.send.side_effect = camera_reports(link, fill_light=3)
    await hub.async_apply("SN0001", FillLightChange(level=3))
    mock_control.send.side_effect = camera_reports(link, fill_light=3, motion_level=2)
    await hub.async_apply("SN0001", MotionChange(level=2))
    assert mock_client.get_device_settings.await_count == 1


async def test_apply_privacy_sends_only_the_command(
    hass: HomeAssistant,
    mock_control: AsyncMock,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Privacy mode writes no desired and reads no detail."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    mock_control.send.side_effect = camera_reports(link, privacy=True)
    await hub.async_apply("SN0001", PrivacyChange(active=True))
    link.update_desired.assert_not_awaited()
    mock_client.get_device_settings.assert_not_awaited()
    mock_control.send.assert_awaited_once_with(
        "SN0001",
        "config.privacyMode",
        {"active": True},
        limit=ANY,
        still_wanted=ANY,
    )


async def test_apply_already_reported(
    hass: HomeAssistant,
    mock_control: AsyncMock,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A change the camera already reports sends nothing."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    await hub.async_apply("SN0001", MotionChange(level=3))
    link.update_desired.assert_not_awaited()
    mock_control.send.assert_not_awaited()


async def test_apply_not_confirmed(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Without the camera's report the change fails after the deadline."""
    hub, _link = await _hub(hass, config_entry, shadow_links)
    # Not a Home Assistant task: async_block_till_done would wait for it forever.
    task = asyncio.ensure_future(hub.async_apply("SN0001", PrivacyChange(active=True)))
    await _until_sent(mock_control)
    await _expire(hass, frozen_time)
    with pytest.raises(HomeAssistantError) as err:
        await task
    assert err.value.translation_key == "change_not_confirmed"
    assert err.value.translation_placeholders["seconds"] == "15"
    assert hub._waiters == {}


async def test_report_at_the_deadline_confirms(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A report that arrives together with the deadline confirms the change."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    task = asyncio.ensure_future(hub.async_apply("SN0001", PrivacyChange(active=True)))
    await _until_sent(mock_control)
    link.on_state("SN0001", replace(DEVICE_STATE, privacy=True))
    await _expire(hass, frozen_time)
    await task
    assert hub._waiters == {}


async def test_unrelated_report_does_not_confirm(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A report of another camera or of other fields does not end the wait."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    task = asyncio.ensure_future(hub.async_apply("SN0001", PrivacyChange(active=True)))
    await _until_sent(mock_control)
    link.on_state("SN0002", replace(DEVICE_STATE, privacy=True))
    link.on_state("SN0001", replace(DEVICE_STATE, battery=50))
    await asyncio.sleep(0)
    assert not task.done()
    link.on_state("SN0001", replace(DEVICE_STATE, privacy=True))
    await task


async def test_old_values_after_the_write_do_not_confirm(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The document that AWS IoT sends right after a desired write still has the old values."""
    hub, link = await _hub(hass, config_entry, shadow_links)

    def write(*_args: Any, **_kwargs: Any) -> WriteResult:
        link.on_state("SN0001", DEVICE_STATE)
        return WriteResult.ACCEPTED

    link.update_desired.side_effect = write
    task = asyncio.ensure_future(hub.async_apply("SN0001", MotionChange(level=2)))
    await _until_sent(mock_control)
    link.update_desired.assert_awaited_once()
    link.on_state("SN0001", DEVICE_STATE)
    await asyncio.sleep(0)
    assert not task.done()
    link.on_state("SN0001", replace(DEVICE_STATE, motion_level=2))
    await task


async def test_link_drop_keeps_waiting(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A dropped link does not fail the change. The report after the reconnect confirms it."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    task = asyncio.ensure_future(hub.async_apply("SN0001", PrivacyChange(active=True)))
    await _until_sent(mock_control)
    link.on_connection(False)
    link.on_connection(True)
    link.on_state("SN0001", replace(DEVICE_STATE, privacy=True))
    await task
    assert mock_control.send.await_count == 1


async def test_second_change_waits_in_line(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """The second fill light change plans from the state the first one confirmed."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    first = asyncio.ensure_future(
        hub.async_apply("SN0001", FillLightChange(auto=False))
    )
    await _until_sent(mock_control)
    second = asyncio.ensure_future(hub.async_apply("SN0001", FillLightChange(level=3)))
    await asyncio.sleep(0)
    assert mock_control.send.await_count == 1
    mock_control.send.side_effect = camera_reports(
        link, fill_light=3, fill_light_auto=False
    )
    link.on_state("SN0001", replace(DEVICE_STATE, fill_light_auto=False))
    await first
    await second
    assert mock_control.send.await_args_list[1].args[2] == {
        "level": 3,
        "brightness2": 120,
        "autoLight": False,
        "lowLight": True,
    }


async def test_deadline_used_up_in_line(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A change whose deadline passes in line sends nothing."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    first = asyncio.ensure_future(
        hub.async_apply("SN0001", FillLightChange(auto=False))
    )
    await _until_sent(mock_control)
    second = asyncio.ensure_future(hub.async_apply("SN0001", FillLightChange(level=3)))
    await asyncio.sleep(0)
    await _expire(hass, frozen_time)
    with pytest.raises(HomeAssistantError) as err:
        await first
    assert err.value.translation_key == "change_not_confirmed"
    with pytest.raises(HomeAssistantError) as err:
        await second
    assert err.value.translation_key == "change_timed_out"
    assert link.update_desired.await_count == 1
    assert mock_control.send.await_count == 1
    assert hub._waiters == {}


@pytest.mark.parametrize(
    ("slow", "key", "writes"),
    [
        ("get_device_settings", "change_timed_out", 0),
        ("update_desired", "change_partial", 1),
    ],
)
async def test_no_step_starts_without_time(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    frozen_time: FrozenDateTimeFactory,
    slow: str,
    key: str,
    writes: int,
) -> None:
    """A step that uses up the deadline stops the change before the next step."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    step = getattr(link if slow == "update_desired" else mock_client, slow)
    result = step.return_value

    def use_up_the_deadline(*_args: Any, **_kwargs: Any) -> Any:
        frozen_time.tick(CHANGE_TIMEOUT)
        return result

    step.side_effect = use_up_the_deadline
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", MotionChange(level=2))
    assert err.value.translation_key == key
    if key == "change_partial":
        assert err.value.translation_placeholders["error"] == "timeout"
    assert link.update_desired.await_count == writes
    mock_control.send.assert_not_awaited()


async def test_other_groups_do_not_wait(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Privacy does not wait behind a pending fill light change."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    fill = asyncio.ensure_future(hub.async_apply("SN0001", FillLightChange(auto=False)))
    await _until_sent(mock_control)
    privacy = asyncio.ensure_future(
        hub.async_apply("SN0001", PrivacyChange(active=True))
    )
    await _until_sent(mock_control, count=2)
    link.on_state("SN0001", replace(DEVICE_STATE, fill_light_auto=False, privacy=True))
    await fill
    await privacy


@pytest.mark.parametrize(
    ("state", "connected", "key"),
    [
        (replace(DEVICE_STATE, online=False), True, "camera_offline"),
        (DEVICE_STATE, False, "connection_not_ready"),
        (replace(DEVICE_STATE, fill_light_auto=None), True, "setting_unknown"),
    ],
)
async def test_apply_refused(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    state: DeviceState,
    connected: bool,
    key: str,
) -> None:
    """A change that cannot start fails at once and sends nothing."""
    hub, link = await _hub(hass, config_entry, shadow_links, state)
    link.status = replace(link.status, connected=connected)
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", FillLightChange(level=1))
    assert err.value.translation_key == key
    assert err.value.translation_placeholders["camera"] == "Bathroom"
    mock_control.send.assert_not_awaited()


async def test_apply_without_state(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A camera without a reported state, or an unknown one, cannot change."""
    hub, _link = await _hub(hass, config_entry, shadow_links)
    for sn in ("SN0002", "SN0099"):
        with pytest.raises(HomeAssistantError) as err:
            await hub.async_apply(sn, PrivacyChange(active=True))
        assert err.value.translation_key == "setting_unknown"
    mock_control.send.assert_not_awaited()


async def test_feature_off(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Old firmware without feature 6 cannot change the fill light."""
    mock_client.get_feature_rules.return_value = FeatureRules({"6": ("9.0.0",)})
    hub, _link = await _hub(hass, config_entry, shadow_links)
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", FillLightChange(level=1))
    assert err.value.translation_key == "setting_not_supported"


async def test_detail_read_fails(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A failed read of the camera detail sends nothing, and an auth error starts reauth."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    mock_client.get_device_settings.side_effect = SiiPetAuthError("expired")
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", MotionChange(level=2))
    assert err.value.translation_key == "request_failed"
    link.update_desired.assert_not_awaited()
    mock_control.send.assert_not_awaited()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_desired_rejected(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A rejected desired write sends no command."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    link.update_desired.side_effect = ShadowWriteError("rejected")
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", MotionChange(level=2))
    assert err.value.translation_key == "change_not_sent"
    mock_control.send.assert_not_awaited()
    assert hub._waiters == {}


async def test_command_fails_after_desired(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A failed command after a written desired is a partial change."""
    hub, _link = await _hub(hass, config_entry, shadow_links)
    mock_control.send.side_effect = LrtmTransportError("Could not reach")
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", MotionChange(level=2))
    assert err.value.translation_key == "change_partial"


async def test_command_fails_without_desired(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A failed privacy command changed nothing."""
    hub, _link = await _hub(hass, config_entry, shadow_links)
    mock_control.send.side_effect = LrtmServerError(103)
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", PrivacyChange(active=True))
    assert err.value.translation_key == "change_not_sent"


async def test_report_before_a_failed_command_confirms(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A camera that applies the desired write and reports it confirms the change."""
    hub, link = await _hub(hass, config_entry, shadow_links)

    def write(*_args: Any, **_kwargs: Any) -> WriteResult:
        link.on_state("SN0001", replace(DEVICE_STATE, motion_level=2))
        return WriteResult.ACCEPTED

    link.update_desired.side_effect = write
    mock_control.send.side_effect = LrtmTransportError("Could not reach")
    await hub.async_apply("SN0001", MotionChange(level=2))
    assert hub._waiters == {}


async def test_auth_error_starts_reauth(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """An auth error that recovery could not fix asks the user to sign in."""
    hub, _link = await _hub(hass, config_entry, shadow_links)
    mock_control.send.side_effect = SiiPetAuthError("ended")
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", PrivacyChange(active=True))
    assert err.value.translation_key == "request_failed"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_unwritable_camera_sends_only_the_command(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A camera whose shadow writes AWS IoT refused gets only the command."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    link.writable = False
    link.refused = True
    mock_control.send.side_effect = camera_reports(link, motion_level=2)
    await hub.async_apply("SN0001", MotionChange(level=2))
    link.update_desired.assert_not_awaited()
    mock_control.send.assert_awaited_once()


async def test_camera_that_starts_again_sends_nothing(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A connected link that cannot write yet, without a refusal, sends nothing."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    link.writable = False
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", MotionChange(level=2))
    assert err.value.translation_key == "connection_not_ready"
    link.update_desired.assert_not_awaited()
    mock_control.send.assert_not_awaited()
    assert hub._waiters == {}


async def test_unload_ends_the_wait(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Unloading the entry fails a waiting change at once."""
    hub, _link = await _hub(hass, config_entry, shadow_links)
    task = asyncio.ensure_future(hub.async_apply("SN0001", PrivacyChange(active=True)))
    await _until_sent(mock_control)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    with pytest.raises(HomeAssistantError) as err:
        await task
    assert err.value.translation_key == "change_not_confirmed"


async def test_unload_stops_the_line(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A change that waits in line at unload sends nothing."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    first = asyncio.ensure_future(hub.async_apply("SN0001", MotionChange(level=2)))
    await _until_sent(mock_control)
    second = asyncio.ensure_future(hub.async_apply("SN0001", MotionChange(level=2)))
    await asyncio.sleep(0)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    with pytest.raises(HomeAssistantError) as err:
        await first
    assert err.value.translation_key == "change_not_confirmed"
    with pytest.raises(HomeAssistantError) as err:
        await second
    assert err.value.translation_key == "connection_not_ready"
    assert link.update_desired.await_count == 1
    assert mock_control.send.await_count == 1


async def test_camera_removal_ends_the_wait(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A camera that leaves the camera list fails its waiting change at once."""
    hub, _link = await _hub(hass, config_entry, shadow_links)
    task = asyncio.ensure_future(hub.async_apply("SN0001", PrivacyChange(active=True)))
    await _until_sent(mock_control)
    _remove_camera(config_entry)
    with pytest.raises(HomeAssistantError) as err:
        await task
    assert err.value.translation_key == "change_not_confirmed"
    assert hub._waiters == {}


async def test_camera_leaves_during_the_reads(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A camera that leaves while the change reads its detail gets nothing."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    settings = mock_client.get_device_settings.return_value

    def leave(*_args: Any, **_kwargs: Any) -> Any:
        _remove_camera(config_entry)
        return settings

    mock_client.get_device_settings.side_effect = leave
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", MotionChange(level=2))
    assert err.value.translation_key == "setting_unknown"
    link.update_desired.assert_not_awaited()
    mock_control.send.assert_not_awaited()


@pytest.mark.parametrize("stop", ["unload", "camera_removal"])
async def test_abandoned_change_sends_no_command(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    stop: str,
) -> None:
    """A change that stops during the desired write sends no command."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    release = asyncio.Event()

    async def write(*_args: Any, **_kwargs: Any) -> WriteResult:
        await release.wait()
        return WriteResult.ACCEPTED

    link.update_desired.side_effect = write
    task = asyncio.ensure_future(hub.async_apply("SN0001", MotionChange(level=2)))
    await _until_awaited(link.update_desired)
    if stop == "unload":
        assert await hass.config_entries.async_unload(config_entry.entry_id)
    else:
        _remove_camera(config_entry)
    release.set()
    with pytest.raises(HomeAssistantError) as err:
        await task
    assert err.value.translation_key == "change_partial"
    assert err.value.translation_placeholders["error"] == "the change was stopped"
    mock_control.send.assert_not_awaited()
    assert hub._waiters == {}


async def test_unconfirmed_command_waits_for_the_report(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A command that went out without an answer is confirmed by the report."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    mock_control.send.side_effect = LrtmUnconfirmedError()
    task = asyncio.ensure_future(hub.async_apply("SN0001", PrivacyChange(active=True)))
    await _until_sent(mock_control)
    for _ in range(5):
        await asyncio.sleep(0)
    assert not task.done()
    link.on_state("SN0001", replace(DEVICE_STATE, privacy=True))
    await task
    assert hub._waiters == {}


async def test_unconfirmed_command_without_report(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A command without an answer and without a report is not confirmed."""
    hub, _link = await _hub(hass, config_entry, shadow_links)
    mock_control.send.side_effect = LrtmUnconfirmedError()
    task = asyncio.ensure_future(hub.async_apply("SN0001", PrivacyChange(active=True)))
    await _until_sent(mock_control)
    await _expire(hass, frozen_time)
    with pytest.raises(HomeAssistantError) as err:
        await task
    assert err.value.translation_key == "change_not_confirmed"
    assert hub._waiters == {}


async def test_no_read_without_time(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A change whose turn comes with no time left reads nothing."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    release = asyncio.Event()

    async def slow_command(*_args: Any, **_kwargs: Any) -> None:
        await release.wait()
        frozen_time.tick(CHANGE_TIMEOUT)
        # A new firmware, so the next change would read the detail again.
        link.on_state("SN0001", replace(DEVICE_STATE, motion_level=2, firmware="1.2.4"))

    mock_control.send.side_effect = slow_command
    first = asyncio.ensure_future(hub.async_apply("SN0001", MotionChange(level=2)))
    await _until_sent(mock_control)
    second = asyncio.ensure_future(hub.async_apply("SN0001", MotionChange(level=3)))
    await asyncio.sleep(0)
    release.set()
    await first
    with pytest.raises(HomeAssistantError) as err:
        await second
    assert err.value.translation_key == "change_timed_out"
    assert mock_client.get_device_settings.await_count == 1
    assert link.update_desired.await_count == 1
    assert mock_control.send.await_count == 1


async def test_slow_detail_read_runs_out_of_time(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A detail read that outlasts the deadline sends nothing."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    release = asyncio.Event()

    async def slow_read(*_args: Any, **_kwargs: Any) -> None:
        await release.wait()

    mock_client.get_device_settings.side_effect = slow_read
    task = asyncio.ensure_future(hub.async_apply("SN0001", MotionChange(level=2)))
    await _until_awaited(mock_client.get_device_settings)
    await _expire(hass, frozen_time)
    with pytest.raises(HomeAssistantError) as err:
        await task
    assert err.value.translation_key == "change_timed_out"
    link.update_desired.assert_not_awaited()
    mock_control.send.assert_not_awaited()
    assert hub._waiters == {}


async def test_no_command_without_time(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A privacy change whose turn comes with no time left sends nothing."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    release = asyncio.Event()

    async def slow_command(*_args: Any, **_kwargs: Any) -> None:
        await release.wait()
        frozen_time.tick(CHANGE_TIMEOUT)
        link.on_state("SN0001", replace(DEVICE_STATE, privacy=True))

    mock_control.send.side_effect = slow_command
    first = asyncio.ensure_future(hub.async_apply("SN0001", PrivacyChange(active=True)))
    await _until_sent(mock_control)
    second = asyncio.ensure_future(
        hub.async_apply("SN0001", PrivacyChange(active=False))
    )
    await asyncio.sleep(0)
    release.set()
    await first
    with pytest.raises(HomeAssistantError) as err:
        await second
    assert err.value.translation_key == "change_timed_out"
    assert mock_control.send.await_count == 1
    assert hub._waiters == {}


async def test_unconfirmed_write_still_sends_the_command(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A desired write without an answer counts as written."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    link.update_desired.return_value = WriteResult.UNCONFIRMED
    mock_control.send.side_effect = camera_reports(link, motion_level=2)
    await hub.async_apply("SN0001", MotionChange(level=2))
    mock_control.send.assert_awaited_once()
    mock_control.send.side_effect = LrtmTransportError("Could not reach")
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", MotionChange(level=3))
    assert err.value.translation_key == "change_partial"


async def test_desired_not_ready(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A desired write that cannot leave sends no command."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    link.update_desired.side_effect = ShadowWriteError("not_ready")
    with pytest.raises(HomeAssistantError) as err:
        await hub.async_apply("SN0001", MotionChange(level=2))
    assert err.value.translation_key == "connection_not_ready"
    mock_control.send.assert_not_awaited()
    assert hub._waiters == {}


async def test_cancel_while_waiting_for_the_report(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A canceled change frees its group and leaves no waiter."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    task = asyncio.ensure_future(hub.async_apply("SN0001", PrivacyChange(active=True)))
    await _until_sent(mock_control)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()
    assert hub._waiters == {}
    mock_control.send.side_effect = camera_reports(link, privacy=True)
    await hub.async_apply("SN0001", PrivacyChange(active=True))
    assert mock_control.send.await_count == 2


async def test_cancel_while_waiting_in_line(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """A change canceled in line sends nothing and keeps the line going."""
    hub, link = await _hub(hass, config_entry, shadow_links)
    first = asyncio.ensure_future(
        hub.async_apply("SN0001", FillLightChange(auto=False))
    )
    await _until_sent(mock_control)
    second = asyncio.ensure_future(hub.async_apply("SN0001", FillLightChange(level=3)))
    await asyncio.sleep(0)
    second.cancel()
    with suppress(asyncio.CancelledError):
        await second
    assert second.cancelled()
    link.on_state("SN0001", replace(DEVICE_STATE, fill_light_auto=False))
    await first
    assert mock_control.send.await_count == 1
    mock_control.send.side_effect = camera_reports(
        link, fill_light=3, fill_light_auto=False
    )
    await hub.async_apply("SN0001", FillLightChange(level=3))
    assert mock_control.send.await_count == 2
    assert hub._waiters == {}


@pytest.mark.parametrize("stop", ["unload", "camera_removal"])
@pytest.mark.parametrize(
    ("change", "key"),
    [
        (PrivacyChange(active=True), "connection_not_ready"),
        (MotionChange(level=2), "change_partial"),
    ],
)
async def test_abandoned_change_publishes_nothing(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_control: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    stop: str,
    change: PrivacyChange | MotionChange,
    key: str,
) -> None:
    """A change that stops while the command connects publishes nothing."""
    hub, _link = await _hub(hass, config_entry, shadow_links)
    release = asyncio.Event()
    published: list[str] = []

    async def send(
        _sn: str,
        command: str,
        _payload: Any,
        *,
        limit: float,
        still_wanted: Callable[[], bool],
    ) -> None:
        # As the realtime client does: connect, then check right before the publish.
        await release.wait()
        if not still_wanted():
            raise LrtmTransportError("The command was stopped before it was sent")
        published.append(command)

    mock_control.send.side_effect = send
    task = asyncio.ensure_future(hub.async_apply("SN0001", change))
    await _until_sent(mock_control)
    if stop == "unload":
        assert await hass.config_entries.async_unload(config_entry.entry_id)
    else:
        _remove_camera(config_entry)
    release.set()
    with pytest.raises(HomeAssistantError) as err:
        await task
    assert err.value.translation_key == key
    if key == "change_partial":
        assert err.value.translation_placeholders["error"] == "the change was stopped"
    assert published == []
    assert hub._waiters == {}
