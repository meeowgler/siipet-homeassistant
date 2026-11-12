"""Tests for the SiiPet realtime control lane."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
import pytest

from custom_components.siipet.api import (
    LrtmServerError,
    LrtmTransportError,
    LrtmUnconfirmedError,
    Session,
    SiiPetAuthError,
)
from custom_components.siipet.api.lrtm import (
    LrtmClient,
    LrtmSession,
    device_command,
    encode_command,
)

from ..common import make_token


@pytest.fixture(autouse=True)
def frozen_time() -> None:
    """Keep the real clock. The timeouts wait on asyncio timers."""


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
    assert sent[0]["connect"]["name"] == "java"
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
    with pytest.raises(LrtmServerError):
        await session.connect({}, 5)
    await session.close()


async def test_closed_connection_fails_pending() -> None:
    """A closed socket fails a waiting request."""

    async def responder(ws: FakeWS, data: str) -> None:
        ws.error()

    ws = FakeWS(responder=responder)
    session = LrtmSession(ws)
    with pytest.raises(LrtmTransportError):
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
    """A websession whose ws_connect returns the next prepared FakeWS."""

    def __init__(self, sockets: list[FakeWS], exc: Exception | None = None) -> None:
        self._sockets = sockets
        self._exc = exc
        self.protocols: list[Any] = []

    async def ws_connect(self, url: str, **kwargs: Any) -> FakeWS:
        self.protocols.append(kwargs.get("protocols"))
        if self._exc is not None:
            raise self._exc
        return self._sockets.pop(0)


def _client(
    websession: FakeClientSession, recover: AsyncMock | None = None
) -> LrtmClient:
    return LrtmClient(
        websession,
        AsyncMock(return_value=SESSION),
        recover or AsyncMock(side_effect=SiiPetAuthError("no password")),
    )


def _reject_connect(code: int) -> Any:
    async def responder(ws: FakeWS, data: str) -> None:
        frame = json.loads(data)
        if "connect" in frame:
            ws.feed(
                json.dumps(
                    {"id": frame["id"], "error": {"code": code, "message": "x SN1"}}
                )
            )

    return responder


async def test_client_sends_like_the_app() -> None:
    """The command connects as the app, publishes the device envelope, and closes."""
    ws = FakeWS()
    websession = FakeClientSession([ws])
    await _client(websession).send("SN1", "config.fillLight", {"level": 3}, limit=5)
    connect, publish = (json.loads(frame) for frame in ws.sent)
    assert connect["connect"] == {
        "name": "java",
        "data": {
            "platform": 1,
            "appConnectData": {"token": TOKEN, "userId": "user-0001"},
        },
    }
    assert publish["publish"]["channel"] == "device:joy1:SN1:app:dev:request"
    request = publish["publish"]["data"]["request"]
    assert request["header"]["name"] == "config.fillLight"
    assert request["payload"] == {"level": 3}
    assert websession.protocols == [None]
    assert ws.closed


async def test_auth_error_recovers_once() -> None:
    """An expired token signs in again through the client, then sends once more."""
    first = FakeWS(responder=_reject_connect(401))
    second = FakeWS()
    fresh = Session(make_token("user-0001"), 1_900_000_000_001)
    recover = AsyncMock(return_value=fresh)
    await _client(FakeClientSession([first, second]), recover).send(
        "SN1", "config.privacyMode", {"active": True}, limit=5
    )
    recover.assert_awaited_once_with(SESSION)
    assert any("publish" in json.loads(frame) for frame in second.sent)


async def test_auth_error_without_recovery() -> None:
    """When the client cannot sign in again, the auth error goes to the caller."""
    ws = FakeWS(responder=_reject_connect(401))
    with pytest.raises(SiiPetAuthError):
        await _client(FakeClientSession([ws])).send(
            "SN1", "config.privacyMode", {"active": True}, limit=5
        )


async def test_server_error_keeps_only_the_code() -> None:
    """Another error code is a server error without the server's message."""
    ws = FakeWS(responder=_reject_connect(103))
    with pytest.raises(LrtmServerError) as err:
        await _client(FakeClientSession([ws])).send(
            "SN1", "config.privacyMode", {"active": True}, limit=5
        )
    assert err.value.code == 103
    assert "SN1" not in str(err.value)


@pytest.mark.parametrize("code", [101, 109])
async def test_other_token_codes_are_server_errors(code: int) -> None:
    """Only the 401 that the server sends is an auth error."""
    ws = FakeWS(responder=_reject_connect(code))
    with pytest.raises(LrtmServerError) as err:
        await _client(FakeClientSession([ws])).send(
            "SN1", "config.privacyMode", {"active": True}, limit=5
        )
    assert err.value.code == code


async def test_unreachable_server() -> None:
    """A socket that will not open is a transport error."""
    websession = FakeClientSession([], exc=aiohttp.ClientError())
    with pytest.raises(LrtmTransportError, match="reach"):
        await _client(websession).send("SN1", "config.fillLight", {}, limit=5)


async def _closes_done(client: LrtmClient) -> None:
    """Wait for the closes that went on after `send` returned."""
    await asyncio.gather(*list(client._closing))
    await asyncio.sleep(0)
    assert not client._closing


async def test_no_answer_in_time() -> None:
    """A server that never answers is a transport error after the limit."""
    ws = FakeWS(auto=False)
    client = _client(FakeClientSession([ws]))
    with pytest.raises(LrtmTransportError) as err:
        await client.send("SN1", "config.fillLight", {}, limit=0.1)
    # The connect was not answered, so nothing was published.
    assert not isinstance(err.value, LrtmUnconfirmedError)
    await _closes_done(client)
    assert ws.closed


class StuckCloseWS(FakeWS):
    """A FakeWS whose close waits until the test sets `release`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.release = asyncio.Event()

    async def close(self) -> None:
        self.closed = True
        await self.release.wait()
        self._queue.put_nowait(None)


async def test_stalled_close_goes_on_after_the_limit() -> None:
    """A socket that does not close keeps no command past its limit."""
    ws = StuckCloseWS()
    client = _client(FakeClientSession([ws]))
    loop = asyncio.get_running_loop()
    start = loop.time()
    await client.send("SN1", "config.fillLight", {}, limit=0.1)
    assert loop.time() - start < 0.25
    assert len(client._closing) == 1
    ws.release.set()
    await _closes_done(client)


async def test_refused_publish_with_a_slow_close() -> None:
    """A refusal that came before the limit stays a refusal."""

    async def refuse(ws: FakeWS) -> None:
        frame = json.loads(ws.sent[-1])
        ws.feed(json.dumps({"id": frame["id"], "error": {"code": 103}}))

    ws = StuckCloseWS(responder=_answer(refuse))
    client = _client(FakeClientSession([ws]))
    with pytest.raises(LrtmServerError) as err:
        await client.send("SN1", "config.fillLight", {}, limit=0.1)
    assert err.value.code == 103
    ws.release.set()
    await _closes_done(client)


async def test_canceled_close_stops_the_reader() -> None:
    """A close canceled while the socket closes still stops the reader."""
    ws = StuckCloseWS()
    session = LrtmSession(ws)
    await session.connect({}, 5)
    closing = asyncio.ensure_future(session.close())
    await asyncio.sleep(0)
    closing.cancel()
    with suppress(asyncio.CancelledError):
        await closing
    assert session._task is not None
    assert session._task.done()


def _publishes(ws: FakeWS) -> list[dict[str, Any]]:
    return [frame for frame in map(json.loads, ws.sent) if "publish" in frame]


async def test_unwanted_command_is_not_published() -> None:
    """A command that is no longer wanted when the connection is ready is not published."""
    ws = FakeWS()
    client = _client(FakeClientSession([ws]))
    with pytest.raises(LrtmTransportError) as err:
        await client.send(
            "SN1", "config.fillLight", {}, limit=5, still_wanted=lambda: False
        )
    assert not isinstance(err.value, LrtmUnconfirmedError)
    assert _publishes(ws) == []
    assert ws.closed


async def test_unwanted_command_is_not_published_after_a_new_sign_in() -> None:
    """The check runs again before the publish that follows a new sign-in."""
    first = FakeWS(responder=_reject_connect(401))
    second = FakeWS()
    wanted = True
    fresh = Session(make_token("user-0001"), 1_900_000_000_001)

    async def recover(_failed: Session) -> Session:
        nonlocal wanted
        wanted = False
        return fresh

    client = _client(FakeClientSession([first, second]), AsyncMock(side_effect=recover))
    with pytest.raises(LrtmTransportError) as err:
        await client.send(
            "SN1", "config.fillLight", {}, limit=5, still_wanted=lambda: wanted
        )
    assert not isinstance(err.value, LrtmUnconfirmedError)
    assert _publishes(first) == []
    assert _publishes(second) == []
    assert second.closed


def _answer(publish: Any) -> Any:
    """Answer the connect, and run `publish` for the publish frame."""

    async def responder(ws: FakeWS, data: str) -> None:
        frame = json.loads(data)
        if "connect" in frame:
            ws.feed(json.dumps({"id": frame["id"], "connect": {"client": "c-1"}}))
        elif "publish" in frame:
            await publish(ws)

    return responder


async def _no_answer(ws: FakeWS) -> None:
    pass


async def _close(ws: FakeWS) -> None:
    ws.error()


@pytest.mark.parametrize("publish", [_no_answer, _close])
async def test_publish_without_answer_is_unconfirmed(publish: Any) -> None:
    """A publish that went out without an answer can still reach the camera."""
    ws = FakeWS(responder=_answer(publish))
    client = _client(FakeClientSession([ws]))
    with pytest.raises(LrtmUnconfirmedError):
        await client.send("SN1", "config.fillLight", {}, limit=0.2)
    await _closes_done(client)
    assert ws.closed


async def test_publish_not_written_is_not_sent() -> None:
    """A connection that closed before the publish frame sent nothing."""

    async def close_after_connect(ws: FakeWS, data: str) -> None:
        frame = json.loads(data)
        if "connect" in frame:
            ws.feed(json.dumps({"id": frame["id"], "connect": {"client": "c-1"}}))
            ws.error()

    ws = FakeWS(responder=close_after_connect)
    with pytest.raises(LrtmTransportError) as err:
        await _client(FakeClientSession([ws])).send(
            "SN1", "config.fillLight", {}, limit=5
        )
    assert not isinstance(err.value, LrtmUnconfirmedError)
    assert _publishes(ws) == []


async def _fail(ws: FakeWS) -> None:
    raise ConnectionError("reset")


async def _stall(ws: FakeWS) -> None:
    await asyncio.sleep(10)


@pytest.mark.parametrize("publish", [_fail, _stall])
async def test_failed_publish_write_is_unconfirmed(publish: Any) -> None:
    """A publish frame whose write failed or stalled can still reach the camera."""
    ws = FakeWS(responder=_answer(publish))
    client = _client(FakeClientSession([ws]))
    with pytest.raises(LrtmUnconfirmedError):
        await client.send("SN1", "config.fillLight", {}, limit=0.2)
    assert len(_publishes(ws)) == 1
    await _closes_done(client)


async def test_refused_publish_then_unreachable_is_not_sent() -> None:
    """After a refused publish and a new sign-in, a retry that cannot connect sent nothing."""

    async def refuse(ws: FakeWS) -> None:
        frame = json.loads(ws.sent[-1])
        ws.feed(json.dumps({"id": frame["id"], "error": {"code": 401}}))

    first = FakeWS(responder=_answer(refuse))

    class Websession(FakeClientSession):
        async def ws_connect(self, url: str, **kwargs: Any) -> FakeWS:
            if self._sockets:
                return self._sockets.pop(0)
            raise aiohttp.ClientError

    fresh = Session(make_token("user-0001"), 1_900_000_000_001)
    client = _client(Websession([first]), AsyncMock(return_value=fresh))
    with pytest.raises(LrtmTransportError) as err:
        await client.send("SN1", "config.privacyMode", {"active": True}, limit=5)
    assert not isinstance(err.value, LrtmUnconfirmedError)


async def test_cameras_do_not_wait_for_each_other() -> None:
    """Two cameras send at the same time."""
    slow = FakeWS(auto=False)
    fast = FakeWS()
    client = _client(FakeClientSession([slow, fast]))
    first = asyncio.create_task(client.send("SN1", "config.fillLight", {}, limit=1))
    await asyncio.sleep(0)
    await client.send("SN2", "config.fillLight", {}, limit=1)
    first.cancel()
    with suppress(asyncio.CancelledError):
        await first
