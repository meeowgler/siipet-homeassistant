"""Websocket commands that feed the SiiPet dashboard card."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import date, timedelta
import functools
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
import probatio

from .api import SiiPetAuthError, SiiPetError, Visit, VisitType
from .const import DOMAIN, UNKNOWN_CAT_ID
from .coordinator import SiiPetConfigEntry, SiiPetData
from .media import MediaKind
from .views import image_path
from .visit_data import (
    HISTORY_DAYS,
    async_read_day,
    camera_labels,
    cat_id,
    check_history_day,
    device_ids,
    loaded_entry,
    visit_dict,
)

# Long enough for a dashboard that stays open. The card must read again before the paths expire.
SIGNED_PATH_LIFETIME = timedelta(hours=1)
# The calendar offers the current month and this many months before it.
CALENDAR_MONTHS = 12

type _Handler = Callable[
    [HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Awaitable[None]
]


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register the websocket commands of the card."""
    websocket_api.async_register_command(hass, ws_cats)
    websocket_api.async_register_command(hass, ws_calendar)
    websocket_api.async_register_command(hass, ws_day)
    websocket_api.async_register_command(hass, ws_queue)
    websocket_api.async_register_command(hass, ws_visit)


def _translated_errors(handler: _Handler) -> _Handler:
    """Send translated errors like call_service does, without an error in the log."""

    @functools.wraps(handler)
    async def wrapper(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        try:
            await handler(hass, connection, msg)
        except HomeAssistantError as err:
            code = (
                websocket_api.ERR_SERVICE_VALIDATION_ERROR
                if isinstance(err, ServiceValidationError)
                else websocket_api.ERR_HOME_ASSISTANT_ERROR
            )
            connection.send_error(
                msg["id"],
                code,
                str(err),
                translation_key=err.translation_key,
                translation_domain=err.translation_domain,
                translation_placeholders=err.translation_placeholders,
            )

    return wrapper


def _signed(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    kind: MediaKind,
    item_id: str,
) -> str:
    return async_sign_path(
        hass,
        image_path(kind, item_id),
        SIGNED_PATH_LIFETIME,
        refresh_token_id=connection.refresh_token_id,
    )


def _card_visits(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    entry: SiiPetConfigEntry,
    visits: Iterable[Visit],
) -> list[dict[str, Any]]:
    """Return visit dicts with signed paths of their cover and stool images.

    `camera` holds the label from `camera_labels`, or None.
    """
    data = entry.runtime_data.coordinator.data
    devices = device_ids(hass, entry)
    labels = camera_labels(hass, entry)
    return [
        {
            **visit_dict(data, devices, visit),
            "camera": labels.get(visit.sn),
            "cover": _signed(hass, connection, MediaKind.COVER, visit.event_id)
            if visit.cover_key
            else None,
            "stool": _signed(hass, connection, MediaKind.STOOL, visit.event_id)
            if visit.stool_key
            else None,
        }
        for visit in visits
    ]


def _summary(visits: Iterable[Visit]) -> dict[str, int]:
    """Count the visits like the calendar does: pee and poop only."""
    visits = list(visits)
    return {
        "visits": sum(visit.type.is_litter_use for visit in visits),
        "pee": sum(visit.type is VisitType.PEE for visit in visits),
        "poop": sum(visit.type is VisitType.POOP for visit in visits),
        "abnormal": sum(visit.abnormal for visit in visits),
    }


@websocket_api.websocket_command({probatio.Required("type"): "siipet/cats"})
@websocket_api.async_response
@_translated_errors
async def ws_cats(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the cats with signed avatar paths, the waiting visits, and the update status."""
    entry = loaded_entry(hass)
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    devices = device_ids(hass, entry)
    connection.send_result(
        msg["id"],
        {
            "cats": [
                {
                    "device_id": devices.get(pet_id),
                    "name": cat.name,
                    "avatar": _signed(hass, connection, MediaKind.AVATAR, pet_id)
                    if cat.avatar_key
                    else None,
                }
                for pet_id, cat in data.cats.items()
            ],
            "unknown": {
                "device_id": devices.get(UNKNOWN_CAT_ID),
                "waiting": len(data.visits(UNKNOWN_CAT_ID)),
            },
            "today": data.today.isoformat(),
            "available": coordinator.last_update_success,
            "updated_at": data.updated_at.isoformat(),
        },
    )


def _month(value: Any) -> date:
    """Validate a `YYYY-MM` month and return its first day."""
    try:
        return date.fromisoformat(f"{cv.string(value)}-01")
    except ValueError as err:
        raise probatio.Invalid("Expected a month as YYYY-MM") from err


def _check_calendar_month(data: SiiPetData, month: date) -> None:
    """Raise date_out_of_range unless `month` is the current month or one of the CALENDAR_MONTHS before it."""
    # Step back in whole months, which timedelta cannot do.
    index = data.today.year * 12 + data.today.month - 1 - CALENDAR_MONTHS
    first = date(index // 12, index % 12 + 1, 1)
    if not first <= month <= data.today:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="date_out_of_range",
            translation_placeholders={
                "first": first.isoformat(),
                "last": data.today.isoformat(),
            },
        )


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "siipet/calendar",
        probatio.Required("month"): _month,
        probatio.Optional("cat"): cv.string,
    }
)
@websocket_api.async_response
@_translated_errors
async def ws_calendar(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the pee and poop counts and the markers of each day of a month.

    Without a cat, the counts add up per cat, so a visit of two cats counts
    twice and visits without a cat are missing.
    """
    entry = loaded_entry(hass)
    runtime = entry.runtime_data
    data = runtime.coordinator.data
    _check_calendar_month(data, msg["month"])
    pet_ids = list(data.cats)
    if "cat" in msg:
        owner = cat_id(hass, entry, msg["cat"], allow_unknown=True)
        # The Unknown cat has no pet id, so the API has no calendar for it.
        pet_ids = [] if owner == UNKNOWN_CAT_ID else [owner]
    try:
        # In parallel, so one slow answer does not add up over the cats.
        months = await asyncio.gather(
            *(runtime.calendar.async_month(pet_id, msg["month"]) for pet_id in pet_ids)
        )
    except SiiPetError as err:
        if isinstance(err, SiiPetAuthError):
            entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="request_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    days: dict[str, dict[str, Any]] = {}
    for month in months:
        for day in month:
            total = days.setdefault(
                day.date.isoformat(), {"visits": 0, "abnormal": 0, "marked": False}
            )
            total["visits"] += day.normal + day.abnormal
            total["abnormal"] += day.abnormal
            total["marked"] = total["marked"] or day.abnormal > 0 or day.flagged
    connection.send_result(
        msg["id"],
        {
            "days": days,
            "first": (data.today - timedelta(days=HISTORY_DAYS)).isoformat(),
            "last": data.today.isoformat(),
        },
    )


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "siipet/day",
        probatio.Required("date"): cv.date,
        probatio.Optional("cat"): cv.string,
    }
)
@websocket_api.async_response
@_translated_errors
async def ws_day(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the visits of one day, newest first, with a summary."""
    entry = loaded_entry(hass)
    runtime = entry.runtime_data
    check_history_day(runtime.coordinator.data, msg["date"])
    owner = None
    if "cat" in msg:
        owner = cat_id(hass, entry, msg["cat"], allow_unknown=True)
    visits = await async_read_day(hass, entry, msg["date"])
    data = runtime.coordinator.data
    if owner is not None:
        visits = tuple(visit for visit in visits if owner in data.cat_ids(visit))
    connection.send_result(
        msg["id"],
        {
            "summary": _summary(visits),
            "visits": _card_visits(hass, connection, entry, visits),
        },
    )


@websocket_api.websocket_command({probatio.Required("type"): "siipet/queue"})
@websocket_api.async_response
@_translated_errors
async def ws_queue(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the visits of the window without a cat, newest first."""
    entry = loaded_entry(hass)
    data = entry.runtime_data.coordinator.data
    visits = sorted(
        data.visits(UNKNOWN_CAT_ID), key=lambda visit: visit.start, reverse=True
    )
    connection.send_result(
        msg["id"],
        {"visits": _card_visits(hass, connection, entry, visits)},
    )


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "siipet/visit",
        probatio.Required("event_id"): cv.string,
    }
)
@websocket_api.async_response
@_translated_errors
async def ws_visit(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return one visit of the window and the day that holds it."""
    entry = loaded_entry(hass)
    data = entry.runtime_data.coordinator.data
    for day, visits in data.days.items():
        for visit in visits:
            if visit.event_id == msg["event_id"]:
                [card_visit] = _card_visits(hass, connection, entry, [visit])
                connection.send_result(
                    msg["id"], {"date": day.isoformat(), "visit": card_visit}
                )
                return
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="visit_not_in_window",
        translation_placeholders={"event_id": msg["event_id"]},
    )
