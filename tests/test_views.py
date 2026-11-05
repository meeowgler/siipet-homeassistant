"""Tests for the SiiPet image view."""

from __future__ import annotations

from http import HTTPStatus
import logging
from pathlib import Path
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant.typing import ClientSessionGenerator

from custom_components.siipet.api import SiiPetConnectionError
from custom_components.siipet.media_store import key_hash

from .common import (
    COVER,
    STOOL,
    TODAY,
    VIDEO,
    day_folder,
    mirror_visit,
    mock_s3,
    s3_gets,
    serve_days,
    setup_integration,
    setup_mirror,
)

COVER_URL = "https://media-bucket.s3.amazonaws.com/events/ev-1/cover.jpg"


async def test_image_requires_login(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    """The image view refuses a request without login."""
    await setup_integration(hass, config_entry)
    client = await hass_client_no_auth()
    response = await client.get("/api/siipet/image/cover/ev-1")
    assert response.status == HTTPStatus.UNAUTHORIZED


async def test_image(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The image view returns the image bytes with private caching."""
    aioclient_mock.get(COVER_URL, content=b"jpeg-bytes")
    await setup_integration(hass, config_entry)
    client = await hass_client()
    response = await client.get("/api/siipet/image/cover/ev-1")
    assert response.status == HTTPStatus.OK
    assert await response.read() == b"jpeg-bytes"
    assert response.headers["Content-Type"] == "image/jpeg"
    assert response.headers["Cache-Control"] == "private, max-age=86400"


@pytest.mark.parametrize(
    "path",
    [
        "/api/siipet/image/video/ev-1",
        "/api/siipet/image/stool/ev-2",
        "/api/siipet/image/avatar/pet-gone",
    ],
)
async def test_image_not_found(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    path: str,
) -> None:
    """An unknown kind or a missing image returns 404."""
    await setup_integration(hass, config_entry)
    client = await hass_client()
    assert (await client.get(path)).status == HTTPStatus.NOT_FOUND


async def test_image_s3_failure(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed S3 read returns 502 and logs the failure without private values."""
    aioclient_mock.get(COVER_URL, status=HTTPStatus.INTERNAL_SERVER_ERROR)
    await setup_integration(hass, config_entry)
    client = await hass_client()
    with caplog.at_level(logging.DEBUG, logger="custom_components.siipet.views"):
        response = await client.get("/api/siipet/image/cover/ev-1")
    assert response.status == HTTPStatus.BAD_GATEWAY
    [record] = [
        record
        for record in caplog.records
        if record.name == "custom_components.siipet.views"
    ]
    assert "SiiPet image request failed" in record.getMessage()
    for text in (record.getMessage() for record in caplog.records):
        assert "amazonaws" not in text
        assert "X-Amz" not in text
        assert "media-bucket" not in text


async def test_image_entry_not_loaded(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
) -> None:
    """Without a loaded entry, the image view returns 503."""
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_client()
    response = await client.get("/api/siipet/image/cover/ev-1")
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE


async def test_recording_from_the_local_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A stored recording plays from Home Assistant, also with a range request."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    client = await hass_client()
    response = await client.get("/api/siipet/recording/ev-1")
    assert response.status == HTTPStatus.OK
    assert await response.read() == VIDEO
    assert response.headers["Content-Type"] == "video/mp4"
    assert response.headers["Cache-Control"] == "private, max-age=3600"
    response = await client.get(
        "/api/siipet/recording/ev-1", headers={"Range": "bytes=0-3"}
    )
    assert response.status == HTTPStatus.PARTIAL_CONTENT
    assert await response.read() == VIDEO[:4]


@pytest.mark.parametrize("days", [0, 7])
async def test_recording_not_in_the_local_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    days: int,
) -> None:
    """A recording that is not stored, or a copy that is off, gives 404."""
    serve_days(mock_client, {})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, days)
    client = await hass_client()
    response = await client.get("/api/siipet/recording/ev-1")
    assert response.status == HTTPStatus.NOT_FOUND


async def test_recording_requires_login(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    """The recording view refuses a request without login."""
    await setup_integration(hass, config_entry)
    client = await hass_client_no_auth()
    response = await client.get("/api/siipet/recording/ev-1")
    assert response.status == HTTPStatus.UNAUTHORIZED


async def test_recording_entry_not_loaded(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
) -> None:
    """Without a loaded entry, the recording view returns 503."""
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_client()
    response = await client.get("/api/siipet/recording/ev-1")
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE


@pytest.mark.parametrize(
    ("path", "body", "key"),
    [
        ("/api/siipet/image/cover/ev-1", COVER, "events/ev-1/cover.jpg"),
        ("/api/siipet/image/stool/ev-1", STOOL, "events/ev-1/stool.jpg"),
        ("/api/siipet/image/avatar/pet-luna", b"luna", "resources/luna.jpg"),
    ],
)
async def test_image_from_the_local_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    path: str,
    body: bytes,
    key: str,
) -> None:
    """A stored image comes from the disk, with no new S3 request."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    client = await hass_client()
    response = await client.get(path)
    assert response.status == HTTPStatus.OK
    assert await response.read() == body
    assert response.headers["Content-Type"] == "image/jpeg"
    assert response.headers["Cache-Control"] == "private, max-age=86400"
    assert s3_gets(aioclient_mock, key) == 1


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize(
    ("path", "body", "key", "file"),
    [
        (
            "/api/siipet/image/cover/ev-1",
            COVER,
            "events/ev-1/cover.jpg",
            "2026-09-26/ev-1.cover.jpg",
        ),
        (
            "/api/siipet/image/stool/ev-1",
            STOOL,
            "events/ev-1/stool.jpg",
            "2026-09-26/ev-1.stool.jpg",
        ),
        (
            "/api/siipet/image/avatar/pet-luna",
            b"luna",
            "resources/luna.jpg",
            f"avatars/pet-luna.{key_hash('resources/luna.jpg')}.jpg",
        ),
    ],
)
async def test_missing_local_image_comes_from_s3(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
    path: str,
    body: bytes,
    key: str,
    file: str,
) -> None:
    """A stored image that is gone from the disk comes from S3, then downloads again."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    stored = media_dir / ".siipet" / file
    stored.unlink()

    client = await hass_client()
    response = await client.get(path)
    assert response.status == HTTPStatus.OK
    assert await response.read() == body
    assert s3_gets(aioclient_mock, key) == 2

    await _refresh(hass, config_entry)
    assert stored.read_bytes() == body
    assert s3_gets(aioclient_mock, key) == 3


async def test_missing_local_recording_downloads_again(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_client: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A stored recording that is gone from the disk gives 404, then downloads again."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    (day_folder(media_dir) / "ev-1.mp4").unlink()

    client = await hass_client()
    response = await client.get("/api/siipet/recording/ev-1")
    assert response.status == HTTPStatus.NOT_FOUND
    assert "Cache-Control" not in response.headers

    await _refresh(hass, config_entry)
    response = await client.get("/api/siipet/recording/ev-1")
    assert response.status == HTTPStatus.OK
    assert await response.read() == VIDEO
