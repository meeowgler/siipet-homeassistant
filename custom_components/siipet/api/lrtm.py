"""The SiiPet realtime control lane (LRTM), on a Centrifugo WebSocket.

The app changes a camera setting by publishing a command to the camera's
request channel on a Centrifugo server. The protocol is the JSON protocol:
each text frame is one or more newline-separated JSON objects. A command is
`{"id": n, "<method>": {...}}` and its reply is `{"id": n, "<method>": {...}}`
or `{"id": n, "error": {...}}`. A lone `{}` from the server is a ping, answered
with `{}`. This module speaks only the `connect` and `publish` methods, which
is all a one-shot control needs, using only aiohttp and the standard library.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
import json
import logging
from typing import Any
import uuid

import aiohttp

from .auth import Session
from .errors import SiiPetError

_LOGGER = logging.getLogger(__name__)

LRTM_URL = "wss://wss-siipet.linkric.com/connection/websocket"
# Per-camera channel the app publishes commands to.
REQUEST_CHANNEL = "device:joy1:{sn}:app:dev:request"
PROTOCOL = ("centrifuge-protocol-v2",)
CONNECT_TIMEOUT = 15.0
COMMAND_TIMEOUT = 15.0


class LrtmError(SiiPetError):
    """The realtime connection failed, timed out, closed, or returned an error."""


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
    LrtmError when the connection closes.
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
            "connect", {"name": "ha-siipet", "data": data}, limit
        )

    async def publish(
        self, channel: str, data: dict[str, Any], limit: float
    ) -> dict[str, Any]:
        """Publish to a channel and return the publish reply."""
        return await self._request("publish", {"channel": channel, "data": data}, limit)

    async def close(self) -> None:
        """Close the socket and stop the reader."""
        self._mark_closed()
        with suppress(TimeoutError, aiohttp.ClientError, ConnectionError):
            async with asyncio.timeout(self._write_limit):
                await self._ws.close()
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _request(
        self, method: str, params: dict[str, Any], limit: float
    ) -> dict[str, Any]:
        self._command_id += 1
        command_id = self._command_id
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._waiters[command_id] = future
        try:
            async with asyncio.timeout(limit):
                await self._send(encode_command(command_id, method, params))
                return await future
        except TimeoutError as err:
            raise LrtmError(f"The {method} command was not answered in time") from err
        finally:
            self._waiters.pop(command_id, None)
            if not future.done():
                future.cancel()

    async def _send(self, frame: str) -> None:
        if self._closed.is_set():
            raise LrtmError("The connection is closed")
        try:
            await self._ws.send_str(frame)
        except (aiohttp.ClientError, ConnectionError) as err:
            raise LrtmError("Could not send to the realtime server") from err

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
            code, message = error.get("code"), error.get("message", "")
            future.set_exception(LrtmError(f"Realtime error {code}: {message}"))
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
                future.set_exception(LrtmError("The connection closed"))


class LrtmControl:
    """Send one control command to a camera over a short-lived realtime connection.

    It opens a connection, authenticates with the account's current session
    (the same token the REST and shadow lanes use), publishes the command, and
    closes. Opening per command keeps the lane idle between changes.
    """

    def __init__(
        self,
        websession: aiohttp.ClientSession,
        session: Callable[[], Session | None],
        *,
        url: str = LRTM_URL,
    ) -> None:
        """Create the control client. `session` returns the live session."""
        self._websession = websession
        self._session = session
        self._url = url
        self._lock = asyncio.Lock()

    async def send(self, sn: str, command: str, payload: dict[str, Any]) -> None:
        """Send `command` with `payload` to the camera. Raise LrtmError on failure."""
        session = self._session()
        if session is None:
            raise LrtmError("No session. Sign in first.")
        auth = {"token": session.token, "userId": session.user_id}
        connect_data = {"platform": 1, "appConnectData": auth}
        # One command at a time keeps the per-command connection simple.
        async with self._lock:
            try:
                async with asyncio.timeout(CONNECT_TIMEOUT):
                    ws = await self._websession.ws_connect(
                        self._url, protocols=PROTOCOL
                    )
            except (aiohttp.ClientError, ConnectionError, TimeoutError) as err:
                raise LrtmError("Could not reach the realtime server") from err
            lrtm = LrtmSession(ws)
            try:
                await lrtm.connect(connect_data, CONNECT_TIMEOUT)
                await lrtm.publish(
                    REQUEST_CHANNEL.format(sn=sn),
                    device_command(sn, command, payload),
                    COMMAND_TIMEOUT,
                )
            finally:
                await lrtm.close()
