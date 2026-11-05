"""Tests for the websocket commands of the SiiPet card."""

from __future__ import annotations

from datetime import date, timedelta
from http import HTTPStatus
import json
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr
import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant.typing import (
    ClientSessionGenerator,
    WebSocketGenerator,
)

from custom_components.siipet.api import (
    CalendarDay,
    SiiPetAuthError,
    SiiPetConnectionError,
)
from custom_components.siipet.const import DOMAIN, UNKNOWN_CAT_ID

from .common import (
    EMPTY_DAY,
    NOW,
    TODAY,
    fixture_day,
    load_data,
    setup_integration,
    siipet_device_id,
)

COVER_URL = "https://media-bucket.s3.amazonaws.com/events/ev-1/cover.jpg"


async def _ws(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, **message: Any
) -> dict[str, Any]:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(message)
    return await client.receive_json()


def _private_values(response: dict[str, Any]) -> list[str]:
    """Return the private values found outside the signed avatar paths."""
    text = json.dumps(response)
    for cat in (response.get("result") or {}).get("cats") or ():
        if cat.get("avatar"):
            text = text.replace(cat["avatar"], "")
    return [
        value
        for value in (
            "pet-luna",
            "pet-milo",
            "SN0001",
            "SN0002",
            "events/",
            "amazonaws",
        )
        if value in text
    ]


async def test_cats(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The cats come with signed avatar paths and the number of waiting visits."""
    await setup_integration(hass, config_entry)
    response = await _ws(hass, hass_ws_client, type="siipet/cats")
    assert response["success"]
    result = response["result"]
    assert [(cat["device_id"], cat["name"]) for cat in result["cats"]] == [
        (siipet_device_id(hass, config_entry, "pet-luna"), "Luna"),
        (siipet_device_id(hass, config_entry, "pet-milo"), "Milo"),
    ]
    assert result["cats"][0]["avatar"].startswith(
        "/api/siipet/image/avatar/pet-luna?authSig="
    )
    assert result["unknown"] == {
        "device_id": siipet_device_id(hass, config_entry, UNKNOWN_CAT_ID),
        "waiting": 1,
    }
    assert result["today"] == "2026-09-26"
    assert result["available"] is True
    assert result["updated_at"] == NOW
    assert _private_values(response) == []


async def test_cats_after_a_failed_update(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """After a failed update, the cats say so and keep the day of the last update."""
    await setup_integration(hass, config_entry)
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    await config_entry.runtime_data.coordinator.async_refresh()
    response = await _ws(hass, hass_ws_client, type="siipet/cats")
    result = response["result"]
    assert result["available"] is False
    assert result["today"] == "2026-09-26"
    assert result["updated_at"] == NOW


async def test_cats_for_a_user_who_is_not_admin(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    """A user who is not an admin can read the cats."""
    await setup_integration(hass, config_entry)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": "siipet/cats"})
    response = await client.receive_json()
    assert response["success"]
    assert [cat["name"] for cat in response["result"]["cats"]] == ["Luna", "Milo"]


async def test_day(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A window day comes newest first, with a summary and signed image paths, and no API call."""
    await setup_integration(hass, config_entry)
    reads = mock_client.get_day.await_count
    response = await _ws(
        hass, hass_ws_client, type="siipet/day", date=TODAY.isoformat()
    )
    assert response["success"]
    result = response["result"]
    assert result["summary"] == {"visits": 5, "pee": 3, "poop": 2, "abnormal": 2}
    visits = result["visits"]
    assert [visit["event_id"] for visit in visits] == [
        "ev-6",
        "ev-5",
        "ev-4",
        "ev-1",
        "ev-2",
        "ev-3",
    ]
    first = visits[3]
    assert first["type"] == "poop"
    assert first["cats"] == [
        {"device_id": siipet_device_id(hass, config_entry, "pet-luna"), "name": "Luna"}
    ]
    assert first["cover"].startswith("/api/siipet/image/cover/ev-1?authSig=")
    assert first["stool"].startswith("/api/siipet/image/stool/ev-1?authSig=")
    assert visits[0]["stool"] is None
    assert _private_values(response) == []
    assert mock_client.get_day.await_count == reads


@pytest.mark.parametrize(
    ("hallway_rename", "hallway_label"),
    [(None, "Hall device"), ("Hall box", "Hall box")],
)
async def test_day_camera_labels(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
    hallway_rename: str | None,
    hallway_label: str,
) -> None:
    """A visit names the area of its camera device, else the device name.

    The area wins over a rename in Home Assistant.
    """
    await setup_integration(hass, config_entry)
    area = area_registry.async_create("Upstairs bath")
    device_registry.async_update_device(
        siipet_device_id(hass, config_entry, "SN0001"),
        area_id=area.id,
        name_by_user="Box 1",
    )
    device_registry.async_update_device(
        siipet_device_id(hass, config_entry, "SN0002"),
        name="Hall device",
        name_by_user=hallway_rename,
    )
    response = await _ws(
        hass, hass_ws_client, type="siipet/day", date=TODAY.isoformat()
    )
    labels = {
        visit["event_id"]: visit["camera"] for visit in response["result"]["visits"]
    }
    assert labels == {
        "ev-1": "Upstairs bath",
        "ev-2": hallway_label,
        "ev-3": "Upstairs bath",
        "ev-4": "Upstairs bath",
        "ev-5": hallway_label,
        "ev-6": "Upstairs bath",
    }


@pytest.mark.parametrize(
    "message",
    [
        {"type": "siipet/day", "date": TODAY.isoformat()},
        {"type": "siipet/queue"},
        {"type": "siipet/visit", "event_id": "ev-4"},
    ],
)
async def test_card_commands_name_the_camera_area(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
    message: dict[str, Any],
) -> None:
    """Each card command names the area of the camera of a visit."""
    await setup_integration(hass, config_entry)
    area = area_registry.async_create("Upstairs bath")
    device_registry.async_update_device(
        siipet_device_id(hass, config_entry, "SN0001"), area_id=area.id
    )
    result = (await _ws(hass, hass_ws_client, **message))["result"]
    visits = [result["visit"]] if "visit" in result else result["visits"]
    [visit] = [visit for visit in visits if visit["event_id"] == "ev-4"]
    assert visit["camera"] == "Upstairs bath"


async def test_day_camera_label_without_a_device(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A camera without a device takes its SiiPet name."""
    await setup_integration(hass, config_entry)
    device_registry.async_remove_device(siipet_device_id(hass, config_entry, "SN0002"))
    response = await _ws(
        hass, hass_ws_client, type="siipet/day", date=TODAY.isoformat()
    )
    [visit] = [
        visit for visit in response["result"]["visits"] if visit["event_id"] == "ev-2"
    ]
    assert visit["camera"] == "Hallway"


async def test_day_one_camera_has_no_label(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """With one camera on the account, no visit names a camera."""
    mock_client.get_cameras.return_value = {
        sn: camera
        for sn, camera in mock_client.get_cameras.return_value.items()
        if sn == "SN0001"
    }
    await setup_integration(hass, config_entry)
    response = await _ws(
        hass, hass_ws_client, type="siipet/day", date=TODAY.isoformat()
    )
    assert [visit["camera"] for visit in response["result"]["visits"]] == [None] * 6


@pytest.mark.parametrize(
    ("identifier", "event_ids", "summary"),
    [
        (
            "pet-luna",
            ["ev-6", "ev-1", "ev-3"],
            {"visits": 2, "pee": 1, "poop": 1, "abnormal": 1},
        ),
        (UNKNOWN_CAT_ID, ["ev-4"], {"visits": 1, "pee": 1, "poop": 0, "abnormal": 0}),
    ],
)
async def test_day_for_one_cat(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    identifier: str,
    event_ids: list[str],
    summary: dict[str, int],
) -> None:
    """A cat filter keeps the visits of that cat, also for the Unknown cat."""
    await setup_integration(hass, config_entry)
    response = await _ws(
        hass,
        hass_ws_client,
        type="siipet/day",
        date=TODAY.isoformat(),
        cat=siipet_device_id(hass, config_entry, identifier),
    )
    assert [visit["event_id"] for visit in response["result"]["visits"]] == event_ids
    assert response["result"]["summary"] == summary


async def test_day_older_day(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A day outside the coordinator window reads through the media cache."""
    await setup_integration(hass, config_entry)
    day = TODAY - timedelta(days=20)
    mock_client.get_day.side_effect = lambda requested, **_: (
        fixture_day() if requested == day else EMPTY_DAY
    )
    response = await _ws(hass, hass_ws_client, type="siipet/day", date=day.isoformat())
    assert len(response["result"]["visits"]) == 6
    assert mock_client.get_day.await_args_list[-1].args[0] == day


@pytest.mark.parametrize(
    ("message", "code", "key", "text"),
    [
        (
            {"date": (TODAY - timedelta(days=31)).isoformat()},
            "service_validation_error",
            "date_out_of_range",
            "Choose a date from 2026-08-27 to 2026-09-26",
        ),
        (
            {"date": TODAY.isoformat(), "cat": "no-such-device"},
            "service_validation_error",
            "invalid_cat",
            "Choose a SiiPet cat device",
        ),
        (
            {"date": (TODAY - timedelta(days=20)).isoformat()},
            "home_assistant_error",
            "request_failed",
            "SiiPet could not complete the request: Could not read the visits of the day",
        ),
    ],
)
async def test_day_errors(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    caplog: pytest.LogCaptureFixture,
    message: dict[str, Any],
    code: str,
    key: str,
    text: str,
) -> None:
    """Errors carry the translated key of the actions and leave no error in the log."""
    await setup_integration(hass, config_entry)
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    response = await _ws(hass, hass_ws_client, type="siipet/day", **message)
    assert not response["success"]
    assert response["error"]["code"] == code
    assert response["error"]["translation_key"] == key
    assert response["error"]["translation_domain"] == DOMAIN
    assert response["error"]["message"] == text
    assert "Error handling message" not in caplog.text


async def test_day_auth_error_starts_reauth(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """An auth error on an older day raises a translated error and starts reauth."""
    await setup_integration(hass, config_entry)
    mock_client.get_day.side_effect = SiiPetAuthError("-2: token illegal")
    day = TODAY - timedelta(days=20)
    response = await _ws(hass, hass_ws_client, type="siipet/day", date=day.isoformat())
    assert not response["success"]
    assert response["error"]["translation_key"] == "request_failed"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_queue(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The queue holds the visits of the window without a cat, newest first."""
    await setup_integration(hass, config_entry)
    response = await _ws(hass, hass_ws_client, type="siipet/queue")
    assert response["success"]
    [visit] = response["result"]["visits"]
    assert visit["event_id"] == "ev-4"
    assert visit["cats"] == []
    assert visit["cover"].startswith("/api/siipet/image/cover/ev-4?authSig=")
    assert _private_values(response) == []


def _without_paths(visit: dict[str, Any]) -> dict[str, Any]:
    """Return a card visit without its signed image paths."""
    return {key: value for key, value in visit.items() if key not in ("cover", "stool")}


@pytest.mark.parametrize(
    ("event_id", "cat_names", "has_stool"),
    [("ev-1", ["Luna"], True), ("ev-4", [], False), ("ev-6", ["Luna"], False)],
)
async def test_visit(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    event_id: str,
    cat_names: list[str],
    has_stool: bool,
) -> None:
    """A window visit comes with its day, in the visit shape of siipet/day, and no API call."""
    await setup_integration(hass, config_entry)
    day = await _ws(hass, hass_ws_client, type="siipet/day", date=TODAY.isoformat())
    [expected] = [
        visit for visit in day["result"]["visits"] if visit["event_id"] == event_id
    ]
    reads = mock_client.get_day.await_count
    response = await _ws(hass, hass_ws_client, type="siipet/visit", event_id=event_id)
    assert response["success"]
    result = response["result"]
    assert result["date"] == TODAY.isoformat()
    visit = result["visit"]
    assert _without_paths(visit) == _without_paths(expected)
    assert [cat["name"] for cat in visit["cats"]] == cat_names
    assert visit["cover"].startswith(f"/api/siipet/image/cover/{event_id}?authSig=")
    if has_stool:
        assert visit["stool"].startswith(f"/api/siipet/image/stool/{event_id}?authSig=")
    else:
        assert visit["stool"] is None
    assert _private_values(response) == []
    assert mock_client.get_day.await_count == reads


async def test_visit_on_an_earlier_window_day(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The date is the window day that holds the visit."""
    day = TODAY - timedelta(days=2)
    mock_client.get_day.side_effect = lambda requested, **_: (
        fixture_day() if requested == day else EMPTY_DAY
    )
    await setup_integration(hass, config_entry)
    response = await _ws(hass, hass_ws_client, type="siipet/visit", event_id="ev-1")
    assert response["result"]["date"] == day.isoformat()
    assert response["result"]["visit"]["event_id"] == "ev-1"


async def test_visit_not_in_window(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A visit outside the window gives visit_not_in_window, with no API call and no error in the log."""
    await setup_integration(hass, config_entry)
    reads = mock_client.get_day.await_count
    response = await _ws(hass, hass_ws_client, type="siipet/visit", event_id="ev-99")
    assert not response["success"]
    error = response["error"]
    assert error["code"] == "service_validation_error"
    assert error["translation_key"] == "visit_not_in_window"
    assert error["translation_domain"] == DOMAIN
    assert error["translation_placeholders"] == {"event_id": "ev-99"}
    assert error["message"] == "SiiPet has no visit ev-99 in the last 7 days"
    assert mock_client.get_day.await_count == reads
    assert "Error handling message" not in caplog.text


@pytest.mark.parametrize(
    "message",
    [
        {"type": "siipet/cats"},
        {"type": "siipet/calendar", "month": "2026-09"},
        {"type": "siipet/day", "date": TODAY.isoformat()},
        {"type": "siipet/queue"},
        {"type": "siipet/visit", "event_id": "ev-1"},
    ],
    ids=lambda message: message["type"],
)
async def test_not_loaded(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    message: dict[str, Any],
) -> None:
    """Without a loaded entry, the commands answer with not_loaded."""
    await setup_integration(hass, config_entry)
    await hass.config_entries.async_unload(config_entry.entry_id)
    response = await _ws(hass, hass_ws_client, **message)
    assert response["error"]["translation_key"] == "not_loaded"


async def test_signed_cover_path_loads_without_login(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A signed cover path works in an img tag, which sends no login header."""
    aioclient_mock.get(COVER_URL, content=b"jpeg-bytes")
    await setup_integration(hass, config_entry)
    response = await _ws(
        hass, hass_ws_client, type="siipet/day", date=TODAY.isoformat()
    )
    path = next(
        visit["cover"]
        for visit in response["result"]["visits"]
        if visit["event_id"] == "ev-1"
    )
    client = await hass_client_no_auth()
    image = await client.get(path)
    assert image.status == HTTPStatus.OK
    assert await image.read() == b"jpeg-bytes"


def _milo_month(pet_id: str, first: date, last: date) -> tuple[CalendarDay, ...]:
    """Luna gets the fixture month. Milo gets two days of his own."""
    if pet_id == "pet-luna":
        return tuple(
            CalendarDay.from_api(item)
            for item in load_data("pet_calendar.json")["DataCalendar"]
        )
    return (
        CalendarDay(date(2026, 9, 24), 1, 0, 60000, 0, False),
        CalendarDay(date(2026, 9, 26), 0, 1, 0, 70000, True),
    )


async def test_calendar_one_cat(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """One cat's month counts pee and poop, and marks abnormal or flagged days."""
    await setup_integration(hass, config_entry)
    response = await _ws(
        hass,
        hass_ws_client,
        type="siipet/calendar",
        month="2026-09",
        cat=siipet_device_id(hass, config_entry, "pet-luna"),
    )
    assert response["result"] == {
        "days": {
            "2026-09-24": {"visits": 4, "abnormal": 1, "marked": True},
            "2026-09-25": {"visits": 2, "abnormal": 0, "marked": True},
            "2026-09-26": {"visits": 2, "abnormal": 0, "marked": False},
        },
        "first": "2026-08-27",
        "last": "2026-09-26",
    }
    mock_client.get_calendar.assert_awaited_once_with(
        "pet-luna", date(2026, 9, 1), date(2026, 9, 30)
    )


async def test_calendar_all_cats(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Without a cat, the month adds the days of every cat together."""
    await setup_integration(hass, config_entry)
    mock_client.get_calendar.side_effect = _milo_month
    response = await _ws(hass, hass_ws_client, type="siipet/calendar", month="2026-09")
    assert response["result"]["days"] == {
        "2026-09-24": {"visits": 5, "abnormal": 1, "marked": True},
        "2026-09-25": {"visits": 2, "abnormal": 0, "marked": True},
        "2026-09-26": {"visits": 3, "abnormal": 1, "marked": True},
    }
    assert [call.args[0] for call in mock_client.get_calendar.await_args_list] == [
        "pet-luna",
        "pet-milo",
    ]


async def test_calendar_is_cached(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A second read of the same month makes no API call."""
    await setup_integration(hass, config_entry)
    for _ in range(2):
        await _ws(hass, hass_ws_client, type="siipet/calendar", month="2026-09")
    assert mock_client.get_calendar.await_count == 2


async def test_calendar_unknown_cat(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The Unknown cat has no calendar."""
    await setup_integration(hass, config_entry)
    response = await _ws(
        hass,
        hass_ws_client,
        type="siipet/calendar",
        month="2026-09",
        cat=siipet_device_id(hass, config_entry, UNKNOWN_CAT_ID),
    )
    assert response["result"]["days"] == {}
    mock_client.get_calendar.assert_not_awaited()


async def test_calendar_invalid_cat(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A device that is not a SiiPet cat gives invalid_cat, without an API call."""
    await setup_integration(hass, config_entry)
    for device_id in ("no-such-device", siipet_device_id(hass, config_entry, "SN0001")):
        response = await _ws(
            hass, hass_ws_client, type="siipet/calendar", month="2026-09", cat=device_id
        )
        assert response["error"]["code"] == "service_validation_error"
        assert response["error"]["translation_key"] == "invalid_cat"
    mock_client.get_calendar.assert_not_awaited()


@pytest.mark.parametrize(
    ("month", "first", "last"),
    [
        ("2025-09", date(2025, 9, 1), date(2025, 9, 30)),
        ("2026-09", date(2026, 9, 1), date(2026, 9, 30)),
    ],
)
async def test_calendar_months_in_range(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    month: str,
    first: date,
    last: date,
) -> None:
    """The current month and the 12 months before it can be read."""
    await setup_integration(hass, config_entry)
    response = await _ws(
        hass,
        hass_ws_client,
        type="siipet/calendar",
        month=month,
        cat=siipet_device_id(hass, config_entry, "pet-luna"),
    )
    assert response["success"]
    mock_client.get_calendar.assert_awaited_once_with("pet-luna", first, last)


@pytest.mark.parametrize("month", ["2025-08", "2026-10", "9999-12"])
async def test_calendar_month_out_of_range(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    caplog: pytest.LogCaptureFixture,
    month: str,
) -> None:
    """A month after the current one or more than 12 months back is refused before any call."""
    await setup_integration(hass, config_entry)
    response = await _ws(hass, hass_ws_client, type="siipet/calendar", month=month)
    assert response["error"]["code"] == "service_validation_error"
    assert response["error"]["translation_key"] == "date_out_of_range"
    assert response["error"]["translation_placeholders"] == {
        "first": "2025-09-01",
        "last": "2026-09-26",
    }
    mock_client.get_calendar.assert_not_awaited()
    assert "Error handling message" not in caplog.text


@pytest.mark.parametrize("month", ["2026-9", "2026-13", "09-2026"])
async def test_calendar_bad_month(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    month: str,
) -> None:
    """A month that is not YYYY-MM is refused before any call."""
    await setup_integration(hass, config_entry)
    response = await _ws(hass, hass_ws_client, type="siipet/calendar", month=month)
    assert response["error"]["code"] == "invalid_format"
    mock_client.get_calendar.assert_not_awaited()


async def test_calendar_request_failed(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A failed calendar read gives request_failed."""
    await setup_integration(hass, config_entry)
    mock_client.get_calendar.side_effect = SiiPetConnectionError("down")
    response = await _ws(hass, hass_ws_client, type="siipet/calendar", month="2026-09")
    assert response["error"]["code"] == "home_assistant_error"
    assert response["error"]["translation_key"] == "request_failed"


async def test_calendar_auth_error_starts_reauth(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """An auth error gives request_failed and starts reauth."""
    await setup_integration(hass, config_entry)
    mock_client.get_calendar.side_effect = SiiPetAuthError("-2: token illegal")
    response = await _ws(hass, hass_ws_client, type="siipet/calendar", month="2026-09")
    assert response["error"]["translation_key"] == "request_failed"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
