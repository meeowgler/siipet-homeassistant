"""A lasting MQTT connection to AWS IoT that reads the device shadows of the cameras."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import json
import logging
from typing import Any
from uuid import uuid4

import aiohttp

from .errors import ShadowWriteError, SiiPetError
from .models import (
    CONFIG_SHADOW,
    SHADOW_KINDS,
    SYSTEM_SHADOW,
    CameraShadows,
    DeviceState,
    IotCredentials,
    ShadowPart,
    parse_shadow,
)
from .mqtt import MqttError, MqttNotSent, MqttRefused, MqttSession
from .sigv4 import iot_ws_url

_LOGGER = logging.getLogger(__name__)

ACCEPTED = "get/accepted"
REJECTED = "get/rejected"
DOCUMENTS = "update/documents"
REPLIES = (ACCEPTED, REJECTED, DOCUMENTS)
UPDATE_ACCEPTED = "update/accepted"
UPDATE_REJECTED = "update/rejected"
UPDATE_REPLIES = (UPDATE_ACCEPTED, UPDATE_REJECTED)
# Failed starts in a row that deny a camera.
DENY_STRIKES = 2


class WriteResult(StrEnum):
    """The answer of AWS IoT to a desired write."""

    ACCEPTED = "accepted"
    # AWS IoT did not answer in time, the publish failed after it started, or
    # the connection closed after the publish. The app does not wait for an
    # answer either, so the change goes on.
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True, slots=True)
class LinkTimings:
    """The waits of the link, in seconds unless the type says otherwise."""

    reply: float = 10.0
    keepalive: int = 60
    ping_timeout: float = 30.0
    read_interval: float = 300.0
    renew_margin: timedelta = timedelta(minutes=10)
    denied_retry: timedelta = timedelta(hours=1)
    backoff: tuple[float, ...] = (5.0, 30.0, 60.0, 120.0, 300.0)


@dataclass(frozen=True, slots=True)
class LinkStatus:
    """The state of the link for diagnostics. It holds no private value."""

    connected: bool
    connected_since: datetime | None
    last_message: datetime | None
    cameras_with_state: int
    denied_cameras: int


def shadow_topic(sn: str, shadow: str, suffix: str) -> str:
    """Return the MQTT topic of a named shadow operation."""
    return f"$aws/things/{sn}/shadow/name/{shadow}/{suffix}"


def _describe(err: BaseException) -> str:
    """Describe an error without its URL or other private text."""
    if isinstance(err, aiohttp.WSServerHandshakeError):
        return f"WebSocket handshake failed with HTTP {err.status}"
    if isinstance(err, SiiPetError):
        return str(err)
    if isinstance(err, TimeoutError):
        return "timeout"
    return type(err).__name__


def _refused_credentials(err: BaseException) -> bool:
    """True when AWS IoT refuses the credentials, so new ones are needed."""
    if isinstance(err, MqttRefused):
        return True
    return isinstance(err, aiohttp.WSServerHandshakeError) and err.status in (401, 403)


def _rejected_code(payload: bytes) -> object:
    """Return the `code` of a rejected reply. Its message can name the shadow."""
    try:
        return json.loads(payload).get("code")
    except ValueError, AttributeError:
        return None


class ShadowLink:
    """Keep one MQTT connection open and report the device state of each camera.

    `on_state` and `on_connection` run in the event loop. After `stop()` the
    link calls neither of them. `on_state` gets `None` when a camera has no
    state any more.
    """

    def __init__(
        self,
        websession: aiohttp.ClientSession,
        fetch_credentials: Callable[[], Awaitable[IotCredentials]],
        on_state: Callable[[str, DeviceState | None], None],
        on_connection: Callable[[bool], None],
        label: Callable[[str], str],
        *,
        timings: LinkTimings | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        url: Callable[[IotCredentials, datetime], str] = iot_ws_url,
    ) -> None:
        """Create the link. `label` names a camera in logs."""
        self._websession = websession
        self._fetch_credentials = fetch_credentials
        self._on_state = on_state
        self._on_connection = on_connection
        self._label = label
        self._timings = timings or LinkTimings()
        self._clock = clock
        self._url = url
        self._credentials: IotCredentials | None = None
        self._cameras: dict[str, CameraShadows] = {}
        self._topics: dict[str, tuple[str, str, str]] = {}
        self._parts: dict[str, dict[str, ShadowPart]] = {}
        self._versions: dict[tuple[str, str], int] = {}
        self._pending: dict[tuple[str, str], asyncio.Future[None]] = {}
        self._started: set[str] = set()
        self._writable: set[str] = set()
        self._writes_refused: set[str] = set()
        self._writes_paused: dict[str, datetime] = {}
        # Cameras whose write replies this connection skipped, because their
        # writes were on hold at the write-reply step, or because that step
        # failed and paused them.
        self._writes_skipped: set[str] = set()
        self._writes: dict[str, asyncio.Future[bool]] = {}
        self._denied: dict[str, datetime] = {}
        self._denied_logged: set[str] = set()
        self._callback_warned: set[str] = set()
        self._strikes: dict[str, int] = {}
        self._rejected_logged: set[tuple[str, str]] = set()
        self._session: MqttSession | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._connected = False
        self._connected_since: datetime | None = None
        self._last_message: datetime | None = None
        self._failures = 0
        self._warned = False

    @property
    def status(self) -> LinkStatus:
        """The state of the link for diagnostics."""
        return LinkStatus(
            connected=self._connected,
            connected_since=self._connected_since,
            last_message=self._last_message,
            cameras_with_state=len(self._parts),
            denied_cameras=len(self._denied),
        )

    def set_cameras(self, cameras: Mapping[str, CameraShadows]) -> None:
        """Replace the camera list.

        A new camera starts on the open connection within one keepalive. A
        removed camera loses its state at once.
        """
        for sn, shadows in list(self._cameras.items()):
            if cameras.get(sn) != shadows:
                self._forget(sn)
        self._cameras = dict(cameras)
        self._topics = {
            shadow_topic(sn, shadows.name(kind), suffix): (sn, kind, suffix)
            for sn, shadows in self._cameras.items()
            for kind in SHADOW_KINDS
            for suffix in REPLIES
        } | {
            shadow_topic(sn, shadows.config, suffix): (sn, CONFIG_SHADOW, suffix)
            for sn, shadows in self._cameras.items()
            for suffix in UPDATE_REPLIES
        }

    async def run(self) -> None:
        """Keep the connection open until `stop()` or cancellation."""
        self._task = asyncio.current_task()
        while not self._stopping:
            try:
                await self._connection()
            except Exception as err:
                if self._stopping:
                    return
                if _refused_credentials(err):
                    self._credentials = None
                self._set_connected(False)
                backoff = self._timings.backoff
                delay = backoff[min(self._failures, len(backoff) - 1)]
                self._failures += 1
                if self._warned:
                    _LOGGER.debug(
                        "The device state connection failed again, next try in %s s: %s",
                        delay,
                        _describe(err),
                    )
                else:
                    _LOGGER.warning(
                        "The device state connection failed, next try in %s s: %s",
                        delay,
                        _describe(err),
                    )
                    self._warned = True
                await asyncio.sleep(delay)

    async def stop(self) -> None:
        """Close the connection and end `run()`."""
        self._stopping = True
        if self._session is not None:
            await self._session.close()
        task = self._task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._connected = False
        self._connected_since = None

    async def _connection(self) -> None:
        """Open one connection, start the cameras, and serve until it ends."""
        credentials = await self._current_credentials()
        async with asyncio.timeout(self._timings.reply):
            ws = await self._websession.ws_connect(
                self._url(credentials, self._clock()), protocols=("mqtt",)
            )
        session = MqttSession(ws, self._handle_message, write_limit=self._timings.reply)
        self._session = session
        try:
            await session.connect(
                f"{credentials.identity_id}:{uuid4().hex}",
                self._timings.keepalive,
                self._timings.reply,
            )
            await self._start_cameras(session)
            self._failures = 0
            if self._warned:
                _LOGGER.info("The device state connection works again")
                self._warned = False
            self._set_connected(True)
            await self._serve(session, credentials)
        finally:
            self._session = None
            # Each camera starts again on the next connection, and that start
            # decides its write replies again.
            self._started.clear()
            self._writable.clear()
            self._writes_skipped.clear()
            await session.close()

    async def _current_credentials(self) -> IotCredentials:
        credentials = self._credentials
        if credentials is None or (
            self._clock() >= credentials.expires - self._timings.renew_margin
        ):
            credentials = await self._fetch_credentials()
            self._credentials = credentials
        return credentials

    async def _serve(self, session: MqttSession, credentials: IotCredentials) -> None:
        """Ping, read, and start cameras until the connection ends.

        Return for a planned reconnect before the credentials expire.
        """
        timings = self._timings
        loop = asyncio.get_running_loop()
        renew_at = max(
            credentials.expires - timings.renew_margin,
            self._clock() + timedelta(seconds=timings.read_interval),
        )
        next_read = loop.time() + timings.read_interval
        while True:
            wait = min(
                timings.keepalive,
                next_read - loop.time(),
                (renew_at - self._clock()).total_seconds(),
            )
            if await session.wait_closed(max(0.0, wait)):
                raise MqttError("The broker closed the connection")
            if self._clock() >= renew_at:
                return
            await session.ping(timings.ping_timeout)
            if loop.time() >= next_read:
                next_read = loop.time() + timings.read_interval
                await self._read_all(session)
            await self._start_cameras(session)

    async def _start_cameras(self, session: MqttSession) -> None:
        """Start each camera that is not started, unless it waits after a denial.

        In one round, every camera reads first, and then the cameras that
        started subscribe to their write replies. AWS IoT limits the
        subscriptions of one connection, so in that round a limit reached by
        the write replies costs no camera its reads. A camera that starts in a
        later round reads after the write replies of the earlier rounds.
        """
        started: list[tuple[str, CameraShadows]] = []
        for sn in list(self._cameras):
            shadows = self._cameras.get(sn)
            if shadows is None or sn in self._started:
                # set_cameras can remove a camera while an earlier one starts.
                continue
            denied_at = self._denied.get(sn)
            if denied_at is not None and (
                self._clock() - denied_at < self._timings.denied_retry
            ):
                continue
            await self._start_camera(session, sn, shadows)
            started.append((sn, shadows))
        for sn, shadows in started:
            # set_cameras can replace or remove a camera, and a read can deny
            # it, while other cameras start.
            if self._cameras.get(sn) != shadows or sn not in self._started:
                continue
            if self._writes_on_hold(sn):
                self._writes_skipped.add(sn)
                continue
            await self._subscribe_updates(session, sn, shadows)

    async def _start_camera(
        self, session: MqttSession, sn: str, shadows: CameraShadows
    ) -> None:
        """Subscribe to the replies of both shadows, and read both.

        A refused read subscription denies the camera at once. An MqttError
        in the reads is a strike, and `DENY_STRIKES` strikes in a row deny the
        camera. The error still ends the connection.
        """
        # A retry after the denied wait starts clean, so its replies are read.
        self._denied.pop(sn, None)
        try:
            await self._subscribe_and_read(session, sn, shadows)
        except MqttError:
            # A camera that set_cameras replaced or removed gets no strike, and
            # neither does one that stop() interrupted.
            if not self._stopping and self._cameras.get(sn) == shadows:
                self._strike(sn)
            raise

    async def _subscribe_and_read(
        self, session: MqttSession, sn: str, shadows: CameraShadows
    ) -> None:
        topics = [
            shadow_topic(sn, shadows.name(kind), suffix)
            for kind in SHADOW_KINDS
            for suffix in REPLIES
        ]
        if not all(await session.subscribe(topics, self._timings.reply)):
            # A camera that set_cameras replaced or removed during the wait gets no denial.
            if self._cameras.get(sn) == shadows:
                self._deny(sn)
            return
        loop = asyncio.get_running_loop()
        replies: list[asyncio.Future[None]] = []
        for kind in SHADOW_KINDS:
            future: asyncio.Future[None] = loop.create_future()
            self._pending[(sn, kind)] = future
            replies.append(future)
        try:
            for kind in SHADOW_KINDS:
                await session.publish(shadow_topic(sn, shadows.name(kind), "get"))
            await self._wait_replies(session, replies)
        finally:
            for kind in SHADOW_KINDS:
                self._pending.pop((sn, kind), None)
        if self._cameras.get(sn) == shadows:
            # set_cameras can replace or remove the camera while it starts.
            self._denied.pop(sn, None)
            self._denied_logged.discard(sn)
            self._strikes.pop(sn, None)
            self._started.add(sn)

    async def _subscribe_updates(
        self, session: MqttSession, sn: str, shadows: CameraShadows
    ) -> None:
        """Subscribe to the replies of desired writes.

        AWS IoT can refuse these topics to an account that may read. A refusal
        only means that the camera cannot be written, so it never denies the
        camera. A subscription that fails pauses the writes of the camera, so
        the connection goes on without them, and the next start reads it
        without them. Neither counts a strike. The error ends the connection
        only when the connection is already closed.
        """
        topics = [shadow_topic(sn, shadows.config, suffix) for suffix in UPDATE_REPLIES]
        try:
            granted = await session.subscribe(topics, self._timings.reply)
        except MqttError:
            self._pause_writes(sn, shadows)
            if session.closed:
                raise
            if self._cameras.get(sn) == shadows:
                self._writes_skipped.add(sn)
            return
        if self._cameras.get(sn) != shadows:
            return
        if not all(granted):
            self._writes_refused.add(sn)
            _LOGGER.debug("SiiPet refused the write replies of %s", self._label(sn))
            return
        self._writes_refused.discard(sn)
        self._writes_paused.pop(sn, None)
        self._writes_skipped.discard(sn)
        self._writable.add(sn)

    def _pause_writes(self, sn: str, shadows: CameraShadows) -> None:
        """Make the camera not writable, and skip its write replies for the retry time."""
        self._writable.discard(sn)
        if self._stopping or self._cameras.get(sn) != shadows:
            return
        self._writes_paused[sn] = self._clock()
        _LOGGER.debug(
            "Writes to %s pause for %s", self._label(sn), self._timings.denied_retry
        )

    def _pause_if_dropped(
        self, session: MqttSession, sn: str, shadows: CameraShadows
    ) -> None:
        """Pause the writes of the camera when the connection dropped during a write.

        AWS IoT can close the connection for a publish that the policy forbids,
        so the reads go on without the writes. A close that the link started,
        such as a planned reconnect or `stop()`, pauses nothing.
        """
        if session.dropped:
            self._pause_writes(sn, shadows)

    def _writes_on_hold(self, sn: str) -> bool:
        """True while the writes of the camera are paused."""
        paused_at = self._writes_paused.get(sn)
        return paused_at is not None and (
            self._clock() - paused_at < self._timings.denied_retry
        )

    def writes_refused(self, sn: str) -> bool:
        """True when a change to the camera must go without a desired write.

        This holds when AWS IoT refused the write replies of the camera, while
        its writes are paused, and for the rest of a connection on which the
        write-reply step of the camera was skipped during a pause or failed
        and started one. A refusal lasts until AWS IoT grants the write
        replies on a later start. After the pause, a camera that has not
        reached its write-reply step on the current connection is not refused
        because of the pause, because that step tries the write replies again.
        """
        return (
            sn in self._writes_refused
            or self._writes_on_hold(sn)
            or sn in self._writes_skipped
        )

    def can_write(self, sn: str) -> bool:
        """True while the link is connected and can confirm writes for the camera."""
        session = self._session
        return (
            self._connected
            and not self._stopping
            and session is not None
            and not session.closed
            and sn in self._writable
        )

    async def update_desired(
        self, sn: str, key: str, value: Mapping[str, Any], *, limit: float
    ) -> WriteResult:
        """Write `{key: value}` to the desired state of the camera's config shadow.

        Wait up to `limit` seconds for the answer of AWS IoT. Raise
        ShadowWriteError("not_ready") when the write cannot leave, and
        ShadowWriteError("rejected") when AWS IoT rejects it.
        """
        session = self._session
        shadows = self._cameras.get(sn)
        if limit <= 0 or session is None or shadows is None or not self.can_write(sn):
            raise ShadowWriteError("not_ready")
        token = uuid4().hex
        body = json.dumps(
            {"state": {"desired": {key: value}}, "clientToken": token},
            separators=(",", ":"),
        ).encode()
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._writes[token] = future
        try:
            async with asyncio.timeout(limit):
                try:
                    await session.publish(
                        shadow_topic(sn, shadows.config, "update"), body
                    )
                except MqttNotSent as err:
                    # The connection closed before the publish, so the message
                    # did not leave.
                    raise ShadowWriteError("not_ready") from err
                except MqttError:
                    # The write failed or stalled after it started, so the
                    # message can still reach AWS IoT.
                    pass
                else:
                    await self._wait_answer(session, future)
        except TimeoutError:
            pass
        finally:
            self._writes.pop(token, None)
        # An answer can arrive while the publish fails or the limit runs out,
        # so it decides the result whenever it is there.
        if future.done():
            if not future.result():
                raise ShadowWriteError("rejected")
            return WriteResult.ACCEPTED
        self._pause_if_dropped(session, sn, shadows)
        return WriteResult.UNCONFIRMED

    async def _wait_answer(
        self, session: MqttSession, future: asyncio.Future[bool]
    ) -> None:
        """Wait until the answer arrives or the connection closes."""
        closed = asyncio.ensure_future(session.wait_closed())
        try:
            await asyncio.wait({future, closed}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            closed.cancel()
            with suppress(asyncio.CancelledError):
                await closed

    def _strike(self, sn: str) -> None:
        strikes = self._strikes.get(sn, 0) + 1
        if strikes < DENY_STRIKES:
            self._strikes[sn] = strikes
            return
        self._deny(sn)

    async def _wait_replies(
        self, session: MqttSession, replies: list[asyncio.Future[None]]
    ) -> None:
        """Wait up to the reply timeout. Raise MqttError if the connection closes."""
        both = asyncio.gather(*replies)
        closed = asyncio.ensure_future(session.wait_closed())
        try:
            done, _pending = await asyncio.wait(
                {both, closed},
                timeout=self._timings.reply,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            # A canceled gather keeps a CancelledError that must be read.
            for waiter in (both, closed):
                waiter.cancel()
                with suppress(asyncio.CancelledError):
                    await waiter
        if closed in done and closed.result():
            raise MqttError("The broker closed the connection")

    async def _read_all(self, session: MqttSession) -> None:
        """Read both shadows of each started camera again."""
        for sn in list(self._started):
            shadows = self._cameras.get(sn)
            if shadows is None:
                continue
            for kind in SHADOW_KINDS:
                await session.publish(shadow_topic(sn, shadows.name(kind), "get"))

    def _handle_message(self, topic: str, payload: bytes) -> None:
        if self._stopping:
            return
        target = self._topics.get(topic)
        if target is None:
            return
        sn, kind, suffix = target
        self._last_message = self._clock()
        if suffix in UPDATE_REPLIES:
            self._answer_write(payload, accepted=suffix == UPDATE_ACCEPTED)
            return
        if sn in self._denied:
            # A partial SUBACK can leave a granted topic subscribed, but a
            # denied camera keeps no state until its retry starts clean.
            self._resolve(sn, kind)
            return
        if suffix == REJECTED:
            if (sn, kind) not in self._rejected_logged:
                self._rejected_logged.add((sn, kind))
                _LOGGER.debug(
                    "SiiPet rejected a %s shadow read of %s with code %s",
                    kind,
                    self._label(sn),
                    _rejected_code(payload),
                )
            self._resolve(sn, kind)
            return
        try:
            message = json.loads(payload)
        except ValueError:
            _LOGGER.debug("A shadow message of %s is not JSON", self._label(sn))
            message = None
        part = parse_shadow(kind, message)
        if part is not None and not self._stale(sn, kind, part):
            parts = self._parts.setdefault(sn, {})
            parts[kind] = part
            self._notify(
                sn,
                DeviceState.from_parts(
                    parts.get(CONFIG_SHADOW), parts.get(SYSTEM_SHADOW)
                ),
            )
        if suffix == ACCEPTED:
            self._resolve(sn, kind)

    def _answer_write(self, payload: bytes, *, accepted: bool) -> None:
        try:
            token = json.loads(payload).get("clientToken")
        except ValueError, AttributeError:
            return
        future = self._writes.get(token) if isinstance(token, str) else None
        if future is not None and not future.done():
            future.set_result(accepted)

    def _notify(self, sn: str, state: DeviceState | None) -> None:
        """Call `on_state`. An error in it does not end the connection."""
        try:
            self._on_state(sn, state)
        except Exception as err:
            if sn in self._callback_warned:
                _LOGGER.debug(
                    "Could not use the device state of %s: %s",
                    self._label(sn),
                    type(err).__name__,
                )
                return
            self._callback_warned.add(sn)
            _LOGGER.warning(
                "Could not use the device state of %s: %s",
                self._label(sn),
                type(err).__name__,
            )

    def _stale(self, sn: str, kind: str, part: ShadowPart) -> bool:
        """True for a document older than the last one of the same shadow."""
        if part.version is None:
            return False
        last = self._versions.get((sn, kind))
        if last is not None and part.version < last:
            return True
        self._versions[(sn, kind)] = part.version
        return False

    def _resolve(self, sn: str, kind: str) -> None:
        future = self._pending.get((sn, kind))
        if future is not None and not future.done():
            future.set_result(None)

    def _deny(self, sn: str) -> None:
        """Skip the camera for the retry time, and drop its state."""
        self._denied[sn] = self._clock()
        self._started.discard(sn)
        self._writable.discard(sn)
        self._writes_skipped.discard(sn)
        self._strikes.pop(sn, None)
        self._parts.pop(sn, None)
        for kind in SHADOW_KINDS:
            self._versions.pop((sn, kind), None)
        if not self._stopping:
            self._notify(sn, None)
        if sn in self._denied_logged:
            _LOGGER.debug(
                "SiiPet still refuses the device state of %s", self._label(sn)
            )
            return
        self._denied_logged.add(sn)
        _LOGGER.warning(
            "SiiPet refused the device state of %s. The next try is in %s",
            self._label(sn),
            self._timings.denied_retry,
        )

    def _forget(self, sn: str) -> None:
        self._parts.pop(sn, None)
        self._started.discard(sn)
        self._writable.discard(sn)
        self._writes_refused.discard(sn)
        self._writes_paused.pop(sn, None)
        self._writes_skipped.discard(sn)
        self._denied.pop(sn, None)
        self._denied_logged.discard(sn)
        self._callback_warned.discard(sn)
        self._strikes.pop(sn, None)
        for kind in SHADOW_KINDS:
            self._versions.pop((sn, kind), None)
            self._rejected_logged.discard((sn, kind))
            self._resolve(sn, kind)

    def _set_connected(self, connected: bool) -> None:
        if connected == self._connected:
            return
        self._connected = connected
        self._connected_since = self._clock() if connected else None
        if not self._stopping:
            self._on_connection(connected)
