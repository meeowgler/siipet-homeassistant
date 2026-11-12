"""Tests for the shadow link against a fake AWS IoT broker."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
import pytest

from custom_components.siipet.api import (
    CameraShadows,
    DeviceState,
    IotCredentials,
    ShadowWriteError,
    SiiPetAuthError,
)
from custom_components.siipet.api.mqtt import MqttError, MqttSession
from custom_components.siipet.api.shadow_link import (
    LinkTimings,
    ShadowLink,
    WriteResult,
    shadow_topic,
)

from ..common import load_data, load_fixture
from .fake_broker import FakeBroker, run_broker

pytestmark = pytest.mark.usefixtures("socket_enabled")

SHADOWS = CameraShadows(config="fake_configInfo", system="fake_systemInfo")
CAMERAS = {"SN0001": SHADOWS, "SN0002": SHADOWS}
NAMES = {"SN0001": "Bathroom", "SN0002": "Hallway", "SN0003": "Kitchen"}
FAST = LinkTimings(
    reply=0.5,
    keepalive=1,
    ping_timeout=0.5,
    read_interval=0.3,
    denied_retry=timedelta(minutes=5),
    backoff=(0.05, 0.1),
)
PRIVATE = (
    "SN0001",
    "SN0002",
    "prod_",
    "identity-0001",
    "AKIDEXAMPLE",
    "X-Amz",
    "fake-token",
    "fake-signature",
)
SIGNED_QUERY = "X-Amz-Signature=fake-signature&X-Amz-Security-Token=fake-token"


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Keep the real clock. The link waits on asyncio timers."""


def _credentials(hours: float = 10) -> IotCredentials:
    return replace(
        IotCredentials.from_api(load_data("aws_auth.json")),
        expires=datetime.now(UTC) + timedelta(hours=hours),
    )


def _broker(**kwargs: Any) -> FakeBroker:
    broker = FakeBroker(**kwargs)
    broker.documents = {
        "SN0001/fake_configInfo": load_fixture("shadow_config_accepted.json"),
        "SN0001/fake_systemInfo": load_fixture("shadow_system_accepted.json"),
        "SN0002/fake_configInfo": load_fixture("shadow_config_accepted.json"),
    }
    return broker


@dataclass
class Recorder:
    """Collects the callbacks of the link."""

    states: dict[str, DeviceState] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    connection: list[bool] = field(default_factory=list)
    hook: Callable[[str], None] | None = None
    fail_first_connect: bool = False

    def on_state(self, sn: str, state: DeviceState | None) -> None:
        if state is None:
            self.states.pop(sn, None)
            self.dropped.append(sn)
            return
        self.states[sn] = state
        if self.hook is not None:
            self.hook(sn)

    def on_connection(self, connected: bool) -> None:
        self.connection.append(connected)
        if connected and self.fail_first_connect:
            self.fail_first_connect = False
            raise RuntimeError("callback failed")


@dataclass
class Clock:
    """The real clock, moved forward by `offset`.

    A test ends a wait of the link, such as a write pause or the life of the
    credentials, by moving the clock instead of sleeping.
    """

    offset: timedelta = timedelta()

    def __call__(self) -> datetime:
        return datetime.now(UTC) + self.offset


@dataclass
class Running:
    link: ShadowLink
    recorder: Recorder
    fetch: AsyncMock
    broker: FakeBroker
    task: asyncio.Task[None]
    clock: Clock


@asynccontextmanager
async def _running(
    broker: FakeBroker,
    *,
    cameras: dict[str, CameraShadows] | None = None,
    fetch: AsyncMock | None = None,
    timings: LinkTimings = FAST,
) -> AsyncIterator[Running]:
    recorder = Recorder()
    fetch = fetch or AsyncMock(return_value=_credentials())
    clock = Clock()
    async with run_broker(broker) as url, aiohttp.ClientSession() as websession:
        link = ShadowLink(
            websession,
            fetch,
            recorder.on_state,
            recorder.on_connection,
            NAMES.__getitem__,
            timings=timings,
            clock=clock,
            url=lambda _credentials, _now: f"{url}?{SIGNED_QUERY}",
        )
        link.set_cameras(CAMERAS if cameras is None else cameras)
        task = asyncio.create_task(link.run())
        try:
            yield Running(link, recorder, fetch, broker, task, clock)
        finally:
            await link.stop()


async def _until(check: Callable[[], bool], limit: float = 4.0) -> None:
    """Poll `check` every 10 ms until it is true, for up to `limit` seconds."""
    for _ in range(int(limit / 0.01)):
        try:
            if check():
                return
        except Exception:
            pass
        await asyncio.sleep(0.01)
    raise AssertionError("The condition did not become true in time")


async def test_start_reads_both_shadows() -> None:
    """The start subscribes to each camera, then reads both of its shadows."""
    async with _running(_broker()) as running:
        await _until(lambda: len(running.recorder.states) == 2)
        await _until(lambda: running.recorder.connection == [True])
        first = running.recorder.states["SN0001"]
        assert first.battery == 72
        assert first.online is True
        assert first.firmware == "1.2.3"
        second = running.recorder.states["SN0002"]
        assert second.battery == 72
        assert second.online is None
        status = running.link.status
        assert status.connected
        assert status.cameras_with_state == 2
        assert status.denied_cameras == 0
    [connection, *_rest] = running.broker.connections
    prefix, suffix = connection.client_id.rsplit(":", 1)
    assert prefix == "us-east-1:identity-0001"
    assert len(suffix) == 32
    assert connection.keepalive == 1
    assert shadow_topic("SN0002", "fake_systemInfo", "update/documents") in (
        connection.subscriptions
    )
    assert running.broker.gets[:4] == [
        shadow_topic("SN0001", "fake_configInfo", "get"),
        shadow_topic("SN0001", "fake_systemInfo", "get"),
        shadow_topic("SN0002", "fake_configInfo", "get"),
        shadow_topic("SN0002", "fake_systemInfo", "get"),
    ]


async def test_push_update() -> None:
    """An update document changes the state, and keeps the other shadow."""
    async with _running(_broker()) as running:
        await _until(lambda: "SN0001" in running.recorder.states)
        await running.broker.push(
            shadow_topic("SN0001", "fake_configInfo", "update/documents"),
            load_fixture("shadow_config_update.json"),
        )
        await _until(lambda: running.recorder.states["SN0001"].battery == 81)
        state = running.recorder.states["SN0001"]
        assert state.charging is True
        assert state.online is True


async def test_older_version_is_ignored() -> None:
    """A document with a lower version than the last one changes nothing."""
    broker = _broker()
    async with _running(broker) as running:
        await _until(lambda: "SN0001" in running.recorder.states)
        old = load_fixture("shadow_config_update.json")
        old["current"]["version"] = 5
        await broker.push(
            shadow_topic("SN0001", "fake_configInfo", "update/documents"), old
        )
        await asyncio.sleep(0.1)
        assert running.recorder.states["SN0001"].battery == 72


async def test_periodic_read() -> None:
    """The link reads every shadow again after the read interval."""
    async with _running(_broker()) as running:
        await _until(lambda: len(running.broker.gets) >= 8)
        assert len(running.broker.connections) == 1


async def test_ping_timeout_reconnects() -> None:
    """A missing PINGRESP ends the connection, and the link connects again."""
    async with _running(_broker(answer_ping=False)) as running:
        await _until(lambda: running.recorder.connection[:3] == [True, False, True])
        assert len(running.broker.connections) >= 2


async def test_subscribe_denied(caplog: pytest.LogCaptureFixture) -> None:
    """A failed SUBACK denies the camera and keeps the connection."""
    caplog.set_level(logging.DEBUG, logger="custom_components.siipet")
    async with _running(_broker(deny_subscribe={"SN0002"})) as running:
        await _until(lambda: running.link.status.denied_cameras == 1)
        await _until(lambda: "SN0001" in running.recorder.states)
        assert "SN0002" not in running.recorder.states
        assert len(running.broker.connections) == 1
    assert "refused the device state of Hallway" in caplog.text
    for private in PRIVATE:
        assert private not in caplog.text


async def test_repeated_close_on_get_denies_camera() -> None:
    """Two closes in a row while a camera starts deny it. The link connects without it."""
    broker = _broker(close_on_get={"SN0002"})
    async with _running(broker) as running:
        await _until(lambda: running.recorder.connection == [True])
        assert running.link.status.denied_cameras == 1
        assert len(broker.connections) == 3
        third = broker.connections[2]
        assert not any("SN0002" in topic for topic in third.subscriptions)
        assert "SN0001" in running.recorder.states


async def test_one_close_on_get_does_not_deny() -> None:
    """One close while a camera starts only reconnects. The camera then starts."""
    broker = _broker(close_on_get_budget={"SN0002": 1})
    async with _running(broker) as running:
        await _until(lambda: len(running.recorder.states) == 2)
        await _until(lambda: running.recorder.connection == [True])
        assert running.link.status.denied_cameras == 0
        assert len(broker.connections) == 2


async def test_silent_get_does_not_deny() -> None:
    """A read with no reply ends the start after the reply wait, with no denial."""
    broker = _broker(silent_get={"SN0002"})
    async with _running(broker) as running:
        await _until(lambda: running.recorder.connection == [True])
        assert running.link.status.denied_cameras == 0
        assert "SN0001" in running.recorder.states
        assert len(broker.connections) == 1


async def test_repeated_subscribe_timeout_denies_camera() -> None:
    """Two subscribe timeouts in a row deny the camera. The other camera keeps working."""
    broker = _broker(silent_subscribe={"SN0002"})
    async with _running(broker) as running:
        await _until(lambda: running.recorder.connection == [True])
        assert running.link.status.denied_cameras == 1
        assert running.link.status.connected
        assert "SN0001" in running.recorder.states
        assert len(broker.connections) == 3


async def test_denied_camera_drops_its_state() -> None:
    """A camera that is denied after a read loses its state."""
    broker = _broker()
    async with _running(broker) as running:
        await _until(lambda: len(running.recorder.states) == 2)
        broker.deny_subscribe = {"SN0002"}
        await broker.close_all()
        await _until(lambda: running.link.status.denied_cameras == 1)
        assert running.recorder.dropped == ["SN0002"]
        assert "SN0002" not in running.recorder.states
        assert running.link.status.cameras_with_state == 1


async def test_denied_camera_is_tried_again() -> None:
    """After the retry time, a denied camera starts on the open connection."""
    broker = _broker(deny_subscribe={"SN0002"})
    # A long read interval keeps a periodic re-read from masking a retry that
    # ignores its own replies, so the state must come from the retry itself.
    timings = replace(FAST, denied_retry=timedelta(seconds=0.2), read_interval=30.0)
    async with _running(broker, timings=timings) as running:
        await _until(lambda: running.link.status.denied_cameras == 1)
        broker.deny_subscribe.clear()
        await _until(lambda: "SN0002" in running.recorder.states)
        await _until(lambda: running.link.status.denied_cameras == 0)
        assert len(broker.connections) == 1


async def test_backoff_and_recovery(caplog: pytest.LogCaptureFixture) -> None:
    """Failures back off and log one warning with no URL, then one info line."""
    caplog.set_level(logging.DEBUG, logger="custom_components.siipet")
    broker = _broker(handshake_status=500)
    async with _running(broker) as running:
        await _until(lambda: "failed again" in caplog.text)
        broker.handshake_status = None
        await _until(lambda: running.recorder.connection == [True])
        assert running.fetch.await_count == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "next try in 0.05 s" in warnings[0].getMessage()
    assert "HTTP 500" in warnings[0].getMessage()
    assert "works again" in caplog.text
    for private in PRIVATE:
        assert private not in caplog.text


async def test_auth_error_backs_off() -> None:
    """An auth error from the credentials call is a normal failure."""
    fetch = AsyncMock(side_effect=[SiiPetAuthError("-2: ended"), _credentials()])
    async with _running(_broker(), fetch=fetch) as running:
        await _until(lambda: running.recorder.connection == [True])
        assert fetch.await_count == 2


async def test_refused_connack_fetches_new_credentials() -> None:
    """A refused CONNACK drops the credentials, so the next try fetches new ones."""
    broker = _broker(connack_code=5)
    async with _running(broker) as running:
        # The client id is set when the broker reads CONNECT, after it picks the code.
        await _until(lambda: broker.connections[0].client_id is not None)
        broker.connack_code = 0
        await _until(lambda: running.link.status.connected)
        assert running.fetch.await_count >= 2


@pytest.mark.parametrize("status", [401, 403])
async def test_refused_handshake_fetches_new_credentials(status: int) -> None:
    """A handshake refused with 401 or 403 drops the credentials."""
    broker = _broker(handshake_status=status)
    async with _running(broker) as running:
        await _until(lambda: running.fetch.await_count >= 2)
        broker.handshake_status = None
        await _until(lambda: running.link.status.connected)


async def test_planned_reconnect() -> None:
    """Before the credentials expire, the link reconnects with new ones."""
    soon = replace(
        _credentials(),
        expires=datetime.now(UTC) + timedelta(minutes=10, seconds=0.5),
    )
    fetch = AsyncMock(side_effect=[soon, _credentials()])
    broker = _broker()
    async with _running(broker, fetch=fetch) as running:
        await _until(lambda: len(broker.connections) == 2)
        await _until(lambda: fetch.await_count == 2)
        assert broker.connections[0].disconnected
        assert running.recorder.connection == [True]


async def test_set_cameras() -> None:
    """A new camera starts on the open connection. A removed one is forgotten."""
    broker = _broker()
    async with _running(broker, cameras={"SN0001": SHADOWS}) as running:
        await _until(lambda: "SN0001" in running.recorder.states)
        running.link.set_cameras(CAMERAS)
        await _until(lambda: "SN0002" in running.recorder.states)
        running.link.set_cameras({"SN0002": SHADOWS})
        assert running.link.status.cameras_with_state == 1
        running.recorder.states.clear()
        await broker.push(
            shadow_topic("SN0001", "fake_configInfo", "update/documents"),
            load_fixture("shadow_config_update.json"),
        )
        await asyncio.sleep(0.1)
        assert "SN0001" not in running.recorder.states
        assert len(broker.connections) == 1


async def test_camera_removed_while_another_starts() -> None:
    """A camera removed while an earlier camera starts is skipped."""
    async with _running(_broker()) as running:

        def drop_second(sn: str) -> None:
            if sn == "SN0001":
                running.link.set_cameras({"SN0001": SHADOWS})

        running.recorder.hook = drop_second
        await _until(lambda: running.recorder.connection == [True])
        assert not running.task.done()
        assert "SN0002" not in running.recorder.states


async def test_shadow_names_change_while_a_camera_starts() -> None:
    """New shadow names during a start lead to a new start with those names."""
    broker = _broker()
    renamed = CameraShadows(config="next_configInfo", system="next_systemInfo")
    broker.documents["SN0001/next_configInfo"] = load_fixture(
        "shadow_config_accepted.json"
    )
    async with _running(broker, cameras={"SN0001": SHADOWS}) as running:
        renames: list[str] = []

        def rename(sn: str) -> None:
            if not renames:
                renames.append(sn)
                running.link.set_cameras({"SN0001": renamed})

        running.recorder.hook = rename
        topic = shadow_topic("SN0001", "next_configInfo", "get/accepted")
        await _until(lambda: topic in running.broker.connections[0].subscriptions)
        assert len(running.broker.connections) == 1


async def test_unexpected_error_does_not_end_the_link() -> None:
    """An unexpected error backs off, and the link connects again."""
    async with _running(_broker()) as running:
        running.recorder.fail_first_connect = True
        await _until(lambda: running.recorder.connection.count(True) == 2)
        assert not running.task.done()
        assert len(running.broker.connections) == 2


async def test_state_callback_error_keeps_the_connection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An error in the state callback logs its type only and keeps the connection."""
    caplog.set_level(logging.DEBUG, logger="custom_components.siipet")
    async with _running(_broker()) as running:
        failed: list[str] = []

        def fail_once(sn: str) -> None:
            if not failed:
                failed.append(sn)
                raise RuntimeError(f"SN0001 fake-token {SIGNED_QUERY}")

        running.recorder.hook = fail_once
        await _until(lambda: len(running.recorder.states) == 2)
        await _until(lambda: running.recorder.connection == [True])
        assert len(running.broker.connections) == 1
        assert not running.task.done()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "RuntimeError" in warnings[0].getMessage()
    assert "Bathroom" in warnings[0].getMessage()
    for private in PRIVATE:
        assert private not in caplog.text


async def test_rejected_read_logs_code_only(caplog: pytest.LogCaptureFixture) -> None:
    """A rejected read logs its code once, without the shadow name."""
    caplog.set_level(logging.DEBUG, logger="custom_components.siipet")
    async with _running(_broker()) as running:
        await _until(lambda: len(running.broker.gets) >= 8)
    rejected = [r for r in caplog.records if "rejected" in r.getMessage()]
    assert len(rejected) == 1
    assert "code 404" in rejected[0].getMessage()
    assert "Hallway" in rejected[0].getMessage()
    for private in PRIVATE:
        assert private not in caplog.text


async def test_partly_refused_camera_ignores_updates() -> None:
    """A denied camera ignores an update on a topic that a partial SUBACK still granted."""
    broker = _broker(
        deny_topics={shadow_topic("SN0002", "fake_systemInfo", "get/rejected")}
    )
    async with _running(broker) as running:
        await _until(lambda: running.link.status.denied_cameras == 1)
        await broker.push(
            shadow_topic("SN0002", "fake_configInfo", "update/documents"),
            load_fixture("shadow_config_update.json"),
        )
        await broker.push(
            shadow_topic("SN0001", "fake_configInfo", "update/documents"),
            load_fixture("shadow_config_update.json"),
        )
        # Messages arrive in order on one connection, so SN0001's new battery
        # is a barrier: SN0002's update was already handled by this point.
        await _until(lambda: running.recorder.states["SN0001"].battery == 81)
        assert "SN0002" not in running.recorder.states
        assert running.link.status.denied_cameras == 1


async def test_stop_during_a_start_counts_no_strike(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A start that stop() interrupts is not a real failure, so it counts no strike."""
    caplog.set_level(logging.DEBUG, logger="custom_components.siipet")
    broker = _broker(silent_subscribe={"SN0002"})
    async with _running(broker) as running:
        await _until(lambda: len(broker.connections) == 2)
        await asyncio.sleep(0.2)
        await running.link.stop()
        assert "refused the device state" not in caplog.text
        assert running.link.status.denied_cameras == 0


async def test_failed_callback_logs_one_warning_per_camera(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A callback that keeps failing warns once per camera, then only at debug level."""
    caplog.set_level(logging.DEBUG, logger="custom_components.siipet")
    async with _running(_broker()) as running:

        def fail_always(_sn: str) -> None:
            raise RuntimeError("callback failed")

        def logged_again(name: str) -> bool:
            return any(
                r.levelno == logging.DEBUG
                and name in r.getMessage()
                and "RuntimeError" in r.getMessage()
                for r in caplog.records
            )

        running.recorder.hook = fail_always
        # The broker counts a get before the link handles its reply, so the test
        # waits for the records that it checks.
        await _until(lambda: logged_again("Bathroom") and logged_again("Hallway"))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    for name in ("Bathroom", "Hallway"):
        matching = [r for r in warnings if name in r.getMessage()]
        assert len(matching) == 1
        message = matching[0].getMessage()
        assert "RuntimeError" in message
        debugs = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and r.getMessage() == message
        ]
        assert debugs
    assert len(running.broker.connections) == 1
    for private in PRIVATE:
        assert private not in caplog.text


async def test_strike_resets_after_a_success() -> None:
    """A successful start clears an earlier strike, so a later failed start does not deny the camera."""
    broker = _broker(close_on_get_budget={"SN0002": 1})
    async with _running(broker) as running:
        await _until(lambda: len(running.recorder.states) == 2)
        await _until(lambda: len(broker.connections) == 2)
        broker.close_on_get_budget["SN0002"] = 1
        await broker.close_all()
        await _until(
            lambda: (
                len(broker.connections) == 4 and running.recorder.connection[-1] is True
            )
        )
        assert running.link.status.denied_cameras == 0
        assert "SN0002" in running.recorder.states


async def test_stop() -> None:
    """Stop sends DISCONNECT, ends run, and reports no lost connection."""
    broker = _broker()
    async with _running(broker) as running:
        await _until(lambda: running.recorder.connection == [True])
        await running.link.stop()
        assert running.task.done()
        assert broker.connections[0].disconnected
        assert running.recorder.connection == [True]
        assert not running.link.status.connected


UPDATE = shadow_topic("SN0001", "fake_configInfo", "update")


async def _started(running: Running, sn: str = "SN0001") -> None:
    await _until(lambda: sn in running.recorder.states and running.link.can_write(sn))


async def test_update_desired_accepted() -> None:
    """A desired write goes to the config shadow with a client token and is accepted."""
    async with _running(_broker()) as running:
        await _started(running)
        result = await running.link.update_desired(
            "SN0001", "fillLight", {"level": 3}, limit=1
        )
        assert result is WriteResult.ACCEPTED
        [(topic, body)] = running.broker.updates
        assert topic == UPDATE
        assert body["state"] == {"desired": {"fillLight": {"level": 3}}}
        assert len(body["clientToken"]) == 32


async def test_update_desired_rejected(caplog: pytest.LogCaptureFixture) -> None:
    """A rejection raises, keeps the camera's state, and logs no topic or token."""
    caplog.set_level(logging.DEBUG)
    async with _running(_broker(reject_update={"SN0001"})) as running:
        await _started(running)
        with pytest.raises(ShadowWriteError) as err:
            await running.link.update_desired("SN0001", "pir", {"level": 2}, limit=1)
        assert err.value.reason == "rejected"
        assert "SN0001" in running.recorder.states
        assert running.recorder.dropped == []
        token = running.broker.updates[0][1]["clientToken"]
    for secret in (*PRIVATE, token):
        assert secret not in caplog.text


async def test_update_desired_unconfirmed_on_silence() -> None:
    """Without an answer the write counts as unconfirmed, as the app's QoS 0 publish."""
    async with _running(_broker(silent_update={"SN0001"})) as running:
        await _started(running)
        result = await running.link.update_desired(
            "SN0001", "pir", {"level": 2}, limit=0.2
        )
        assert result is WriteResult.UNCONFIRMED


async def test_update_desired_unconfirmed_when_the_connection_drops() -> None:
    """A drop after the publish is unconfirmed, and the camera comes back read-only."""
    async with _running(_broker(close_on_update={"SN0001"})) as running:
        await _started(running)
        result = await running.link.update_desired(
            "SN0001", "pir", {"level": 2}, limit=1
        )
        assert result is WriteResult.UNCONFIRMED
        await _until(lambda: running.recorder.connection == [True, False, True])
        second = running.broker.connections[1]
        read = shadow_topic("SN0001", "fake_configInfo", "get/accepted")
        assert read in second.subscriptions
        assert f"{UPDATE}/accepted" not in second.subscriptions
        assert not running.link.can_write("SN0001")
        assert running.link.writes_refused("SN0001")
        assert running.link.can_write("SN0002")
        assert not running.link.writes_refused("SN0002")
        assert running.recorder.dropped == []
        assert running.link.status.denied_cameras == 0
        assert len(running.broker.connections) == 2


async def test_writes_stay_refused_until_the_write_replies_subscribe() -> None:
    """After the pause ends, the camera stays read-only until a new start subscribes its write replies."""
    broker = _broker(close_on_update={"SN0001"})
    async with _running(broker) as running:
        await _started(running)
        await running.link.update_desired("SN0001", "pir", {"level": 2}, limit=1)
        # The pause lasts minutes, so the camera starts again without its write replies.
        await _until(lambda: running.recorder.connection == [True, False, True])
        running.clock.offset = FAST.denied_retry
        # A read round reads four shadows, and a start round follows it. After
        # three read rounds, a start round has run since the pause ended.
        reads = len(broker.gets)
        await _until(lambda: len(broker.gets) >= reads + 12)
        assert not running.link.can_write("SN0001")
        assert running.link.writes_refused("SN0001")
        assert f"{UPDATE}/accepted" not in broker.connections[1].subscriptions
        assert len(broker.connections) == 2


async def test_cameras_that_start_again_are_not_refused() -> None:
    """During a planned reconnect, a camera that has not started again cannot write, and is not refused."""
    fetch = AsyncMock(side_effect=[_credentials(), _credentials(hours=20)])
    broker = _broker()
    async with _running(broker, fetch=fetch) as running:
        await _started(running)
        # The new start of the camera waits for the reply time.
        broker.silent_get.add("SN0001")
        # The first credentials now need renewal, so the link reconnects.
        running.clock.offset = timedelta(hours=10)
        await _until(lambda: len(broker.connections) == 2)
        assert running.link.status.connected
        assert not running.link.can_write("SN0001")
        assert not running.link.writes_refused("SN0001")
        await _until(lambda: running.link.can_write("SN0001"))
        assert running.recorder.connection == [True]


@pytest.mark.parametrize(
    "held",
    [
        # SN0001 waits for its own reads.
        "SN0001",
        # SN0001 has read and waits for its write replies while SN0002 reads.
        "SN0002",
    ],
)
async def test_paused_camera_is_not_refused_while_it_starts_again(held: str) -> None:
    """After its pause ends, a camera is not refused until a new connection tries its write replies, and then can write."""
    issued = [_credentials(), _credentials(hours=20)]
    renew = asyncio.Event()

    async def credentials() -> IotCredentials:
        if len(issued) == 1:
            await renew.wait()
        return issued.pop(0)

    fetch = AsyncMock(side_effect=credentials)
    broker = _broker(close_on_update={"SN0001"})
    async with _running(broker, fetch=fetch) as running:
        await _started(running)
        await running.link.update_desired("SN0001", "pir", {"level": 2}, limit=1)
        await _until(lambda: running.recorder.connection == [True, False, True])
        assert running.link.writes_refused("SN0001")
        # The next reads of the held camera wait for the reply time.
        broker.silent_get.add(held)
        # The pause ends, and the first credentials need renewal, so the link
        # reconnects. It waits for new credentials until the test lets it go on.
        running.clock.offset = timedelta(hours=10)
        await _until(lambda: fetch.await_count == 2)
        assert running.link.status.connected
        assert not running.link.can_write("SN0001")
        assert not running.link.writes_refused("SN0001")
        # The old connection is closed, so each later read is on the new one.
        reads = len(broker.gets)
        renew.set()
        held_read = shadow_topic(held, "fake_systemInfo", "get")
        await _until(lambda: held_read in broker.gets[reads:])
        assert not running.link.can_write("SN0001")
        assert not running.link.writes_refused("SN0001")
        await _until(lambda: running.link.can_write("SN0001"))
        assert not running.link.writes_refused("SN0001")
        assert f"{UPDATE}/accepted" in broker.connections[2].subscriptions
        assert running.recorder.connection == [True, False, True]


async def test_failed_write_replies_stay_refused_after_the_pause() -> None:
    """A camera whose write reply subscription failed stays refused after the pause while its connection stays open."""
    broker = _broker(silent_topics={f"{UPDATE}/accepted"})
    async with _running(broker) as running:
        await _until(lambda: running.recorder.connection == [True])
        assert running.link.writes_refused("SN0001")
        running.clock.offset = FAST.denied_retry
        assert running.link.writes_refused("SN0001")
        assert not running.link.can_write("SN0001")
        assert running.link.can_write("SN0002")
        assert len(broker.connections) == 1


async def test_update_desired_ignores_other_tokens() -> None:
    """A reply for another write does not answer this one."""
    async with _running(_broker(silent_update={"SN0001"})) as running:
        await _started(running)
        write = asyncio.create_task(
            running.link.update_desired("SN0001", "pir", {"level": 2}, limit=0.3)
        )
        await _until(lambda: running.broker.updates)
        await running.broker.push(
            f"{UPDATE}/accepted", {"state": {}, "clientToken": "other"}
        )
        assert await write is WriteResult.UNCONFIRMED


async def test_refused_update_replies_keep_the_reads() -> None:
    """AWS IoT may refuse the update replies. The camera keeps its state but cannot be written."""
    refused = {f"{UPDATE}/accepted", f"{UPDATE}/rejected"}
    async with _running(_broker(deny_topics=refused)) as running:
        await _until(lambda: running.recorder.connection == [True])
        assert not running.link.can_write("SN0001")
        assert running.link.writes_refused("SN0001")
        assert not running.link.writes_refused("SN0002")
        assert "SN0001" in running.recorder.states
        assert running.recorder.dropped == []
        with pytest.raises(ShadowWriteError) as err:
            await running.link.update_desired("SN0001", "pir", {"level": 2}, limit=1)
        assert err.value.reason == "not_ready"
        assert running.broker.updates == []


async def test_write_replies_after_the_reads_of_every_camera() -> None:
    """A subscription limit that refuses write replies costs no camera its state."""
    cameras = {**CAMERAS, "SN0003": SHADOWS}
    # Room for the reads of three cameras and the write replies of one.
    broker = _broker(max_subscriptions=20)
    broker.documents["SN0003/fake_configInfo"] = load_fixture(
        "shadow_config_accepted.json"
    )
    async with _running(broker, cameras=cameras) as running:
        await _until(lambda: running.recorder.connection == [True])
        assert set(running.recorder.states) == set(cameras)
        assert running.recorder.dropped == []
        assert running.link.status.denied_cameras == 0
        assert running.link.can_write("SN0001")
        for sn in ("SN0002", "SN0003"):
            assert not running.link.can_write(sn)
            assert running.link.writes_refused(sn)
        assert len(broker.connections) == 1


async def test_cannot_write_without_a_connection() -> None:
    """Before the link connects, nothing is published."""
    link = ShadowLink(
        AsyncMock(), AsyncMock(), lambda *_: None, lambda _c: None, NAMES.__getitem__
    )
    link.set_cameras(CAMERAS)
    assert not link.can_write("SN0001")
    assert not link.writes_refused("SN0001")
    with pytest.raises(ShadowWriteError) as err:
        await link.update_desired("SN0001", "pir", {"level": 2}, limit=1)
    assert err.value.reason == "not_ready"


async def test_error_after_the_reads_is_no_strike() -> None:
    """An error in the write reply subscription does not count toward a denial."""
    broker = _broker(close_on_subscribe={f"{UPDATE}/accepted"})
    # A long backoff lets the test change the broker before the next connection.
    # A short retry ends the pause of the writes before the third connection.
    timings = replace(FAST, backoff=(0.3, 0.3), denied_retry=timedelta(seconds=0.2))
    async with _running(
        broker, cameras={"SN0001": SHADOWS}, timings=timings
    ) as running:
        await _until(lambda: broker.connections[0].ws.closed)
        broker.close_on_subscribe.clear()
        broker.close_on_get_budget["SN0001"] = 1
        await _started(running)
        assert running.link.status.denied_cameras == 0
        assert running.recorder.dropped == []
        assert len(broker.connections) == 3


@pytest.mark.parametrize(
    ("failure", "connections"), [("silent_topics", 1), ("close_on_subscribe", 3)]
)
async def test_failed_write_replies_keep_the_reads(
    failure: str, connections: int
) -> None:
    """A write reply subscription with no answer, or one that drops the connection, leaves the cameras read-only."""
    replies = {shadow_topic(sn, "fake_configInfo", "update/accepted") for sn in CAMERAS}
    broker = _broker(**{failure: replies})
    async with _running(broker) as running:
        await _until(lambda: running.recorder.connection == [True])
        assert set(running.recorder.states) == {"SN0001", "SN0002"}
        assert running.recorder.dropped == []
        assert running.link.status.denied_cameras == 0
        assert not running.link.can_write("SN0001")
        assert not running.link.can_write("SN0002")
        assert running.link.writes_refused("SN0001")
        assert running.link.writes_refused("SN0002")
        assert len(broker.connections) == connections


async def test_write_on_a_closed_connection_is_not_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write whose connection closes before the publish sends nothing and keeps the camera writable."""
    publish = MqttSession.publish

    async def close_first(self: MqttSession, topic: str, payload: bytes = b"") -> None:
        if topic.endswith("/update"):
            await self.close()
        await publish(self, topic, payload)

    async with _running(_broker()) as running:
        await _started(running)
        monkeypatch.setattr(MqttSession, "publish", close_first)
        with pytest.raises(ShadowWriteError) as err:
            await running.link.update_desired("SN0001", "pir", {"level": 2}, limit=1)
        assert err.value.reason == "not_ready"
        assert running.broker.updates == []
        await _until(
            lambda: (
                len(running.broker.connections) == 2
                and running.link.can_write("SN0001")
            )
        )


async def test_no_write_while_the_link_stops() -> None:
    """Once stop() begins, the link sends no write."""
    async with _running(_broker()) as running:
        await _started(running)
        stopping = asyncio.create_task(running.link.stop())
        await asyncio.sleep(0)
        assert running.link.status.connected
        assert not running.link.can_write("SN0001")
        with pytest.raises(ShadowWriteError) as err:
            await running.link.update_desired("SN0001", "pir", {"level": 2}, limit=1)
        assert err.value.reason == "not_ready"
        await stopping
        assert running.broker.updates == []


@pytest.mark.parametrize("limit", [0, -1])
async def test_spent_limit_sends_nothing(limit: float) -> None:
    """A write with no time left raises not_ready and publishes nothing."""
    async with _running(_broker()) as running:
        await _started(running)
        with pytest.raises(ShadowWriteError) as err:
            await running.link.update_desired(
                "SN0001", "pir", {"level": 2}, limit=limit
            )
        assert err.value.reason == "not_ready"
        # Messages on one connection keep their order, so a later write that
        # is accepted shows that the first one sent nothing.
        result = await running.link.update_desired(
            "SN0001", "pir", {"level": 2}, limit=1
        )
        assert result is WriteResult.ACCEPTED
        assert len(running.broker.updates) == 1


@pytest.mark.parametrize("drop", [False, True])
async def test_publish_error_after_the_write_is_unconfirmed(
    monkeypatch: pytest.MonkeyPatch, drop: bool
) -> None:
    """A publish error after the message left is unconfirmed. A drop also pauses the writes."""
    publish = MqttSession.publish

    async def send_then_fail(
        self: MqttSession, topic: str, payload: bytes = b""
    ) -> None:
        await publish(self, topic, payload)
        if topic.endswith("/update"):
            await self.wait_closed(0.2)
            raise MqttError("The broker did not take the message in time")

    broker = _broker(
        close_on_update={"SN0001"} if drop else set(),
        silent_update=set() if drop else {"SN0001"},
    )
    async with _running(broker) as running:
        await _started(running)
        monkeypatch.setattr(MqttSession, "publish", send_then_fail)
        result = await running.link.update_desired(
            "SN0001", "pir", {"level": 2}, limit=1
        )
        assert result is WriteResult.UNCONFIRMED
        assert len(running.broker.updates) == 1
        if drop:
            await _until(lambda: running.recorder.connection == [True, False, True])
            assert not running.link.can_write("SN0001")
            assert running.link.can_write("SN0002")
        else:
            assert running.link.can_write("SN0001")
            assert len(running.broker.connections) == 1


async def test_write_during_a_planned_reconnect_pauses_nothing() -> None:
    """A write in flight when the link reconnects on its own leaves the camera writable."""
    soon = replace(
        _credentials(),
        expires=datetime.now(UTC) + timedelta(minutes=10, seconds=1),
    )
    fetch = AsyncMock(side_effect=[soon, _credentials()])
    broker = _broker(silent_update={"SN0001"})
    async with _running(broker, fetch=fetch) as running:
        await _started(running)
        loop = asyncio.get_running_loop()
        start = loop.time()
        result = await running.link.update_desired(
            "SN0001", "pir", {"level": 2}, limit=3
        )
        assert result is WriteResult.UNCONFIRMED
        # The reconnect ended the wait, not the limit.
        assert loop.time() - start < 2.5
        await _until(
            lambda: len(broker.connections) == 2 and running.link.can_write("SN0001")
        )
        assert running.recorder.connection == [True]


@pytest.mark.parametrize("failure", ["error", "stall"])
@pytest.mark.parametrize("reply", ["accepted", "rejected"])
async def test_reply_during_a_failed_publish_counts(
    monkeypatch: pytest.MonkeyPatch, failure: str, reply: str
) -> None:
    """An answer that arrives before the publish fails or runs out of time decides the result."""
    publish = MqttSession.publish
    broker = _broker(silent_update={"SN0001"})

    async def answer_then_fail(
        self: MqttSession, topic: str, payload: bytes = b""
    ) -> None:
        await publish(self, topic, payload)
        if not topic.endswith("/update"):
            return
        token = json.loads(payload)["clientToken"]
        await broker.push(f"{topic}/{reply}", {"clientToken": token})
        # The SUBACK comes after the reply, so the link has read the reply.
        await self.subscribe(["$aws/things/SN0001/barrier"], 1)
        if failure == "stall":
            await asyncio.sleep(5)
        raise MqttError("The broker did not take the message in time")

    async with _running(broker) as running:
        await _started(running)
        monkeypatch.setattr(MqttSession, "publish", answer_then_fail)
        write = running.link.update_desired("SN0001", "pir", {"level": 2}, limit=0.3)
        if reply == "accepted":
            assert await write is WriteResult.ACCEPTED
        else:
            with pytest.raises(ShadowWriteError) as err:
                await write
            assert err.value.reason == "rejected"
        assert len(broker.updates) == 1
