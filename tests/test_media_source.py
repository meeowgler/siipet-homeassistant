"""Tests for the SiiPet media source."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
from unittest.mock import AsyncMock

from homeassistant.components.media_player import BrowseError
from homeassistant.components.media_source import (
    Unresolvable,
    async_browse_media,
    async_resolve_media,
)
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant.typing import WebSocketGenerator

from custom_components.siipet.api import (
    DayVisits,
    SiiPetApiError,
    SiiPetConnectionError,
    Visit,
)

from .common import (
    EMPTY_DAY,
    TODAY,
    VIDEO,
    day_folder,
    fixture_day,
    load_data,
    md5_hex,
    mirror_visit,
    mock_s3,
    serve_days,
    setup_integration,
    setup_mirror,
)

ROOT = "media-source://siipet"
OLD_DAY = TODAY - timedelta(days=10)


def _old_visit(**changes: object) -> Visit:
    return replace(
        Visit.from_api(load_data("event_detail.json")), event_id="ev-old", **changes
    )


async def test_root_lists_30_days(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The root lists the last 30 days, newest first."""
    await setup_integration(hass, config_entry)
    root = await async_browse_media(hass, ROOT)
    assert root.title == "SiiPet"
    assert len(root.children) == 30
    assert root.children[0].identifier == "day/2026-09-26"
    assert root.children[0].title == "2026-09-26"
    assert root.children[-1].identifier == "day/2026-08-28"
    assert all(child.can_expand and not child.can_play for child in root.children)


async def test_day_lists_visits(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A day lists its visits, newest first, with titles and cover thumbnails."""
    await setup_integration(hass, config_entry)
    day = await async_browse_media(hass, f"{ROOT}/day/2026-09-26")
    assert [child.title for child in day.children] == [
        "09:00 Luna - Pee (3:20)",
        "08:00 Milo - Poop (1:30)",
        "07:10 Unknown cat - Pee (0:30)",
        "06:48 Luna - Poop (1:20)",
        "05:12 Milo - Pee (0:45)",
        "01:30 Luna - Lingering (0:20)",
    ]
    first = day.children[0]
    assert first.identifier == "visit/ev-6"
    assert first.can_play is True
    assert first.can_expand is False
    assert first.thumbnail == "/api/siipet/image/cover/ev-6"


async def test_on_camera_only_visit(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A visit that is only on the camera cannot play and says so."""
    old = DayVisits((_old_visit(cloud_stored=False),), {}, False)
    mock_client.get_day.side_effect = lambda requested, **_: (
        old
        if requested == OLD_DAY
        else fixture_day()
        if requested == TODAY
        else EMPTY_DAY
    )
    await setup_integration(hass, config_entry)
    day = await async_browse_media(hass, f"{ROOT}/day/{OLD_DAY.isoformat()}")
    [visit] = day.children
    assert visit.title == "06:48 Luna - Poop (1:20) (on camera only)"
    assert visit.can_play is False


async def test_browse_has_no_s3_urls(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Browse results contain only Home Assistant paths."""
    await setup_integration(hass, config_entry)
    for media_id in (ROOT, f"{ROOT}/day/2026-09-26"):
        text = json.dumps((await async_browse_media(hass, media_id)).as_dict())
        assert "amazonaws" not in text
        assert "X-Amz" not in text


@pytest.mark.parametrize("identifier", ["week/1", "day/not-a-date"])
async def test_browse_unknown_folder(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    identifier: str,
) -> None:
    """An unknown folder raises BrowseError."""
    await setup_integration(hass, config_entry)
    with pytest.raises(BrowseError) as info:
        await async_browse_media(hass, f"{ROOT}/{identifier}")
    assert str(info.value) == "Unknown SiiPet folder"


async def test_browse_day_failure(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A failed read of an older day raises BrowseError."""
    await setup_integration(hass, config_entry)
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    with pytest.raises(BrowseError) as info:
        await async_browse_media(hass, f"{ROOT}/day/{OLD_DAY.isoformat()}")
    assert str(info.value) == "Could not read the visits of the day"


async def test_browse_not_loaded(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Without a loaded entry, browse raises BrowseError."""
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(BrowseError) as info:
        await async_browse_media(hass, ROOT)
    assert str(info.value) == "SiiPet is not loaded"


async def test_resolve_video(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A visit resolves to a signed recording URL."""
    await setup_integration(hass, config_entry)
    media = await async_resolve_media(hass, f"{ROOT}/visit/ev-1", None)
    assert media.mime_type == "video/mp4"
    assert media.url.startswith(
        "https://media-bucket.s3.amazonaws.com/events/ev-1/video.mp4?"
    )


@pytest.mark.parametrize(
    ("identifier", "path"),
    [
        ("cover/ev-1", "/api/siipet/image/cover/ev-1"),
        ("stool/ev-1", "/api/siipet/image/stool/ev-1"),
        ("avatar/pet-luna", "/api/siipet/image/avatar/pet-luna"),
    ],
)
async def test_resolve_image(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    identifier: str,
    path: str,
) -> None:
    """An image resolves to the image view path."""
    await setup_integration(hass, config_entry)
    media = await async_resolve_media(hass, f"{ROOT}/{identifier}", None)
    assert media.url == path
    assert media.mime_type == "image/jpeg"


@pytest.mark.parametrize(
    "identifier",
    ["visit/ev-old", "visit/", "stool/ev-2", "avatar/pet-gone", "week/1"],
)
async def test_resolve_errors(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    identifier: str,
) -> None:
    """A missing or unknown item raises Unresolvable without its id."""
    mock_client.get_visit.side_effect = SiiPetApiError(1001, "no such event")
    await setup_integration(hass, config_entry)
    with pytest.raises(Unresolvable) as info:
        await async_resolve_media(hass, f"{ROOT}/{identifier}", None)
    assert "Unknown media source" not in str(info.value)
    assert "pet-gone" not in str(info.value)


async def test_resolve_not_loaded(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Without a loaded entry, resolve raises Unresolvable."""
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(Unresolvable) as info:
        await async_resolve_media(hass, f"{ROOT}/visit/ev-1", None)
    assert str(info.value) == "SiiPet is not loaded"


async def test_resolve_video_from_the_local_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A stored recording resolves to the recording view, signed for the card."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    media = await async_resolve_media(hass, f"{ROOT}/visit/ev-1", None)
    assert media.url == "/api/siipet/recording/ev-1"
    assert media.mime_type == "video/mp4"

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "media_source/resolve_media", "media_content_id": f"{ROOT}/visit/ev-1"}
    )
    result = await client.receive_json()
    assert result["success"]
    assert result["result"]["url"].startswith("/api/siipet/recording/ev-1?authSig=")


async def test_resolve_video_not_in_the_local_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A recording that failed its check still resolves to a signed S3 URL."""
    serve_days(mock_client, {TODAY: (mirror_visit(video_md5=md5_hex(b"other")),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    media = await async_resolve_media(hass, f"{ROOT}/visit/ev-1", None)
    assert media.url.startswith(
        "https://media-bucket.s3.amazonaws.com/events/ev-1/video.mp4?"
    )


async def test_resolve_video_with_a_missing_local_file(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A stored recording that is gone from the disk resolves to S3, then downloads again."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    (day_folder(media_dir) / "ev-1.mp4").unlink()

    media = await async_resolve_media(hass, f"{ROOT}/visit/ev-1", None)
    assert media.url.startswith(
        "https://media-bucket.s3.amazonaws.com/events/ev-1/video.mp4?"
    )

    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert (day_folder(media_dir) / "ev-1.mp4").read_bytes() == VIDEO
    media = await async_resolve_media(hass, f"{ROOT}/visit/ev-1", None)
    assert media.url == "/api/siipet/recording/ev-1"
