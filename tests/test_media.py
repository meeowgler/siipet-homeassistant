"""Tests for SiiPet media lookup and access."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.siipet.api import (
    DayVisits,
    SiiPetApiError,
    SiiPetConnectionError,
    Visit,
)
from custom_components.siipet.media import (
    MediaKind,
    MediaNotFound,
    MediaUnavailable,
    SiiPetMedia,
)

from .common import EMPTY_DAY, TODAY, fixture_day, load_data, setup_integration

COVER_URL = "https://media-bucket.s3.amazonaws.com/events/ev-1/cover.jpg"
OLD_DAY = TODAY - timedelta(days=10)


def _detail(**changes: Any) -> Visit:
    return replace(Visit.from_api(load_data("event_detail.json")), **changes)


async def _media(hass: HomeAssistant, config_entry: MockConfigEntry) -> SiiPetMedia:
    await setup_integration(hass, config_entry)
    return config_entry.runtime_data.media


async def test_window_day_newest_first(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A day in the window comes from the coordinator, newest visit first."""
    media = await _media(hass, config_entry)
    calls = mock_client.get_day.await_count
    visits = await media.async_day_visits(TODAY)
    assert [visit.event_id for visit in visits] == [
        "ev-6",
        "ev-5",
        "ev-4",
        "ev-1",
        "ev-2",
        "ev-3",
    ]
    assert mock_client.get_day.await_count == calls


async def test_future_day_is_empty(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A day after today has no visits and makes no call."""
    media = await _media(hass, config_entry)
    calls = mock_client.get_day.await_count
    assert await media.async_day_visits(TODAY + timedelta(days=1)) == ()
    assert mock_client.get_day.await_count == calls


async def test_older_day_is_cached_for_five_minutes(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A day before the window is read once, then again after 5 minutes."""
    old = DayVisits((_detail(event_id="ev-old"),), {}, False)
    mock_client.get_day.side_effect = lambda requested, **_: (
        old
        if requested == OLD_DAY
        else fixture_day()
        if requested == TODAY
        else EMPTY_DAY
    )
    media = await _media(hass, config_entry)

    def old_reads() -> int:
        return sum(
            1 for call in mock_client.get_day.await_args_list if call.args[0] == OLD_DAY
        )

    assert [v.event_id for v in await media.async_day_visits(OLD_DAY)] == ["ev-old"]
    await media.async_day_visits(OLD_DAY)
    assert old_reads() == 1
    frozen_time.tick(timedelta(minutes=5))
    await media.async_day_visits(OLD_DAY)
    assert old_reads() == 2


async def test_older_day_failure(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A failed read of an older day raises MediaUnavailable."""
    media = await _media(hass, config_entry)
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    with pytest.raises(MediaUnavailable):
        await media.async_day_visits(OLD_DAY)


async def test_visit_from_window_makes_no_call(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A visit in the window needs no API call."""
    media = await _media(hass, config_entry)
    assert (await media.async_visit("ev-1")).event_id == "ev-1"
    mock_client.get_visit.assert_not_awaited()


async def test_visit_outside_window_uses_detail(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A visit outside the window is read with get_visit."""
    mock_client.get_visit.return_value = _detail(event_id="ev-old")
    media = await _media(hass, config_entry)
    assert (await media.async_visit("ev-old")).event_id == "ev-old"
    mock_client.get_visit.assert_awaited_once_with("ev-old")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SiiPetApiError(1001, "no such event"), MediaNotFound),
        (SiiPetConnectionError("down"), MediaUnavailable),
    ],
)
async def test_visit_errors(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    error: Exception,
    expected: type[Exception],
) -> None:
    """A rejected detail read is not found, and a failed one is unavailable."""
    mock_client.get_visit.side_effect = error
    media = await _media(hass, config_entry)
    with pytest.raises(expected):
        await media.async_visit("ev-old")


async def test_video_url(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A recording gets a signed URL that lasts one hour."""
    media = await _media(hass, config_entry)
    url = await media.async_video_url("ev-1")
    assert url.startswith(
        "https://media-bucket.s3.amazonaws.com/events/ev-1/video.mp4?"
    )
    assert "&X-Amz-Expires=3600&" in url


@pytest.mark.parametrize(
    "visit",
    [
        _detail(event_id="ev-old", cloud_stored=False),
        _detail(event_id="ev-old", video_key=None),
    ],
)
async def test_video_not_in_cloud(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    visit: Visit,
) -> None:
    """A recording that is only on the camera, or missing, gives no URL."""
    mock_client.get_visit.return_value = visit
    media = await _media(hass, config_entry)
    with pytest.raises(MediaNotFound):
        await media.async_video_url("ev-old")


async def test_credentials_failure(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A failed credentials call makes the media unavailable."""
    mock_client.get_media_credentials.side_effect = SiiPetConnectionError("down")
    media = await _media(hass, config_entry)
    with pytest.raises(MediaUnavailable):
        await media.async_video_url("ev-1")


@pytest.mark.parametrize(
    ("kind", "item_id", "key"),
    [
        (MediaKind.COVER, "ev-1", "events/ev-1/cover.jpg"),
        (MediaKind.STOOL, "ev-1", "events/ev-1/stool.jpg"),
        (MediaKind.AVATAR, "pet-luna", "resources/luna.jpg"),
    ],
)
async def test_image_key(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    kind: MediaKind,
    item_id: str,
    key: str,
) -> None:
    """Each image kind finds its key."""
    media = await _media(hass, config_entry)
    assert await media.async_image_key(kind, item_id) == key


@pytest.mark.parametrize(
    ("kind", "item_id"),
    [
        (MediaKind.STOOL, "ev-2"),
        (MediaKind.AVATAR, "unknown"),
        (MediaKind.AVATAR, "pet-gone"),
    ],
)
async def test_image_key_missing(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    kind: MediaKind,
    item_id: str,
) -> None:
    """A missing image raises MediaNotFound."""
    media = await _media(hass, config_entry)
    with pytest.raises(MediaNotFound):
        await media.async_image_key(kind, item_id)


async def test_fetch_image(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An image is fetched on the server with a 5-minute URL."""
    aioclient_mock.get(COVER_URL, content=b"jpeg-bytes")
    media = await _media(hass, config_entry)
    assert await media.async_fetch_image(MediaKind.COVER, "ev-1") == b"jpeg-bytes"
    [(_method, url, _data, _headers)] = aioclient_mock.mock_calls
    assert url.query["X-Amz-Expires"] == "300"


async def test_fetch_image_403_retries_with_new_credentials(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """After a 403, the image is fetched again with new credentials."""
    statuses = [403, 200]

    async def respond(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(
            method, url, status=statuses.pop(0), response=b"jpeg-bytes"
        )

    aioclient_mock.get(COVER_URL, side_effect=respond)
    media = await _media(hass, config_entry)
    assert await media.async_fetch_image(MediaKind.COVER, "ev-1") == b"jpeg-bytes"
    assert mock_client.get_media_credentials.await_count == 2


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"status": 403}, MediaUnavailable),
        ({"status": 404}, MediaNotFound),
        ({"status": 500}, MediaUnavailable),
        ({"exc": TimeoutError()}, MediaUnavailable),
    ],
)
async def test_fetch_image_errors(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    response: dict[str, Any],
    expected: type[Exception],
) -> None:
    """A failed S3 read raises a media error without the URL."""
    aioclient_mock.get(COVER_URL, **response)
    media = await _media(hass, config_entry)
    with pytest.raises(expected) as info:
        await media.async_fetch_image(MediaKind.COVER, "ev-1")
    assert "amazonaws" not in str(info.value)
    assert "X-Amz" not in str(info.value)
    assert info.value.__cause__ is None


async def test_forget_day(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A forgotten older day is read again on the next request."""
    media = await _media(hass, config_entry)
    await media.async_day_visits(OLD_DAY)
    media.forget_day(OLD_DAY)
    await media.async_day_visits(OLD_DAY)
    old_reads = [
        call for call in mock_client.get_day.await_args_list if call.args[0] == OLD_DAY
    ]
    assert len(old_reads) == 2
