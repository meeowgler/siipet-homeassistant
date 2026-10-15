"""Helpers shared by the SiiPet tests."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.siipet.api import CameraShadows, DayVisits, DeviceState, Visit
from custom_components.siipet.api.shadow_link import LinkStatus
from custom_components.siipet.const import CONF_MEDIA_DAYS, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
NOW = "2026-09-26T12:00:00+00:00"
TODAY = date(2026, 9, 26)
EMPTY_DAY = DayVisits((), {}, False)
SHADOWS = CameraShadows(config="fake_configInfo", system="fake_systemInfo")
DEVICE_STATE = DeviceState(
    battery=72,
    charging=False,
    privacy=False,
    fill_light=2,
    fill_light_auto=True,
    fill_light_low=True,
    fill_light_brightness=70,
    motion_level=3,
    update_mode=0,
    cloud_storage=True,
    online=True,
    firmware="1.2.3",
    rssi=-61,
    reported_at=datetime(2026, 9, 26, 11, 55, tzinfo=UTC),
)


class FakeShadowLink:
    """A stand-in for ShadowLink. Tests call its callbacks to push data."""

    keep_running = False

    def __init__(
        self,
        websession: Any,
        fetch_credentials: Callable[[], Any],
        on_state: Callable[[str, DeviceState | None], None],
        on_connection: Callable[[bool], None],
        label: Callable[[str], str],
        **_kwargs: Any,
    ) -> None:
        """Keep the arguments for the test."""
        self.fetch_credentials = fetch_credentials
        self.on_state = on_state
        self.on_connection = on_connection
        self.label = label
        self.cameras: dict[str, CameraShadows] = {}
        self.running = False
        self.stopped = False
        self._stopped_event = asyncio.Event()
        self.status = LinkStatus(
            connected=True,
            connected_since=datetime(2026, 9, 26, 11, 0, tzinfo=UTC),
            last_message=datetime(2026, 9, 26, 11, 59, tzinfo=UTC),
            cameras_with_state=1,
            denied_cameras=1,
        )

    def set_cameras(self, cameras: Mapping[str, CameraShadows]) -> None:
        self.cameras = dict(cameras)

    async def run(self) -> None:
        # By default the fake returns at once, because the tests of the local
        # media copy wait for every background task. A test that checks the
        # link runs in the background sets `keep_running`, so this waits
        # until `stop` sets the event instead, like the real link.
        self.running = True
        if self.keep_running:
            await self._stopped_event.wait()

    async def stop(self) -> None:
        self.stopped = True
        self._stopped_event.set()


def load_fixture(name: str) -> dict[str, Any]:
    """Return a JSON fixture as a dict. Fixtures hold full response envelopes."""
    return json.loads((FIXTURES / name).read_text())


def load_data(name: str) -> Any:
    """Return the `Data` part of a JSON fixture."""
    return load_fixture(name)["Data"]


def make_token(user_id: str, exp: Any = None) -> str:
    """Return an unsigned JWT with a UserId claim, and an exp claim when given."""

    def part(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    payload: dict[str, Any] = {"UserId": user_id}
    if exp is not None:
        payload["exp"] = exp
    return f"{part({'alg': 'HS256', 'typ': 'JWT'})}.{part(payload)}.sig"


def fixture_day() -> DayVisits:
    """The visits of the fixture day."""
    return DayVisits.from_api(load_data("toilet_event_day.json"))


def siipet_device_id(
    hass: HomeAssistant, entry: MockConfigEntry, identifier: str
) -> str:
    """Return the device id of a SiiPet cat or camera."""
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, identifier), entry.entry_id
    )
    assert device is not None
    return device.id


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the entry and wait for the platforms."""
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


S3 = "https://media-bucket.s3.amazonaws.com/"
VIDEO = b"video-ev-1"
COVER = b"cover-ev-1"
STOOL = b"stool-ev-1"
MIRROR_FILES = {
    "events/ev-1/video.mp4": VIDEO,
    "events/ev-1/cover.jpg": COVER,
    "events/ev-1/stool.jpg": STOOL,
    "resources/luna.jpg": b"luna",
    "resources/milo.jpg": b"milo",
}


def md5_hex(data: bytes) -> str:
    """Return the MD5 of `data` in the format of the API."""
    return hashlib.md5(data).hexdigest()


def mirror_visit(**changes: Any) -> Visit:
    """Visit ev-1 of the fixture day, with sizes and a hash that match MIRROR_FILES."""
    base = next(visit for visit in fixture_day().visits if visit.event_id == "ev-1")
    values: dict[str, Any] = {
        "video_size": len(VIDEO),
        "video_md5": md5_hex(VIDEO),
        "cover_size": len(COVER),
        "stool_size": len(STOOL),
    }
    values.update(changes)
    return replace(base, **values)


def serve_days(mock_client: AsyncMock, days: dict[date, tuple[Visit, ...]]) -> None:
    """Let the client return these visits for these days, and none for others."""
    base = fixture_day()
    mock_client.get_day.side_effect = lambda requested, **_: (
        replace(base, visits=days[requested]) if requested in days else EMPTY_DAY
    )


def mock_s3(aioclient_mock: AiohttpClientMocker, **extra: bytes) -> None:
    """Serve MIRROR_FILES and `extra` from the mocked S3 bucket."""
    for key, body in {**MIRROR_FILES, **extra}.items():
        aioclient_mock.get(S3 + key, content=body)


class StalledResponse(AiohttpClientMockResponse):
    """An S3 response that sends its first byte, then waits for `release`."""

    def __init__(
        self,
        method: str,
        url: Any,
        body: bytes,
        started: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        """Create the response. `started` is set once the first byte is out."""
        super().__init__(method, url, response=body)
        self._started = started
        self._release = release

    @property
    def content(self) -> Any:
        """Return a body that stalls after its first byte."""
        return SimpleNamespace(iter_chunked=lambda size: self._chunks())

    async def _chunks(self) -> AsyncIterator[bytes]:
        yield self.response[:1]
        self._started.set()
        await self._release.wait()
        yield self.response[1:]


def s3_gets(aioclient_mock: AiohttpClientMocker, key: str) -> int:
    """Count the S3 requests for one key."""
    return sum(1 for call in aioclient_mock.mock_calls if call[1].path == f"/{key}")


def day_folder(media_dir: Path, day: date = TODAY) -> Path:
    """Return the folder of the local copy for one day."""
    return media_dir / ".siipet" / day.isoformat()


async def setup_mirror(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    days: int | None,
    *,
    wait_for_downloads: bool = True,
) -> None:
    """Set up the entry with local media for `days` days, and wait for the downloads.

    None leaves the option out, so the default applies. A test that pauses a
    download mid-flight passes `wait_for_downloads=False` and waits itself.
    """
    options = {} if days is None else {CONF_MEDIA_DAYS: days}
    hass.config_entries.async_update_entry(entry, options=options)
    await setup_integration(hass, entry)
    if wait_for_downloads:
        await hass.async_block_till_done(wait_background_tasks=True)
