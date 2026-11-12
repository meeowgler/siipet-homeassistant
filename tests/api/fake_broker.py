"""A fake AWS IoT broker for the MQTT and shadow link tests.

It runs on an aiohttp test server and speaks the MQTT codec of the integration.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import json
import struct
from typing import Any

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

from custom_components.siipet.api.mqtt import (
    CONNACK,
    CONNECT,
    DISCONNECT,
    PINGREQ,
    PINGRESP,
    PUBLISH,
    SUBACK,
    SUBACK_FAILURE,
    SUBSCRIBE,
    Packet,
    PacketReader,
    encode_length,
    encode_publish,
    parse_publish,
)


def _read_string(body: bytes, start: int) -> tuple[str, int]:
    (size,) = struct.unpack("!H", body[start : start + 2])
    end = start + 2 + size
    return body[start + 2 : end].decode(), end


def _serial(topic: str) -> str:
    """Return the thing name of a `$aws/things/<sn>/...` topic."""
    return topic.split("/")[2]


@dataclass
class BrokerConnection:
    """One client connection that the broker accepted."""

    ws: web.WebSocketResponse
    client_id: str | None = None
    keepalive: int | None = None
    subscriptions: set[str] = field(default_factory=set)
    disconnected: bool = False

    async def send(self, kind: int, body: bytes) -> None:
        await self.ws.send_bytes(bytes([kind << 4]) + encode_length(len(body)) + body)


@dataclass
class FakeBroker:
    """Answers shadow reads from `documents`, keyed by `<sn>/<shadow name>`."""

    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    connack_code: int = 0
    answer_ping: bool = True
    deny_subscribe: set[str] = field(default_factory=set)
    deny_topics: set[str] = field(default_factory=set)
    close_on_get: set[str] = field(default_factory=set)
    close_on_get_budget: dict[str, int] = field(default_factory=dict)
    reject_get: set[str] = field(default_factory=set)
    silent_get: set[str] = field(default_factory=set)
    silent_subscribe: set[str] = field(default_factory=set)
    silent_topics: set[str] = field(default_factory=set)
    close_on_subscribe: set[str] = field(default_factory=set)
    reject_update: set[str] = field(default_factory=set)
    silent_update: set[str] = field(default_factory=set)
    close_on_update: set[str] = field(default_factory=set)
    # Subscriptions that one connection may hold. AWS IoT refuses a topic past the limit.
    max_subscriptions: int | None = None
    handshake_status: int | None = None
    connections: list[BrokerConnection] = field(default_factory=list)
    gets: list[str] = field(default_factory=list)
    updates: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def handler(self, request: web.Request) -> web.StreamResponse:
        if self.handshake_status is not None:
            return web.Response(status=self.handshake_status)
        ws = web.WebSocketResponse(protocols=("mqtt",))
        await ws.prepare(request)
        connection = BrokerConnection(ws)
        self.connections.append(connection)
        reader = PacketReader()
        async for message in ws:
            if message.type is not WSMsgType.BINARY:
                continue
            for packet in reader.feed(message.data):
                if not await self._handle(connection, packet):
                    await ws.close()
                    return ws
        return ws

    async def push(self, topic: str, document: dict[str, Any]) -> None:
        """Send a message to each connection that subscribed to `topic`."""
        for connection in self.connections:
            if topic in connection.subscriptions and not connection.ws.closed:
                await connection.ws.send_bytes(
                    encode_publish(topic, json.dumps(document).encode())
                )

    async def close_all(self) -> None:
        for connection in self.connections:
            await connection.ws.close()

    async def _handle(self, connection: BrokerConnection, packet: Packet) -> bool:
        if packet.kind == CONNECT:
            _name, index = _read_string(packet.body, 0)
            (connection.keepalive,) = struct.unpack(
                "!H", packet.body[index + 2 : index + 4]
            )
            connection.client_id, _end = _read_string(packet.body, index + 4)
            await connection.send(CONNACK, bytes([0, self.connack_code]))
            return self.connack_code == 0
        if packet.kind == SUBSCRIBE:
            packet_id = packet.body[:2]
            topics: list[str] = []
            index = 2
            while index < len(packet.body):
                topic, index = _read_string(packet.body, index)
                index += 1
                topics.append(topic)
            if any(_serial(topic) in self.silent_subscribe for topic in topics):
                return True
            if any(topic in self.silent_topics for topic in topics):
                return True
            if any(topic in self.close_on_subscribe for topic in topics):
                return False
            codes = bytearray()
            for topic in topics:
                if (
                    _serial(topic) in self.deny_subscribe
                    or topic in self.deny_topics
                    or self._over_limit(connection, topic)
                ):
                    codes.append(SUBACK_FAILURE)
                else:
                    connection.subscriptions.add(topic)
                    codes.append(0)
            await connection.send(SUBACK, packet_id + bytes(codes))
            return True
        if packet.kind == PUBLISH:
            topic, payload = parse_publish(packet)
            if topic.endswith("/update"):
                return await self._update(connection, topic, payload)
            return await self._get(connection, topic)
        if packet.kind == PINGREQ:
            if self.answer_ping:
                await connection.send(PINGRESP, b"")
            return True
        if packet.kind == DISCONNECT:
            connection.disconnected = True
            return False
        return True

    def _over_limit(self, connection: BrokerConnection, topic: str) -> bool:
        return (
            self.max_subscriptions is not None
            and topic not in connection.subscriptions
            and len(connection.subscriptions) >= self.max_subscriptions
        )

    async def _get(self, connection: BrokerConnection, topic: str) -> bool:
        if not topic.endswith("/get"):
            return True
        self.gets.append(topic)
        sn = _serial(topic)
        if sn in self.close_on_get:
            return False
        if self.close_on_get_budget.get(sn, 0) > 0:
            self.close_on_get_budget[sn] -= 1
            return False
        if sn in self.silent_get:
            return True
        shadow = topic.split("/")[5]
        document = self.documents.get(f"{sn}/{shadow}")
        if sn in self.reject_get or document is None:
            reply = f"{topic}/rejected"
            payload = {
                "code": 404,
                "message": f"No shadow exists with name: '{shadow}'",
            }
        else:
            reply = f"{topic}/accepted"
            payload = document
        if reply in connection.subscriptions:
            await connection.ws.send_bytes(
                encode_publish(reply, json.dumps(payload).encode())
            )
        return True

    async def _update(
        self, connection: BrokerConnection, topic: str, payload: bytes
    ) -> bool:
        body = json.loads(payload)
        self.updates.append((topic, body))
        sn = _serial(topic)
        if sn in self.close_on_update:
            return False
        if sn in self.silent_update:
            return True
        token = body.get("clientToken")
        if sn in self.reject_update:
            reply = f"{topic}/rejected"
            answer: dict[str, Any] = {
                "code": 403,
                "message": f"Not authorized for {topic}",
                "clientToken": token,
            }
        else:
            reply = f"{topic}/accepted"
            answer = {"state": body["state"], "version": 7, "clientToken": token}
        if reply in connection.subscriptions:
            await connection.ws.send_bytes(
                encode_publish(reply, json.dumps(answer).encode())
            )
        return True


@asynccontextmanager
async def run_broker(broker: FakeBroker) -> AsyncIterator[str]:
    """Serve the broker on localhost and yield its WebSocket URL."""
    app = web.Application()
    app.router.add_get("/mqtt", broker.handler)
    server = TestServer(app)
    # The access log of the broker shows the signed query of the test URL.
    # Without it, the privacy checks see only what the integration logs.
    await server.start_server(access_log=None)
    try:
        yield f"ws://{server.host}:{server.port}/mqtt"
    finally:
        await broker.close_all()
        await server.close()
