"""Tests for the SiiPet realtime control lane."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp
import pytest

from custom_components.siipet.api import Session
from custom_components.siipet.api.lrtm import (
    LrtmControl,
    LrtmError,
    LrtmSession,
    device_command,
    encode_command,
)

from ..common import make_token

TOKEN = make_token("user-0001")
SESSION = Session(TOKEN, 1_900_000_000_000)


class FakeMessage:
    """A stand-in for an aiohttp WSMessage."""

    def __init__(self, data: str, kind: aiohttp.WSMsgType = aiohttp.WSMsgType.TEXT):
        self.type = kind
        self.data = data


class FakeWS:
    """A fake WebSocket that answers each command by id, or runs a scripted responder."""

    def __init__(self, responder: Any = None, auto: bool = True) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._auto = auto
        self._responder = responder
        self._queue: asyncio.Queue[FakeMessage | None] = asyncio.Queue()

    async def send_str(self, data: str) -> None:
        if self.closed:
            raise ConnectionError("closed")
        self.sent.append(data)
        if self._responder is not None:
            await self._responder(self, data)
            return
        if not self._auto:
            return
        frame = json.loads(data)
        if "id" in frame:
            method = next(k for k in frame if k != "id")
            body = {"client": "c-1"} if method == "connect" else {}
            self.feed(json.dumps({"id": frame["id"], method: body}))

    def feed(self, data: str) -> None:
        self._queue.put_nowait(FakeMessage(data))

    def error(self) -> None:
        self._queue.put_nowait(FakeMessage("", aiohttp.WSMsgType.ERROR))

    async def close(self) -> None:
        self.closed = True
        self._queue.put_nowait(None)

    def __aiter__(self) -> FakeWS:
        return self

    async def __anext__(self) -> FakeMessage:
        message = await self._queue.get()
        if message is None:
            raise StopAsyncIteration
        return message


def test_encode_command() -> None:
    """A command is a compact JSON object with the id and one method."""
    assert encode_command(3, "publish", {"channel": "c"}) == (
        '{"id":3,"publish":{"channel":"c"}}'
    )


def test_device_command_shape() -> None:
    """The device envelope carries the command name, device id, and a session id."""
    msg = device_command("SN1", "config.fillLight", {"level": 2})
    assert msg["request"]["header"]["name"] == "config.fillLight"
    assert msg["request"]["header"]["deviceId"] == "SN1"
    assert msg["request"]["payload"] == {"level": 2}
    assert len(msg["request"]["header"]["sessionId"]) >= 8


async def test_connect_and_publish() -> None:
    """Connect and publish send the right frames and return the replies."""
    ws = FakeWS()
    session = LrtmSession(ws)
    reply = await session.connect({"platform": 1}, 5)
    assert reply == {"client": "c-1"}
    await session.publish("device:joy1:SN1:app:dev:request", {"x": 1}, 5)
    sent = [json.loads(frame) for frame in ws.sent]
    assert sent[0]["connect"]["data"] == {"platform": 1}
    assert sent[1]["publish"]["channel"] == "device:joy1:SN1:app:dev:request"
    assert sent[1]["id"] != sent[0]["id"]
    await session.close()


async def test_server_ping_is_answered() -> None:
    """A lone empty object is a ping; the session replies with an empty object."""
    ws = FakeWS()
    session = LrtmSession(ws)
    await session.connect({}, 5)
    ws.feed("{}")
    await asyncio.sleep(0)
    assert "{}" in ws.sent
    await session.close()


async def test_error_reply_raises() -> None:
    """An error reply raises LrtmError."""

    async def responder(ws: FakeWS, data: str) -> None:
        frame = json.loads(data)
        ws.feed(
            json.dumps({"id": frame["id"], "error": {"code": 103, "message": "no"}})
        )

    ws = FakeWS(responder=responder)
    session = LrtmSession(ws)
    with pytest.raises(LrtmError, match="103"):
        await session.connect({}, 5)
    await session.close()


async def test_closed_connection_fails_pending() -> None:
    """A closed socket fails a waiting request."""

    async def responder(ws: FakeWS, data: str) -> None:
        ws.error()

    ws = FakeWS(responder=responder)
    session = LrtmSession(ws)
    with pytest.raises(LrtmError):
        await session.connect({}, 5)


async def test_push_goes_to_handler() -> None:
    """A publication push is delivered to on_push."""
    seen: list[tuple[str, dict]] = []
    ws = FakeWS()
    session = LrtmSession(ws, lambda ch, data: seen.append((ch, data)))
    await session.connect({}, 5)
    ws.feed(json.dumps({"push": {"channel": "ch1", "pub": {"data": {"hi": 1}}}}))
    await asyncio.sleep(0)
    assert seen == [("ch1", {"hi": 1})]
    await session.close()


class FakeClientSession:
    """A websession whose ws_connect returns a prepared FakeWS."""

    def __init__(self, ws: FakeWS | None, exc: Exception | None = None) -> None:
        self._ws = ws
        self._exc = exc
        self.url: str | None = None

    async def ws_connect(self, url: str, **_: Any) -> FakeWS:
        self.url = url
        if self._exc is not None:
            raise self._exc
        assert self._ws is not None
        return self._ws


async def test_control_send() -> None:
    """A control command connects, publishes the device envelope, and closes."""
    ws = FakeWS()
    control = LrtmControl(FakeClientSession(ws), lambda: SESSION)
    await control.send("SN1", "config.fillLight", {"level": 3})
    frames = [json.loads(frame) for frame in ws.sent]
    connect = next(f for f in frames if "connect" in f)
    publish = next(f for f in frames if "publish" in f)
    assert connect["connect"]["data"]["appConnectData"]["token"] == TOKEN
    assert connect["connect"]["data"]["appConnectData"]["userId"] == "user-0001"
    assert publish["publish"]["channel"] == "device:joy1:SN1:app:dev:request"
    req = publish["publish"]["data"]["request"]
    assert req["header"]["name"] == "config.fillLight"
    assert req["payload"] == {"level": 3}
    assert ws.closed


async def test_control_without_session() -> None:
    """With no session, send raises before it opens a socket."""
    control = LrtmControl(FakeClientSession(None), lambda: None)
    with pytest.raises(LrtmError, match="session"):
        await control.send("SN1", "config.fillLight", {"level": 1})


async def test_control_connect_failure() -> None:
    """A socket that will not open raises LrtmError."""
    control = LrtmControl(
        FakeClientSession(None, aiohttp.ClientError()), lambda: SESSION
    )
    with pytest.raises(LrtmError, match="reach"):
        await control.send("SN1", "config.fillLight", {"level": 1})
