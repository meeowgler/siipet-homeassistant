"""Diagnostics for the SiiPet integration."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CLIENT_ID,
    CONF_MEDIA_DAYS,
    CONF_TOKEN,
    DEFAULT_MEDIA_DAYS,
    UNKNOWN_CAT_ID,
)
from .coordinator import SiiPetConfigEntry

TO_REDACT = {
    CONF_CLIENT_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_TOKEN,
    "AccessKeyId",
    "AgoraAuth",
    "Email",
    "Endpoint",
    "EventId",
    "GroupId",
    "IdentityId",
    "IdentityPoolId",
    "IotCore",
    "Member",
    "MqttClientId",
    "Owner",
    "PetId",
    "Phone",
    "S3Bucket",
    "SN",
    "SecretAccessKey",
    "SessionToken",
    "Topic",
    "Url",
    "UserId",
    "sn",
    "unique_id",
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SiiPetConfigEntry
) -> dict[str, Any]:
    """Return a summary of the entry with no private values."""
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    mirror = entry.runtime_data.mirror
    media_cache: dict[str, Any] = {
        "days": entry.options.get(CONF_MEDIA_DAYS, DEFAULT_MEDIA_DAYS),
        "running": mirror is not None and mirror.running,
    }
    if mirror is not None:
        files, size = mirror.store.stats()
        media_cache.update(files=files, bytes=size, **mirror.stats())
    device_state = entry.runtime_data.device_state
    status = device_state.link_status
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "last_update": data.updated_at.isoformat(),
        "cats": len(data.cats),
        "cameras": [
            {
                "product_id": camera.product_id,
                "role": camera.role,
                "subscribed": camera.subscription_expires is not None,
            }
            for camera in data.cameras.values()
        ],
        "visits_per_day": {
            day.isoformat(): len(visits) for day, visits in sorted(data.days.items())
        },
        "unassigned_visits": len(data.visits(UNKNOWN_CAT_ID)),
        "more_pages": data.more,
        "abnormal_labels": {
            "shape": len(data.labels.shape),
            "color": len(data.labels.color),
            "event": len(data.labels.event),
        },
        "media_cache": media_cache,
        "device_state": {
            "last_update_success": device_state.last_update_success,
            "connected": status.connected,
            "connected_since": _iso(status.connected_since),
            "last_message": _iso(status.last_message),
            "cameras_with_state": status.cameras_with_state,
            "denied_cameras": status.denied_cameras,
            "cameras": [
                {**asdict(state), "reported_at": _iso(state.reported_at)}
                for state in device_state.data.values()
            ],
        },
    }
