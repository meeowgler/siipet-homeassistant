"""Device state of the cameras, pushed by the shadow link, and changes to their settings."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CameraShadows,
    DeviceSettings,
    DeviceState,
    FeatureRules,
    LrtmClient,
    LrtmUnconfirmedError,
    SettingUnavailableError,
    ShadowWriteError,
    SiiPetAuthError,
    SiiPetClient,
    SiiPetError,
)
from .api.settings import (
    FEATURE_PIR_AND_FILL_LIGHT,
    PlannedChange,
    SettingChange,
    SettingGroup,
    group_of,
    plan_change,
    reports,
)
from .api.shadow_link import LinkStatus, ShadowLink, WriteResult
from .const import CHANGE_TIMEOUT, DEVICE_STATE_GRACE, DOMAIN, SHADOW_WRITE_TIMEOUT

if TYPE_CHECKING:
    from .coordinator import SiiPetConfigEntry, SiiPetCoordinator

_LOGGER = logging.getLogger(__name__)


class _Abandoned(Exception):
    """The change stopped waiting because the entry unloaded or the camera left."""


@dataclass(eq=False, slots=True)
class _Waiter:
    """One change that waits for its expected fields in the reported state."""

    expected: Mapping[str, Any]
    future: asyncio.Future[None]

    def confirmed(self) -> bool:
        """True when the camera reported every expected field."""
        future = self.future
        return future.done() and not future.cancelled() and future.exception() is None

    def abandoned(self) -> bool:
        """True when the entry unloaded or the camera left."""
        future = self.future
        return (
            future.done()
            and not future.cancelled()
            and isinstance(future.exception(), _Abandoned)
        )


class SiiPetDeviceCoordinator(DataUpdateCoordinator[dict[str, DeviceState]]):
    """Keep the device state of each camera, by serial number, and change its settings."""

    config_entry: SiiPetConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SiiPetConfigEntry,
        coordinator: SiiPetCoordinator,
        client: SiiPetClient,
        lrtm: LrtmClient,
    ) -> None:
        """Create the coordinator and its link. `async_start` starts the link."""
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} device state"
        )
        self.data = {}
        self._coordinator = coordinator
        self._client = client
        self._lrtm = lrtm
        self._link = ShadowLink(
            async_get_clientsession(hass),
            client.get_iot_credentials,
            self._async_on_state,
            self._async_on_connection,
            self._label,
        )
        self._shadows: dict[str, CameraShadows] = {}
        self._firmware: dict[str, str] = {}
        self._cancel_grace: CALLBACK_TYPE | None = None
        # Shutdown cancels the timer, like the other Home Assistant timers.
        self._grace_job = HassJob(
            self._async_grace_over,
            f"{DOMAIN} device state grace",
            cancel_on_shutdown=True,
        )
        self._locks: dict[tuple[str, SettingGroup], asyncio.Lock] = {}
        self._waiters: dict[str, list[_Waiter]] = {}
        self._device_settings: dict[str, tuple[str, DeviceSettings]] = {}
        self._features: FeatureRules | None = None
        self._stopped = False

    @property
    def link_status(self) -> LinkStatus:
        """The state of the link, for diagnostics."""
        return self._link.status

    @callback
    def async_start(self) -> None:
        """Start the link in the background. Setup does not wait for AWS IoT."""
        entry = self.config_entry
        self._async_cameras_changed()
        # The link starts without a connection, so the grace runs until it connects.
        self._async_on_connection(False)
        entry.async_on_unload(
            self._coordinator.async_add_listener(self._async_cameras_changed)
        )
        entry.async_on_unload(self._async_stop)
        entry.async_create_background_task(
            self.hass, self._link.run(), f"{DOMAIN} shadow link"
        )

    async def _async_stop(self) -> None:
        # A change in line must not start after this, and a waiting one ends
        # now, because no report reaches it any more.
        self._stopped = True
        self._abandon(list(self._waiters))
        self._async_cancel_grace()
        await self._link.stop()

    async def async_apply(self, sn: str, change: SettingChange) -> None:
        """Change one setting of a camera, and return when the camera reports it.

        Raise HomeAssistantError with a translated message when the change
        cannot start, fails, or is not reported within CHANGE_TIMEOUT.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + CHANGE_TIMEOUT.total_seconds()

        def remaining() -> float:
            return max(0.0, deadline - loop.time())

        self._ready_state(sn)
        group = group_of(change)
        lock = self._locks.setdefault((sn, group), asyncio.Lock())
        try:
            async with asyncio.timeout(remaining()):
                await lock.acquire()
        except TimeoutError as err:
            raise self._error("change_timed_out", sn) from err
        try:
            await self._async_apply_locked(sn, change, group, remaining)
        finally:
            lock.release()

    async def _async_apply_locked(
        self,
        sn: str,
        change: SettingChange,
        group: SettingGroup,
        remaining: Callable[[], float],
    ) -> None:
        # The state can change while the change waits in line.
        state = self._ready_state(sn)
        settings = DeviceSettings()
        if group is not SettingGroup.PRIVACY:
            if remaining() <= 0:
                raise self._error("change_timed_out", sn)
            try:
                async with asyncio.timeout(remaining()):
                    if not await self._async_feature_enabled(state):
                        raise self._error("setting_not_supported", sn)
                    settings = await self._async_device_settings(sn, state)
            except TimeoutError as err:
                raise self._error("change_timed_out", sn) from err
            except SiiPetError as err:
                raise self._request_failed(sn, err) from err
            # The camera can leave, or the entry unload, during the reads.
            # A waiter registered after this check is abandoned in both cases.
            state = self._ready_state(sn)
        try:
            planned = plan_change(change, state, settings)
        except SettingUnavailableError as err:
            raise self._error("setting_unknown", sn) from err
        if planned is None:
            return
        waiter = _Waiter(planned.expected, asyncio.get_running_loop().create_future())
        self._waiters.setdefault(sn, []).append(waiter)
        try:
            try:
                await self._async_send(sn, planned, waiter, remaining)
            except HomeAssistantError:
                # A camera can apply the desired write and report it before
                # the command fails. It then has the setting, so the change
                # succeeded.
                if waiter.confirmed():
                    return
                raise
            try:
                async with asyncio.timeout(remaining()):
                    await waiter.future
            except (TimeoutError, _Abandoned) as err:
                # The report and the deadline can arrive in the same loop
                # iteration. The report wins.
                if waiter.confirmed():
                    return
                raise self._error("change_not_confirmed", sn) from err
        finally:
            self._remove_waiter(sn, waiter)

    async def _async_send(
        self,
        sn: str,
        planned: PlannedChange,
        waiter: _Waiter,
        remaining: Callable[[], float],
    ) -> None:
        """Write desired when the link can, then send the command."""
        desired_written = False
        if planned.desired_key is not None and self._may_write_shadow(sn):
            left = remaining()
            if left <= 0:
                raise self._error("change_timed_out", sn)
            try:
                result = await self._link.update_desired(
                    sn,
                    planned.desired_key,
                    planned.payload,
                    limit=min(left, SHADOW_WRITE_TIMEOUT.total_seconds()),
                )
            except ShadowWriteError as err:
                if err.reason == "not_ready":
                    raise self._error("connection_not_ready", sn) from err
                raise self._error("change_not_sent", sn, error=str(err)) from err
            desired_written = True
            if result is WriteResult.UNCONFIRMED:
                _LOGGER.debug(
                    "AWS IoT did not confirm the desired write of %s", self._label(sn)
                )
        # The entry can unload, or the camera leave, during the desired write.
        # Nothing then waits for the report, so the command stays unsent.
        if self._abandoned(sn, waiter):
            raise self._stopped_error(sn, desired_written)
        left = remaining()
        if left <= 0:
            if desired_written:
                raise self._error("change_partial", sn, error="timeout")
            raise self._error("change_timed_out", sn)
        try:
            await self._lrtm.send(
                sn,
                planned.command,
                planned.payload,
                limit=left,
                # The same stop can come while the command connects.
                still_wanted=lambda: not self._abandoned(sn, waiter),
            )
        except LrtmUnconfirmedError:
            # The command went out, so the camera may still apply it. Its
            # report decides.
            _LOGGER.debug(
                "The realtime server did not confirm the command for %s",
                self._label(sn),
            )
        except SiiPetError as err:
            if self._abandoned(sn, waiter):
                raise self._stopped_error(sn, desired_written) from err
            if isinstance(err, SiiPetAuthError):
                self.config_entry.async_start_reauth(self.hass)
                key = "change_partial" if desired_written else "request_failed"
            else:
                key = "change_partial" if desired_written else "change_not_sent"
            raise self._error(key, sn, error=str(err)) from err

    def _abandoned(self, sn: str, waiter: _Waiter) -> bool:
        """True when the entry unloaded or the camera left after the change started."""
        return self._stopped or sn not in self._shadows or waiter.abandoned()

    def _stopped_error(self, sn: str, desired_written: bool) -> HomeAssistantError:
        if desired_written:
            return self._error("change_partial", sn, error="the change was stopped")
        return self._error("connection_not_ready", sn)

    def _may_write_shadow(self, sn: str) -> bool:
        """Return True to write the shadow, or False to send the command alone.

        Raise while the link is not ready for the camera yet, as while the
        cameras start again after a reconnect.
        """
        if self._link.can_write(sn):
            return True
        if self._link.writes_refused(sn):
            # AWS IoT refused the write replies of this camera, or the link
            # skipped them because the writes of the camera were paused. The
            # command alone still changes the setting.
            _LOGGER.debug("The shadow of %s cannot be written", self._label(sn))
            return False
        # The command alone would leave the old value in the desired state.
        raise self._error("connection_not_ready", sn)

    def _ready_state(self, sn: str) -> DeviceState:
        """Return the state of a camera that can take a change now, or raise."""
        state = self.data.get(sn)
        if sn not in self._shadows or state is None:
            raise self._error("setting_unknown", sn)
        if state.online is False:
            raise self._error("camera_offline", sn)
        if self._stopped or not self._link.status.connected:
            raise self._error("connection_not_ready", sn)
        return state

    async def _async_feature_enabled(self, state: DeviceState) -> bool:
        if self._features is None:
            self._features = await self._client.get_feature_rules()
        return self._features.enabled(FEATURE_PIR_AND_FILL_LIGHT, state.firmware)

    async def _async_device_settings(
        self, sn: str, state: DeviceState
    ) -> DeviceSettings:
        firmware = state.firmware or ""
        cached = self._device_settings.get(sn)
        if cached is not None and cached[0] == firmware:
            return cached[1]
        settings = await self._client.get_device_settings(sn, firmware)
        self._device_settings[sn] = (firmware, settings)
        return settings

    @callback
    def _resolve_waiters(self, sn: str, state: DeviceState) -> None:
        for waiter in self._waiters.get(sn, ()):
            if not waiter.future.done() and reports(state, waiter.expected):
                waiter.future.set_result(None)

    @callback
    def _abandon(self, sns: Iterable[str]) -> None:
        for sn in sns:
            for waiter in self._waiters.get(sn, ()):
                if not waiter.future.done():
                    waiter.future.set_exception(_Abandoned())

    def _remove_waiter(self, sn: str, waiter: _Waiter) -> None:
        waiters = self._waiters.get(sn, [])
        if waiter in waiters:
            waiters.remove(waiter)
        if not waiters:
            self._waiters.pop(sn, None)
        if waiter.future.done() and not waiter.future.cancelled():
            # Reading the error keeps asyncio from logging it as never retrieved.
            waiter.future.exception()

    def _request_failed(self, sn: str, err: SiiPetError) -> HomeAssistantError:
        if isinstance(err, SiiPetAuthError):
            self.config_entry.async_start_reauth(self.hass)
        return self._error("request_failed", sn, error=str(err))

    def _error(self, key: str, sn: str, **placeholders: str) -> HomeAssistantError:
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={
                "camera": self._label(sn),
                "seconds": str(int(CHANGE_TIMEOUT.total_seconds())),
                **placeholders,
            },
        )

    @callback
    def _async_cameras_changed(self) -> None:
        cameras = self._coordinator.data.cameras
        shadows = {
            sn: camera.shadows
            for sn, camera in cameras.items()
            if camera.shadows is not None
        }
        if shadows == self._shadows:
            return
        # A camera that left the list, or whose shadow names changed, keeps no
        # old state. Otherwise its entities would stay available with values
        # the link no longer reports on.
        stale = {
            sn for sn, previous in self._shadows.items() if shadows.get(sn) != previous
        }
        self._abandon(stale)
        self._shadows = shadows
        self._firmware = {
            sn: firmware for sn, firmware in self._firmware.items() if sn in shadows
        }
        self._device_settings = {
            sn: value for sn, value in self._device_settings.items() if sn in shadows
        }
        self._link.set_cameras(shadows)
        if any(sn in self.data for sn in stale):
            self.data = {
                sn: state for sn, state in self.data.items() if sn not in stale
            }
            self.async_update_listeners()

    def _label(self, sn: str) -> str:
        camera = self._coordinator.data.cameras.get(sn)
        return camera.name if camera else "a removed camera"

    @callback
    def _async_on_state(self, sn: str, state: DeviceState | None) -> None:
        if state is None:
            # async_set_updated_data would also mark a success and hide an outage.
            if sn in self.data:
                self.data = {
                    key: value for key, value in self.data.items() if key != sn
                }
                self.async_update_listeners()
            return
        if sn not in self._shadows:
            return
        self._async_update_firmware(sn, state.firmware)
        self.async_set_updated_data({**self.data, sn: state})
        self._resolve_waiters(sn, state)

    @callback
    def _async_update_firmware(self, sn: str, firmware: str | None) -> None:
        if firmware is None or self._firmware.get(sn) == firmware:
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier(
            (DOMAIN, sn), self.config_entry.entry_id
        )
        if device is None:
            return
        self._firmware[sn] = firmware
        if device.sw_version != firmware:
            registry.async_update_device(device.id, sw_version=firmware)

    @callback
    def _async_on_connection(self, connected: bool) -> None:
        if connected:
            self._async_cancel_grace()
        elif self._cancel_grace is None:
            self._cancel_grace = async_call_later(
                self.hass, DEVICE_STATE_GRACE, self._grace_job
            )

    @callback
    def _async_grace_over(self, _now: datetime) -> None:
        self._cancel_grace = None
        self.async_set_update_error(
            UpdateFailed("No connection to the SiiPet device state for 15 minutes")
        )

    @callback
    def _async_cancel_grace(self) -> None:
        if self._cancel_grace is not None:
            self._cancel_grace()
            self._cancel_grace = None
