"""MQTT 3.1.1 on a WebSocket, with only the packets that the shadow link needs.

The session sends and subscribes at QoS 0, so it never sends PUBACK.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
import logging
import struct

import aiohttp

from .errors import SiiPetError

_LOGGER = logging.getLogger(__name__)

CONNECT = 1
CONNACK = 2
PUBLISH = 3
SUBSCRIBE = 8
SUBACK = 9
PINGREQ = 12
PINGRESP = 13
DISCONNECT = 14

PROTOCOL_LEVEL = 4
CLEAN_SESSION = 0x02
SUBACK_FAILURE = 0x80
MAX_LENGTH = 268_435_455


class MqttError(SiiPetError):
    """The MQTT connection failed, timed out, or closed."""


class MqttRefused(MqttError):
    """The broker refused the connection with a non-zero CONNACK code."""


class MqttNotSent(MqttError):
    """The message was not sent because the connection is closed."""


@dataclass(frozen=True, slots=True)
class Packet:
    """One MQTT control packet: its type, the low bits of its first byte, its body."""

    kind: int
    flags: int
    body: bytes


def encode_length(length: int) -> bytes:
    """Encode a remaining length with the MQTT variable-length scheme."""
    if not 0 <= length <= MAX_LENGTH:
        raise ValueError("The MQTT packet is too long")
    out = bytearray()
    while True:
        byte, length = length % 128, length // 128
        out.append(byte | 0x80 if length else byte)
        if not length:
            return bytes(out)


def _string(value: str) -> bytes:
    raw = value.encode()
    return struct.pack("!H", len(raw)) + raw


def _packet(kind: int, flags: int, body: bytes) -> bytes:
    return bytes([kind << 4 | flags]) + encode_length(len(body)) + body


def encode_connect(client_id: str, keepalive: int) -> bytes:
    """A CONNECT with a clean session, no user name, and no password."""
    body = (
        _string("MQTT")
        + bytes([PROTOCOL_LEVEL, CLEAN_SESSION])
        + struct.pack("!H", keepalive)
        + _string(client_id)
    )
    return _packet(CONNECT, 0, body)


def encode_subscribe(packet_id: int, topics: Sequence[str]) -> bytes:
    """A SUBSCRIBE that asks for QoS 0 on each topic."""
    body = struct.pack("!H", packet_id) + b"".join(
        _string(topic) + b"\x00" for topic in topics
    )
    return _packet(SUBSCRIBE, 0b0010, body)


def encode_publish(topic: str, payload: bytes) -> bytes:
    """A QoS 0 PUBLISH. It has no packet id."""
    return _packet(PUBLISH, 0, _string(topic) + payload)


PINGREQ_PACKET = _packet(PINGREQ, 0, b"")
DISCONNECT_PACKET = _packet(DISCONNECT, 0, b"")


def parse_connack(packet: Packet) -> int:
    """Return the return code of a CONNACK. Zero means accepted."""
    if len(packet.body) != 2:
        raise MqttError("Malformed CONNACK")
    return packet.body[1]


def parse_suback(packet: Packet) -> tuple[int, tuple[int, ...]]:
    """Return the packet id and the return code of each topic."""
    if len(packet.body) < 3:
        raise MqttError("Malformed SUBACK")
    return struct.unpack("!H", packet.body[:2])[0], tuple(packet.body[2:])


def parse_publish(packet: Packet) -> tuple[str, bytes]:
    """Return the topic and the payload. A QoS 1 or 2 packet id is skipped."""
    body = packet.body
    if len(body) < 2:
        raise MqttError("Malformed PUBLISH")
    end = 2 + struct.unpack("!H", body[:2])[0]
    start = end + 2 if (packet.flags >> 1) & 0b11 else end
    if len(body) < start:
        raise MqttError("Malformed PUBLISH")
    try:
        topic = body[2:end].decode()
    except UnicodeDecodeError as err:
        raise MqttError("Malformed PUBLISH topic") from err
    return topic, body[start:]


class PacketReader:
    """Split received bytes into packets. A frame can hold part of a packet or many."""

    def __init__(self) -> None:
        """Start with an empty buffer."""
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Packet]:
        """Add bytes and return the packets that are now complete."""
        self._buffer += data
        packets: list[Packet] = []
        while (packet := self._next()) is not None:
            packets.append(packet)
        return packets

    def _next(self) -> Packet | None:
        buffer = self._buffer
        length = 0
        index = 1
        while True:
            if index >= len(buffer):
                return None
            byte = buffer[index]
            length += (byte & 0x7F) << (7 * (index - 1))
            index += 1
            if not byte & 0x80:
                break
            if index > 4:
                raise MqttError("Malformed MQTT remaining length")
        end = index + length
        if len(buffer) < end:
            return None
        packet = Packet(buffer[0] >> 4, buffer[0] & 0x0F, bytes(buffer[index:end]))
        del buffer[:end]
        return packet


class MqttSession:
    """One MQTT connection on an open WebSocket.

    A task reads packets until the socket closes. Published messages go to
    `on_message`. Requests that wait for an answer fail with MqttError when
    the connection closes. A write that takes longer than `write_limit`
    seconds is given up.
    """

    def __init__(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        on_message: Callable[[str, bytes], None],
        *,
        write_limit: float = 10.0,
    ) -> None:
        """Wrap an open WebSocket. Call `connect` before anything else."""
        self._ws = ws
        self._on_message = on_message
        self._write_limit = write_limit
        self._reader = PacketReader()
        self._waiters: dict[tuple[int, int], asyncio.Future[Packet]] = {}
        self._closed = asyncio.Event()
        self._closed_here = False
        self._task: asyncio.Task[None] | None = None
        self._packet_id = 0

    @property
    def closed(self) -> bool:
        """True after the connection closed."""
        return self._closed.is_set()

    @property
    def dropped(self) -> bool:
        """True when the connection closed before any call to `close`."""
        return self._closed.is_set() and not self._closed_here

    async def connect(self, client_id: str, keepalive: int, limit: float) -> None:
        """Send CONNECT and wait for an accepting CONNACK."""
        self._task = asyncio.get_running_loop().create_task(self._read_loop())
        packet = await self._request(
            encode_connect(client_id, keepalive), (CONNACK, 0), limit
        )
        code = parse_connack(packet)
        if code:
            raise MqttRefused(f"The broker refused the connection with code {code}")

    async def subscribe(self, topics: Sequence[str], limit: float) -> list[bool]:
        """Subscribe at QoS 0. Return for each topic whether the broker granted it."""
        self._packet_id = self._packet_id % 0xFFFF + 1
        packet_id = self._packet_id
        packet = await self._request(
            encode_subscribe(packet_id, topics), (SUBACK, packet_id), limit
        )
        _packet_id, codes = parse_suback(packet)
        if len(codes) != len(topics):
            raise MqttError("The SUBACK does not match the SUBSCRIBE")
        return [code != SUBACK_FAILURE for code in codes]

    async def publish(self, topic: str, payload: bytes = b"") -> None:
        """Publish at QoS 0.

        Raise MqttNotSent when the connection is already closed, and MqttError
        when the write fails or takes too long. After a plain MqttError, the
        message can still reach the broker.
        """
        try:
            async with asyncio.timeout(self._write_limit):
                await self._send(encode_publish(topic, payload))
        except TimeoutError as err:
            raise MqttError("The broker did not take the message in time") from err

    async def ping(self, limit: float) -> None:
        """Send PINGREQ and wait for PINGRESP."""
        await self._request(PINGREQ_PACKET, (PINGRESP, 0), limit)

    async def wait_closed(self, limit: float | None = None) -> bool:
        """Wait until the connection closes or `limit` seconds pass. True when closed."""
        try:
            async with asyncio.timeout(limit):
                await self._closed.wait()
        except TimeoutError:
            return False
        return True

    async def close(self) -> None:
        """Send DISCONNECT if the connection is open, then close the socket.

        Each of the two steps gets up to the write limit.
        """
        if not self._closed.is_set():
            self._closed_here = True
            with suppress(aiohttp.ClientError, ConnectionError, TimeoutError):
                async with asyncio.timeout(self._write_limit):
                    await self._ws.send_bytes(DISCONNECT_PACKET)
        self._mark_closed()
        # When a timeout cancels the close handshake, aiohttp drops the connection.
        with suppress(TimeoutError):
            async with asyncio.timeout(self._write_limit):
                await self._ws.close()
        task = self._task
        if task is None:
            return
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        elif not task.cancelled() and (err := task.exception()) is not None:
            # Reading the error keeps asyncio from logging it as never retrieved.
            _LOGGER.debug("The MQTT reader failed: %s", type(err).__name__)

    async def _request(self, data: bytes, key: tuple[int, int], limit: float) -> Packet:
        future: asyncio.Future[Packet] = asyncio.get_running_loop().create_future()
        self._waiters[key] = future
        try:
            async with asyncio.timeout(limit):
                await self._send(data)
                return await future
        except TimeoutError as err:
            raise MqttError("The broker did not answer in time") from err
        finally:
            self._waiters.pop(key, None)
            if not future.done():
                future.cancel()

    async def _send(self, data: bytes) -> None:
        if self._closed.is_set():
            raise MqttNotSent("The connection is closed")
        try:
            await self._ws.send_bytes(data)
        except (aiohttp.ClientError, ConnectionError) as err:
            raise MqttError("Could not send to the broker") from err

    async def _read_loop(self) -> None:
        try:
            async for message in self._ws:
                if message.type is aiohttp.WSMsgType.BINARY:
                    for packet in self._reader.feed(message.data):
                        self._dispatch(packet)
                elif message.type is aiohttp.WSMsgType.ERROR:
                    break
        except MqttError as err:
            _LOGGER.debug("Closing the MQTT connection: %s", err)
        finally:
            self._mark_closed()

    def _dispatch(self, packet: Packet) -> None:
        if packet.kind == PUBLISH:
            topic, payload = parse_publish(packet)
            self._on_message(topic, payload)
            return
        if packet.kind == SUBACK:
            key = (SUBACK, parse_suback(packet)[0])
        elif packet.kind in (CONNACK, PINGRESP):
            key = (packet.kind, 0)
        else:
            return
        future = self._waiters.get(key)
        if future is not None and not future.done():
            future.set_result(packet)

    def _mark_closed(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        for future in self._waiters.values():
            if not future.done():
                future.set_exception(MqttError("The connection closed"))
