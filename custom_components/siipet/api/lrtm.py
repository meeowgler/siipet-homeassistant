"""The SiiPet realtime command lane (LRTM), on a Centrifugo WebSocket.

The app changes a camera setting by publishing a command to the camera's
request channel on a Centrifugo server. This module speaks the JSON protocol:
each text frame holds one or more newline-separated JSON objects. A command is
`{"id": n, "<method>": {...}}` and its reply is `{"id": n, "<method>": {...}}`
or `{"id": n, "error": {...}}`. A lone `{}` from the server is a ping, answered
with `{}`. Only `connect` and `publish` are used.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
import json
import logging
from typing import Any
import uuid

import aiohttp

from .auth import Session
from .errors import (
    LrtmError,
    LrtmServerError,
    LrtmTransportError,
    LrtmUnconfirmedError,
    SiiPetAuthError,
)

_LOGGER = logging.getLogger(__name__)

LRTM_URL = "wss://wss-siipet.linkric.com/connection/websocket"
REQUEST_CHANNEL = "device:joy1:{sn}:app:dev:request"
# The default name of centrifuge-java, the client library of the Android app.
CLIENT_NAME = "java"
# The platform that the Android app sends in its connect data.
PLATFORM = 1
# The server answers an invalid token and an ended session token with 401.
AUTH_ERROR_CODES = frozenset({401})
# Each frame and each reply of one command gets at most this long.
STEP_LIMIT = 10.0
# Closing the socket after a command gets at most this long. `LrtmClient.send`
# waits for the close only within its limit, and a longer close goes on in the
# background.
CLOSE_LIMIT = 1.0


def encode_command(command_id: int, method: str, params: dict[str, Any]) -> str:
    """One Centrifugo command frame."""
    return json.dumps({"id": command_id, method: params}, separators=(",", ":"))


def device_command(sn: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The request envelope the camera expects, with a fresh session id."""
    return {
        "request": {
            "header": {"name": name, "sessionId": str(uuid.uuid4()), "deviceId": sn},
            "payload": payload,
        }
    }


class LrtmSession:
    """One Centrifugo connection on an open WebSocket.

    A task reads frames until the socket closes. Replies are matched by id;
    a lone `{}` ping is answered; pushes go to `on_push`. Requests fail with
    LrtmTransportError when the connection closes.
    """

    def __init__(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        on_push: Callable[[str, dict[str, Any]], None] | None = None,
        *,
        write_limit: float = 10.0,
    ) -> None:
        """Wrap an open WebSocket. Call `connect` before anything else."""
        self._ws = ws
        self._on_push = on_push
        self._write_limit = write_limit
        self._waiters: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._closed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._command_id = 0

    @property
    def closed(self) -> bool:
        """True after the connection closed."""
        return self._closed.is_set()

    async def connect(self, data: dict[str, Any], limit: float) -> dict[str, Any]:
        """Send the connect command and return the connect reply."""
        self._task = asyncio.get_running_loop().create_task(self._read_loop())
        return await self._request(
            "connect", {"name": CLIENT_NAME, "data": data}, limit
        )

    async def publish(
        self,
        channel: str,
        data: dict[str, Any],
        limit: float,
        *,
        on_write: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Publish to a channel and return the publish reply.

        `on_write` runs right before the socket writes the publish frame. On a
        closed connection nothing is written and `on_write` does not run.
        """
        return await self._request(
            "publish", {"channel": channel, "data": data}, limit, on_write
        )

    async def close(self) -> None:
        """Close the socket and stop the reader."""
        self._mark_closed()
        try:
            with suppress(TimeoutError, aiohttp.ClientError, ConnectionError):
                async with asyncio.timeout(self._write_limit):
                    await self._ws.close()
        finally:
            # Also when the close itself is canceled, so no reader stays behind.
            task = self._task
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def _request(
        self,
        method: str,
        params: dict[str, Any],
        limit: float,
        on_write: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        self._command_id += 1
        command_id = self._command_id
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._waiters[command_id] = future
        try:
            async with asyncio.timeout(limit):
                await self._send(encode_command(command_id, method, params), on_write)
                return await future
        except TimeoutError as err:
            raise LrtmTransportError(
                f"The {method} command was not answered in time"
            ) from err
        finally:
            self._waiters.pop(command_id, None)
            if not future.done():
                future.cancel()

    async def _send(
        self, frame: str, on_write: Callable[[], None] | None = None
    ) -> None:
        if self._closed.is_set():
            raise LrtmTransportError("The realtime connection is closed")
        if on_write is not None:
            # A write that fails or stalls can still have put the frame on
            # the wire.
            on_write()
        try:
            await self._ws.send_str(frame)
        except (aiohttp.ClientError, ConnectionError) as err:
            raise LrtmTransportError("Could not send to the realtime server") from err

    async def _read_loop(self) -> None:
        try:
            async for message in self._ws:
                if message.type is aiohttp.WSMsgType.TEXT:
                    for line in message.data.splitlines():
                        if line:
                            await self._dispatch(line)
                elif message.type is aiohttp.WSMsgType.ERROR:
                    break
        except LrtmError as err:
            _LOGGER.debug("Closing the realtime connection: %s", err)
        finally:
            self._mark_closed()

    async def _dispatch(self, line: str) -> None:
        try:
            frame = json.loads(line)
        except ValueError:
            return
        if not isinstance(frame, dict):
            return
        if not frame:
            # A lone empty object is a server ping; answer with an empty object.
            await self._send("{}")
            return
        if "push" in frame:
            self._dispatch_push(frame["push"])
            return
        command_id = frame.get("id")
        if not isinstance(command_id, int):
            return
        future = self._waiters.get(command_id)
        if future is None or future.done():
            return
        error = frame.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            if code in AUTH_ERROR_CODES:
                future.set_exception(
                    SiiPetAuthError("The realtime server rejected the session")
                )
            else:
                future.set_exception(
                    LrtmServerError(code if isinstance(code, int) else None)
                )
        else:
            reply = next(
                (v for k, v in frame.items() if k != "id" and isinstance(v, dict)), {}
            )
            future.set_result(reply)

    def _dispatch_push(self, push: Any) -> None:
        if self._on_push is None or not isinstance(push, dict):
            return
        channel = push.get("channel")
        pub = push.get("pub")
        if isinstance(channel, str) and isinstance(pub, dict) and "data" in pub:
            data = pub["data"]
            if isinstance(data, dict):
                self._on_push(channel, data)

    def _mark_closed(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        for future in self._waiters.values():
            if not future.done():
                future.set_exception(
                    LrtmTransportError("The realtime connection closed")
                )


class LrtmClient:
    """Send one command to a camera over a short connection, as the app does.

    One connection per command keeps nothing open between the rare changes.
    Commands to different cameras run at the same time.
    """

    def __init__(
        self,
        websession: aiohttp.ClientSession,
        get_session: Callable[[], Awaitable[Session]],
        recover_session: Callable[[Session], Awaitable[Session]],
        *,
        url: str = LRTM_URL,
    ) -> None:
        """`get_session` gives the renewed session, `recover_session` a new one after an auth error."""
        self._websession = websession
        self._get_session = get_session
        self._recover_session = recover_session
        self._url = url
        # Closes that go on after `send` returned. The set keeps the tasks alive.
        self._closing: set[asyncio.Task[None]] = set()

    async def send(
        self,
        sn: str,
        command: str,
        payload: Mapping[str, Any],
        *,
        limit: float,
        still_wanted: Callable[[], bool] | None = None,
    ) -> None:
        """Publish `command` to the camera.

        Raise SiiPetAuthError when the session cannot be recovered,
        LrtmServerError for an error answer, and LrtmTransportError when the
        server cannot be reached or does not answer within `limit` seconds.
        When the failure comes after the write of the publish frame started,
        raise LrtmUnconfirmedError, because the camera may still apply the
        command.
        When `still_wanted` returns False right before a publish, publish
        nothing and raise LrtmTransportError.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + limit
        opened: list[LrtmSession] = []
        published = False

        def on_write() -> None:
            nonlocal published
            published = True

        async def attempt(session: Session) -> None:
            lrtm = await self._open(session, opened)
            # Nothing yields to the event loop between this check and the
            # write of the publish frame, so a stop cannot slip in between.
            if still_wanted is not None and not still_wanted():
                raise LrtmTransportError("The command was stopped before it was sent")
            await lrtm.publish(
                REQUEST_CHANNEL.format(sn=sn),
                device_command(sn, command, dict(payload)),
                STEP_LIMIT,
                on_write=on_write,
            )

        try:
            try:
                async with asyncio.timeout_at(deadline):
                    session = await self._get_session()
                    try:
                        await attempt(session)
                    except SiiPetAuthError:
                        # The server answered with an auth error, so it did
                        # not take the command and one more try is safe.
                        published = False
                        session = await self._recover_session(session)
                        await attempt(session)
            finally:
                # Outside the limit, so a slow close cannot turn an answer
                # that came in time into a timeout.
                await self._close(opened, deadline)
        except TimeoutError as err:
            if published:
                raise LrtmUnconfirmedError from err
            raise LrtmTransportError(
                "The realtime server did not answer in time"
            ) from err
        except LrtmTransportError as err:
            if published:
                raise LrtmUnconfirmedError from err
            raise

    async def _open(self, session: Session, opened: list[LrtmSession]) -> LrtmSession:
        """Open a connection and connect as the app. `opened` gets it for the close."""
        try:
            ws = await self._websession.ws_connect(self._url)
        except (aiohttp.ClientError, ConnectionError) as err:
            raise LrtmTransportError("Could not reach the realtime server") from err
        lrtm = LrtmSession(ws, write_limit=CLOSE_LIMIT)
        opened.append(lrtm)
        await lrtm.connect(
            {
                "platform": PLATFORM,
                "appConnectData": {
                    "token": session.token,
                    "userId": session.user_id,
                },
            },
            STEP_LIMIT,
        )
        return lrtm

    async def _close(self, sessions: list[LrtmSession], deadline: float) -> None:
        """Close the connections, and wait for that until `deadline` at most.

        A close that takes longer goes on in the background.
        """
        if not sessions:
            return
        loop = asyncio.get_running_loop()
        task = loop.create_task(_close_all(sessions))
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)
        budget = min(CLOSE_LIMIT, deadline - loop.time())
        if budget > 0:
            await asyncio.wait({task}, timeout=budget)


async def _close_all(sessions: list[LrtmSession]) -> None:
    await asyncio.gather(*(lrtm.close() for lrtm in sessions))
