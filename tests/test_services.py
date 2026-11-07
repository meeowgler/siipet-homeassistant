"""Tests for the SiiPet actions."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.auth.models import User
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import area_registry as ar, device_registry as dr
import probatio
import pytest
from pytest_homeassistant.common import MockConfigEntry
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.siipet.api import (
    SiiPetApiError,
    SiiPetAuthError,
    SiiPetConnectionError,
    Visit,
    VisitType,
)
from custom_components.siipet.const import DOMAIN

from .common import (
    S3,
    TODAY,
    StalledResponse,
    day_folder,
    load_data,
    md5_hex,
    mirror_visit,
    mock_s3,
    serve_days,
    setup_integration,
    setup_mirror,
    siipet_device_id,
)


async def _list(hass: HomeAssistant, **data: Any) -> dict[str, Any]:
    return await hass.services.async_call(
        DOMAIN, "list_visits", data, blocking=True, return_response=True
    )


async def test_list_visits_today(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Today's visits come newest first, with the cats of the account."""
    await setup_integration(hass, config_entry)
    luna = siipet_device_id(hass, config_entry, "pet-luna")
    response = await _list(hass)
    assert response["cats"] == [
        {"device_id": luna, "name": "Luna", "unknown": False},
        {
            "device_id": siipet_device_id(hass, config_entry, "pet-milo"),
            "name": "Milo",
            "unknown": False,
        },
        {
            "device_id": siipet_device_id(hass, config_entry, "unknown"),
            "name": "Unknown cat",
            "unknown": True,
        },
    ]
    visits = response["visits"]
    assert [visit["event_id"] for visit in visits] == [
        "ev-6",
        "ev-5",
        "ev-4",
        "ev-1",
        "ev-2",
        "ev-3",
    ]
    assert visits[0] == {
        "event_id": "ev-6",
        "start": "2026-09-26T09:00:00+00:00",
        "duration": 200,
        "type": "pee",
        "cats": [{"device_id": luna, "name": "Luna"}],
        "camera": "Bathroom",
        "note": "Long visit",
        "abnormal": True,
        "abnormal_reasons": ["Potty Overtime"],
        "has_video": True,
        "has_stool_image": False,
    }
    assert visits[2]["cats"] == []


@pytest.mark.parametrize(
    ("identifier", "event_ids"),
    [("pet-milo", ["ev-5", "ev-2"]), ("unknown", ["ev-4"])],
)
async def test_list_visits_for_one_cat(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    identifier: str,
    event_ids: list[str],
) -> None:
    """A cat device, or the Unknown cat device, filters the visits."""
    await setup_integration(hass, config_entry)
    response = await _list(hass, cat=siipet_device_id(hass, config_entry, identifier))
    assert [visit["event_id"] for visit in response["visits"]] == event_ids


async def test_list_visits_keeps_the_siipet_camera_name(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    area_registry: ar.AreaRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A visit names its camera as SiiPet does, also when the device has an area and a rename."""
    await setup_integration(hass, config_entry)
    area = area_registry.async_create("Upstairs bath")
    device_registry.async_update_device(
        siipet_device_id(hass, config_entry, "SN0001"),
        area_id=area.id,
        name_by_user="Box 1",
    )
    response = await _list(hass)
    assert {visit["camera"] for visit in response["visits"]} == {"Bathroom", "Hallway"}


async def test_list_visits_window_days_make_no_call(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Days in the 7-day window come from the coordinator."""
    await setup_integration(hass, config_entry)
    calls = mock_client.get_day.await_count
    response = await _list(hass, days=7)
    assert len(response["visits"]) == 6
    assert mock_client.get_day.await_count == calls


async def test_list_visits_older_day(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A day before the window is read from the API."""
    await setup_integration(hass, config_entry)
    day = TODAY - timedelta(days=20)
    response = await _list(hass, date=day.isoformat())
    assert response["visits"] == []
    assert mock_client.get_day.await_args_list[-1].args[0] == day


async def test_list_visits_stops_at_history_limit(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A window that ends near the 30-day limit reads no older day."""
    await setup_integration(hass, config_entry)
    calls = mock_client.get_day.await_count
    await _list(hass, date=(TODAY - timedelta(days=29)).isoformat(), days=7)
    read = [call.args[0] for call in mock_client.get_day.await_args_list[calls:]]
    assert read == [TODAY - timedelta(days=29), TODAY - timedelta(days=30)]


async def test_list_visits_older_day_failure(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A failed read of an older day raises a translated error."""
    await setup_integration(hass, config_entry)
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    with pytest.raises(HomeAssistantError) as info:
        await _list(hass, date=(TODAY - timedelta(days=20)).isoformat())
    assert info.value.translation_key == "request_failed"


async def test_list_visits_older_day_auth_error_starts_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """An auth error on an older day raises a translated error and starts reauth."""
    await setup_integration(hass, config_entry)
    mock_client.get_day.side_effect = SiiPetAuthError("-2: token illegal")
    with pytest.raises(HomeAssistantError) as info:
        await _list(hass, date=(TODAY - timedelta(days=20)).isoformat())
    assert info.value.translation_key == "request_failed"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


@pytest.mark.parametrize("offset", [31, -1])
async def test_list_visits_date_out_of_range(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    offset: int,
) -> None:
    """A date before the 31-day history or after today is refused."""
    await setup_integration(hass, config_entry)
    with pytest.raises(ServiceValidationError) as info:
        await _list(hass, date=(TODAY - timedelta(days=offset)).isoformat())
    assert info.value.translation_key == "date_out_of_range"


@pytest.mark.parametrize("days", [0, 8])
async def test_list_visits_days_out_of_range(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    days: int,
) -> None:
    """The schema refuses days outside 1 to 7."""
    await setup_integration(hass, config_entry)
    with pytest.raises(probatio.Invalid):
        await _list(hass, days=days)


async def test_list_visits_invalid_cat(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A device that is not a SiiPet cat is refused."""
    await setup_integration(hass, config_entry)
    for device_id in (siipet_device_id(hass, config_entry, "SN0001"), "not-a-device"):
        with pytest.raises(ServiceValidationError) as info:
            await _list(hass, cat=device_id)
        assert info.value.translation_key == "invalid_cat"


async def test_list_visits_cat_of_another_entry(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A device of another config entry is refused, also with the id of a cat."""
    await setup_integration(hass, config_entry)
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={(DOMAIN, "pet-luna")}
    )
    assert device.id != siipet_device_id(hass, config_entry, "pet-luna")
    with pytest.raises(ServiceValidationError) as info:
        await _list(hass, cat=device.id)
    assert info.value.translation_key == "invalid_cat"


async def test_list_visits_has_no_private_values(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The response holds no pet id, serial number, or URL."""
    await setup_integration(hass, config_entry)
    text = json.dumps(await _list(hass, days=7))
    for private in ("pet-luna", "pet-milo", "SN0001", "amazonaws", "events/"):
        assert private not in text


async def test_list_visits_not_loaded(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Without a loaded entry, the action is refused."""
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as info:
        await _list(hass)
    assert info.value.translation_key == "not_loaded"


def _detail(**changes: Any) -> Visit:
    """The fixture visit ev-1: Luna, poop, today at 06:48."""
    return replace(Visit.from_api(load_data("event_detail.json")), **changes)


async def _update(hass: HomeAssistant, **data: Any) -> None:
    await hass.services.async_call(DOMAIN, "update_visit", data, blocking=True)


def _edit_calls(mock_client: AsyncMock) -> list[tuple[str, tuple[Any, ...]]]:
    return [
        (name, args)
        for name, args, _kwargs in mock_client.mock_calls
        if name in ("annotate", "set_note", "delete_visit")
    ]


async def test_update_reassign(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A new cat sends operation 2, checks the result, and refreshes the day."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail(), _detail(pet_ids=("pet-milo",))]
    reads = mock_client.get_day.await_count
    await _update(
        hass, event_id="ev-1", cats=[siipet_device_id(hass, config_entry, "pet-milo")]
    )
    assert _edit_calls(mock_client) == [
        (
            "annotate",
            ("ev-1", 2, {"PetIds": ["pet-milo"], "GonePotty": True, "Manual": True}),
        )
    ]
    assert mock_client.get_visit.await_count == 2
    assert mock_client.get_day.await_count == reads + 1
    assert mock_client.get_day.await_args_list[-1].args[0] == TODAY


async def test_update_type(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Poop to pee sends operation 3 with Type 3."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail(), _detail(type=VisitType.PEE)]
    await _update(hass, event_id="ev-1", type="pee")
    assert _edit_calls(mock_client) == [("annotate", ("ev-1", 3, {"Type": 3}))]


async def test_update_note(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A memo is trimmed and sent alone."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail(), _detail(note="test")]
    await _update(hass, event_id="ev-1", note="  test  ")
    assert _edit_calls(mock_client) == [("set_note", ("ev-1", "test"))]


async def test_update_combined(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Cats, type, and memo go out in the planned order."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [
        _detail(),
        _detail(pet_ids=("pet-milo",), type=VisitType.PEE, note="x"),
    ]
    await _update(
        hass,
        event_id="ev-1",
        cats=[siipet_device_id(hass, config_entry, "pet-milo")],
        type="pee",
        note="x",
    )
    assert _edit_calls(mock_client) == [
        (
            "annotate",
            ("ev-1", 2, {"PetIds": ["pet-milo"], "GonePotty": True, "Manual": True}),
        ),
        ("annotate", ("ev-1", 3, {"Type": 3})),
        ("set_note", ("ev-1", "x")),
    ]


@pytest.mark.parametrize(
    ("visit", "data", "key"),
    [
        (_detail(), {"type": "poop"}, "nothing_to_change"),
        (_detail(type=VisitType.UNKNOWN), {"cats": "milo"}, "type_required"),
    ],
)
async def test_update_not_possible(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    visit: Visit,
    data: dict[str, Any],
    key: str,
) -> None:
    """A request with nothing to change, or cats for an unknown visit, sends nothing."""
    await setup_integration(hass, config_entry)
    if data.get("cats") == "milo":
        data = {"cats": [siipet_device_id(hass, config_entry, "pet-milo")]}
    mock_client.get_visit.side_effect = [visit]
    with pytest.raises(ServiceValidationError) as info:
        await _update(hass, event_id="ev-1", **data)
    assert info.value.translation_key == key
    assert _edit_calls(mock_client) == []


@pytest.mark.parametrize("code", [10000, 40000])
async def test_update_unknown_visit(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    code: int,
) -> None:
    """An unknown or deleted visit is refused."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = SiiPetApiError(code, "")
    with pytest.raises(ServiceValidationError) as info:
        await _update(hass, event_id="ev-x", note="x")
    assert info.value.translation_key == "unknown_visit"


async def test_update_invalid_cat(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The Unknown cat and other devices are not valid cats for an edit."""
    await setup_integration(hass, config_entry)
    for identifier in ("unknown", "SN0001"):
        with pytest.raises(ServiceValidationError) as info:
            await _update(
                hass,
                event_id="ev-1",
                cats=[siipet_device_id(hass, config_entry, identifier)],
            )
        assert info.value.translation_key == "invalid_cat"
    mock_client.get_visit.assert_not_awaited()


@pytest.mark.parametrize(
    "data", [{"note": "x" * 201}, {"cats": []}, {"type": "unknown"}]
)
async def test_update_schema(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    data: dict[str, Any],
) -> None:
    """The schema refuses a long memo, an empty cats list, and an unsupported type."""
    await setup_integration(hass, config_entry)
    with pytest.raises(probatio.Invalid):
        await _update(hass, event_id="ev-1", **data)


async def test_update_not_applied(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A read-back that differs raises an error, and the day still refreshes."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail(), _detail()]
    reads = mock_client.get_day.await_count
    with pytest.raises(HomeAssistantError) as info:
        await _update(hass, event_id="ev-1", type="pee")
    assert info.value.translation_key == "edit_not_applied"
    assert mock_client.get_day.await_count == reads + 1


async def test_update_partial(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A failure after the first call says the visit can be half changed."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail()]
    mock_client.annotate.side_effect = [None, SiiPetConnectionError("down")]
    reads = mock_client.get_day.await_count
    with pytest.raises(HomeAssistantError) as info:
        await _update(
            hass,
            event_id="ev-1",
            cats=[siipet_device_id(hass, config_entry, "pet-milo")],
            type="pee",
        )
    assert info.value.translation_key == "edit_partial"
    assert info.value.translation_placeholders["type"] == "pee"
    assert mock_client.get_day.await_count == reads + 1


async def test_update_partial_reassign_of_pee_visit(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A failed operation 3 after a reassign of a pee visit names the type pee."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail(type=VisitType.PEE)]
    mock_client.annotate.side_effect = [None, SiiPetApiError(1001, "busy")]
    reads = mock_client.get_day.await_count
    with pytest.raises(HomeAssistantError) as info:
        await _update(
            hass,
            event_id="ev-1",
            cats=[siipet_device_id(hass, config_entry, "pet-milo")],
        )
    assert info.value.translation_key == "edit_partial"
    assert info.value.translation_placeholders["type"] == "pee"
    assert mock_client.get_day.await_count == reads + 1


async def test_update_first_call_connection_error(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A connection error on the first of two calls can be a partial change."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail()]
    mock_client.annotate.side_effect = SiiPetConnectionError("timeout")
    reads = mock_client.get_day.await_count
    with pytest.raises(HomeAssistantError) as info:
        await _update(
            hass,
            event_id="ev-1",
            cats=[siipet_device_id(hass, config_entry, "pet-milo")],
            type="pee",
        )
    assert info.value.translation_key == "edit_partial"
    assert info.value.translation_placeholders["type"] == "pee"
    assert mock_client.get_day.await_count == reads + 1


async def test_update_memo_connection_error_names_no_type(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A failed memo edit of an unknown visit asks for no type."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail(type=VisitType.UNKNOWN)]
    mock_client.set_note.side_effect = SiiPetConnectionError("timeout")
    with pytest.raises(HomeAssistantError) as info:
        await _update(hass, event_id="ev-1", note="checked")
    assert info.value.translation_key == "edit_partial_note"
    assert "type" not in info.value.translation_placeholders


async def test_update_read_back_fails(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A failed read-back after all calls says the change is not confirmed."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail(), SiiPetConnectionError("down")]
    reads = mock_client.get_day.await_count
    with pytest.raises(HomeAssistantError) as info:
        await _update(hass, event_id="ev-1", type="pee")
    assert info.value.translation_key == "edit_unconfirmed"
    assert info.value.translation_placeholders["event_id"] == "ev-1"
    assert mock_client.get_day.await_count == reads + 1


async def test_update_clear_note(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """An empty memo clears the memo, and an empty read-back passes."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail(note="old"), _detail(note="")]
    await _update(hass, event_id="ev-1", note="")
    assert _edit_calls(mock_client) == [("set_note", ("ev-1", ""))]


async def test_update_reassign_not_applied(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A read-back that still shows the old cat raises an error."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail(), _detail()]
    with pytest.raises(HomeAssistantError) as info:
        await _update(
            hass,
            event_id="ev-1",
            cats=[siipet_device_id(hass, config_entry, "pet-milo")],
        )
    assert info.value.translation_key == "edit_not_applied"


async def test_update_duplicate_cats(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A cat given twice is sent once."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail(), _detail(pet_ids=("pet-milo",))]
    milo = siipet_device_id(hass, config_entry, "pet-milo")
    await _update(hass, event_id="ev-1", cats=[milo, milo])
    assert _edit_calls(mock_client) == [
        (
            "annotate",
            ("ev-1", 2, {"PetIds": ["pet-milo"], "GonePotty": True, "Manual": True}),
        )
    ]


async def test_update_first_call_fails(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A failure of the first call changes nothing and refreshes nothing."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail()]
    mock_client.annotate.side_effect = SiiPetApiError(1001, "busy")
    reads = mock_client.get_day.await_count
    with pytest.raises(HomeAssistantError) as info:
        await _update(hass, event_id="ev-1", type="pee")
    assert info.value.translation_key == "request_failed"
    assert mock_client.get_day.await_count == reads


async def test_update_auth_error_starts_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """An auth error raises an error and starts reauth."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = SiiPetAuthError("-2: token illegal")
    with pytest.raises(HomeAssistantError):
        await _update(hass, event_id="ev-1", note="x")
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_update_drops_the_calendar_month(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """An edit drops the calendar month of the visit, so the next read calls the API."""
    await setup_integration(hass, config_entry)
    calendar = config_entry.runtime_data.calendar
    await calendar.async_month("pet-luna", TODAY)
    mock_client.get_visit.side_effect = [_detail(), _detail(note="x")]
    await _update(hass, event_id="ev-1", note="x")
    await calendar.async_month("pet-luna", TODAY)
    assert mock_client.get_calendar.await_count == 2


async def test_update_older_visit_drops_its_cached_day(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """An edit of an older visit makes the next list read that day again."""
    await setup_integration(hass, config_entry)
    day = TODAY - timedelta(days=20)
    old = _detail(start=_detail().start - timedelta(days=20))
    await _list(hass, date=day.isoformat())
    mock_client.get_visit.side_effect = [old, replace(old, note="x")]
    await _update(hass, event_id="ev-1", note="x")
    await _list(hass, date=day.isoformat())
    reads = [c for c in mock_client.get_day.await_args_list if c.args[0] == day]
    assert len(reads) == 2


async def _delete(hass: HomeAssistant, **data: Any) -> None:
    await hass.services.async_call(DOMAIN, "delete_visit", data, blocking=True)


async def test_delete_visit(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A delete reads the visit, deletes it, and refreshes its day."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail()]
    reads = mock_client.get_day.await_count
    await _delete(hass, event_id="ev-1")
    assert _edit_calls(mock_client) == [("delete_visit", ("ev-1",))]
    assert mock_client.get_day.await_count == reads + 1
    assert mock_client.get_day.await_args_list[-1].args[0] == TODAY


async def test_delete_visit_removes_the_local_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A delete also removes the local files of the visit."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    assert (day_folder(media_dir) / "ev-1.mp4").exists()
    mock_client.get_visit.side_effect = [_detail()]
    serve_days(mock_client, {})
    await _delete(hass, event_id="ev-1")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert list(day_folder(media_dir).iterdir()) == []


async def test_delete_visit_does_not_wait_for_a_running_download(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """The files of a deleted visit are gone when the action returns."""
    other_video = b"video-ev-2"
    other = mirror_visit(
        event_id="ev-2",
        start=mirror_visit().start - timedelta(hours=1),
        cover_key=None,
        stool_key=None,
        video_key="events/ev-2/video.mp4",
        video_size=len(other_video),
        video_md5=md5_hex(other_video),
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def respond(method: str, url: Any, data: Any) -> StalledResponse:
        return StalledResponse(method, url, other_video, started, release)

    serve_days(mock_client, {TODAY: (mirror_visit(), other)})
    aioclient_mock.get(S3 + "events/ev-2/video.mp4", side_effect=respond)
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7, wait_for_downloads=False)
    await asyncio.wait_for(started.wait(), timeout=1)

    mock_client.get_visit.side_effect = [_detail()]
    serve_days(mock_client, {TODAY: (other,)})
    await _delete(hass, event_id="ev-1")
    assert sorted(path.name for path in day_folder(media_dir).iterdir()) == [
        "ev-2.mp4.part"
    ]

    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert (day_folder(media_dir) / "ev-2.mp4").read_bytes() == other_video


async def test_failed_delete_keeps_the_local_copy(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    media_dir: Path,
) -> None:
    """A delete that SiiPet refuses keeps the local files."""
    serve_days(mock_client, {TODAY: (mirror_visit(),)})
    mock_s3(aioclient_mock)
    await setup_mirror(hass, config_entry, 7)
    mock_client.get_visit.side_effect = [_detail()]
    mock_client.delete_visit.side_effect = SiiPetConnectionError("down")
    with pytest.raises(HomeAssistantError):
        await _delete(hass, event_id="ev-1")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert (day_folder(media_dir) / "ev-1.mp4").exists()


async def test_delete_unknown_visit(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """An unknown or deleted visit is refused, and nothing is deleted."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = SiiPetApiError(40000, "")
    with pytest.raises(ServiceValidationError) as info:
        await _delete(hass, event_id="ev-x")
    assert info.value.translation_key == "unknown_visit"
    assert _edit_calls(mock_client) == []


async def test_delete_fails(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A failed delete raises a translated error and refreshes nothing."""
    await setup_integration(hass, config_entry)
    mock_client.get_visit.side_effect = [_detail()]
    mock_client.delete_visit.side_effect = SiiPetConnectionError("down")
    reads = mock_client.get_day.await_count
    with pytest.raises(HomeAssistantError) as info:
        await _delete(hass, event_id="ev-1")
    assert info.value.translation_key == "request_failed"
    assert mock_client.get_day.await_count == reads


async def test_delete_needs_admin(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    hass_read_only_user: User,
) -> None:
    """A user who is not an admin cannot delete a visit."""
    await setup_integration(hass, config_entry)
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "delete_visit",
            {"event_id": "ev-1"},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    mock_client.get_visit.assert_not_awaited()
    assert _edit_calls(mock_client) == []
