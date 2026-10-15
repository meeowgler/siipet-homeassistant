"""Tests for the SiiPet diagnostics."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from homeassistant.components.diagnostics import REDACTED
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.siipet.const import (
    CONF_AUTH_METHOD,
    CONF_CLIENT_ID,
    CONF_EXPIRE_AT,
    CONF_TOKEN,
)
from custom_components.siipet.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)
from custom_components.siipet.media_store import key_hash

from .common import (
    COVER,
    DEVICE_STATE,
    STOOL,
    TODAY,
    VIDEO,
    FakeShadowLink,
    load_data,
    mirror_visit,
    mock_s3,
    serve_days,
    setup_integration,
    setup_mirror,
)


async def test_diagnostics(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Diagnostics summarize the account and contain no private values."""
    await setup_integration(hass, config_entry)
    result = await async_get_config_entry_diagnostics(hass, config_entry)

    assert result["last_update_success"] is True
    assert result["last_update"] == "2026-09-26T12:00:00+00:00"
    assert result["cats"] == 2
    assert result["cameras"][0] == {
        "product_id": "JOY1",
        "role": 1,
        "subscribed": True,
    }
    assert result["visits_per_day"]["2026-09-26"] == 6
    assert result["unassigned_visits"] == 1
    assert result["abnormal_labels"] == {"shape": 2, "color": 1, "event": 1}

    entry = result["entry"]
    assert entry["unique_id"] == REDACTED
    assert entry["data"] == {
        CONF_AUTH_METHOD: "email",
        CONF_EMAIL: REDACTED,
        CONF_TOKEN: REDACTED,
        CONF_EXPIRE_AT: config_entry.data[CONF_EXPIRE_AT],
        CONF_CLIENT_ID: REDACTED,
    }

    # Also guards the ids that the summary does not include.
    text = json.dumps(result, default=str)
    for private in (
        load_data("login.json")["Token"],
        "cat@example.com",
        "client-uuid-0001",
        "user-0001",
        "SN0001",
        "pet-luna",
        "group-0001",
        "ev-1",
    ):
        assert private not in text


def test_media_credential_keys_are_redacted() -> None:
    """The media credential keys are on the redaction list."""
    assert {"AccessKeyId", "SecretAccessKey", "SessionToken", "S3Bucket"} <= TO_REDACT


async def test_diagnostics_count_the_local_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The local copy shows as counts, with no ids, paths, keys, or hashes."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    assert result["media_cache"] == {
        "days": 7,
        "running": True,
        "files": 5,
        "bytes": len(VIDEO) + len(COVER) + len(STOOL) + len(b"luna") + len(b"milo"),
        "queued": 0,
        "failing": 0,
    }
    text = json.dumps(result, default=str)
    for private in (
        "ev-1",
        ".siipet",
        "resources/luna.jpg",
        key_hash("resources/luna.jpg"),
    ):
        assert private not in text


async def test_diagnostics_local_copy_off(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """With 0 days, the diagnostics say that the copy does not run."""
    await setup_integration(hass, config_entry)
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    assert result["media_cache"] == {"days": 0, "running": False}


async def test_diagnostics_local_copy_stopped(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A copy that stopped after a folder error does not count as running."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    with patch(
        "custom_components.siipet.media_store.shutil.disk_usage",
        side_effect=OSError,
    ):
        await setup_mirror(hass, config_entry, 7)
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    assert result["media_cache"] == {
        "days": 7,
        "running": False,
        "files": 0,
        "bytes": 0,
        "queued": 0,
        "failing": 0,
    }


def test_iot_keys_are_redacted() -> None:
    """The AWS IoT keys are on the redaction list."""
    assert {
        "IotCore",
        "IdentityId",
        "IdentityPoolId",
        "Endpoint",
        "MqttClientId",
    } <= TO_REDACT


async def test_device_state_diagnostics(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Diagnostics show the link state and each camera state, with no serial."""
    await setup_integration(hass, config_entry)
    shadow_links[0].on_state("SN0001", DEVICE_STATE)
    await hass.async_block_till_done()
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    assert result["device_state"] == {
        "last_update_success": True,
        "connected": True,
        "connected_since": "2026-09-26T11:00:00+00:00",
        "last_message": "2026-09-26T11:59:00+00:00",
        "cameras_with_state": 1,
        "denied_cameras": 1,
        "cameras": [
            {
                "battery": 72,
                "charging": False,
                "privacy": False,
                "fill_light": 2,
                "fill_light_auto": True,
                "fill_light_low": True,
                "fill_light_brightness": 70,
                "motion_level": 3,
                "update_mode": 0,
                "cloud_storage": True,
                "online": True,
                "firmware": "1.2.3",
                "rssi": -61,
                "reported_at": "2026-09-26T11:55:00+00:00",
            }
        ],
    }
    assert "SN0001" not in json.dumps(result, default=str)
