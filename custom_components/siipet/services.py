"""Actions of the SiiPet integration."""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.util import dt as dt_util
import probatio

from .api import (
    SiiPetApiError,
    SiiPetAuthError,
    SiiPetClient,
    SiiPetConnectionError,
    SiiPetError,
    Visit,
    VisitType,
)
from .api.edits import Annotate, EditCall, EditNotPossible, plan_edit
from .const import DOMAIN, UNKNOWN_CAT_ID, UNKNOWN_CAT_NAME
from .coordinator import SiiPetConfigEntry, SiiPetRuntime
from .visit_data import (
    HISTORY_DAYS,
    async_read_day,
    cat_id,
    check_history_day,
    device_ids,
    loaded_entry,
    visit_dict,
)

SERVICE_LIST_VISITS = "list_visits"
SERVICE_UPDATE_VISIT = "update_visit"
SERVICE_DELETE_VISIT = "delete_visit"

ATTR_CAT = "cat"
ATTR_CATS = "cats"
ATTR_DATE = "date"
ATTR_DAYS = "days"
ATTR_EVENT_ID = "event_id"
ATTR_NOTE = "note"
ATTR_TYPE = "type"

NOTE_MAX_LENGTH = 200
# Detail codes for an event id that does not exist, and for a deleted visit.
UNKNOWN_VISIT_CODES = frozenset({10000, 40000})
VISIT_TYPES = {
    "pee": VisitType.PEE,
    "poop": VisitType.POOP,
    "lingering": VisitType.LINGERING,
}

LIST_VISITS_SCHEMA = probatio.Schema(
    {
        probatio.Optional(ATTR_DATE): cv.date,
        probatio.Optional(ATTR_DAYS, default=1): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=7)
        ),
        probatio.Optional(ATTR_CAT): cv.string,
    }
)


UPDATE_VISIT_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_EVENT_ID): cv.string,
        probatio.Optional(ATTR_CATS): probatio.All(
            cv.ensure_list, [cv.string], probatio.Length(min=1)
        ),
        probatio.Optional(ATTR_TYPE): probatio.In(list(VISIT_TYPES)),
        probatio.Optional(ATTR_NOTE): probatio.All(
            cv.string, probatio.Length(max=NOTE_MAX_LENGTH)
        ),
    }
)

DELETE_VISIT_SCHEMA = probatio.Schema({probatio.Required(ATTR_EVENT_ID): cv.string})


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the SiiPet actions."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_VISITS,
        _async_list_visits,
        schema=LIST_VISITS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_VISIT,
        _async_update_visit,
        schema=UPDATE_VISIT_SCHEMA,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_DELETE_VISIT,
        _async_delete_visit,
        schema=DELETE_VISIT_SCHEMA,
    )


async def _async_list_visits(call: ServiceCall) -> ServiceResponse:
    """Return the visits of up to 7 days that end on `date`, newest first."""
    hass = call.hass
    entry = loaded_entry(hass)
    runtime = entry.runtime_data
    data = runtime.coordinator.data
    last: date = call.data.get(ATTR_DATE, data.today)
    check_history_day(data, last)
    cat_filter = None
    if ATTR_CAT in call.data:
        cat_filter = cat_id(hass, entry, call.data[ATTR_CAT], allow_unknown=True)
    first = data.today - timedelta(days=HISTORY_DAYS)
    visits: list[Visit] = []
    for offset in range(call.data[ATTR_DAYS]):
        day = last - timedelta(days=offset)
        if day < first:
            # The server keeps no older visits, so the read would be empty.
            break
        visits.extend(await async_read_day(hass, entry, day))
    if cat_filter is not None:
        visits = [visit for visit in visits if cat_filter in data.cat_ids(visit)]
    devices = device_ids(hass, entry)
    cats = [
        {"device_id": devices.get(pet_id), "name": cat.name, "unknown": False}
        for pet_id, cat in data.cats.items()
    ]
    cats.append(
        {
            "device_id": devices.get(UNKNOWN_CAT_ID),
            "name": UNKNOWN_CAT_NAME,
            "unknown": True,
        }
    )
    return {
        "cats": cats,
        "visits": [visit_dict(data, devices, visit) for visit in visits],
    }


def _request_failed(
    hass: HomeAssistant,
    entry: SiiPetConfigEntry,
    err: SiiPetError,
    key: str,
    event_id: str,
    **placeholders: str,
) -> HomeAssistantError:
    """Return the translated error for a failed request, and start reauth on auth errors."""
    if isinstance(err, SiiPetAuthError):
        entry.async_start_reauth(hass)
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={
            "event_id": event_id,
            "error": str(err),
            **placeholders,
        },
    )


async def _async_read_visit(
    hass: HomeAssistant, entry: SiiPetConfigEntry, event_id: str
) -> Visit:
    try:
        return await entry.runtime_data.client.get_visit(event_id)
    except SiiPetApiError as err:
        if err.code in UNKNOWN_VISIT_CODES:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_visit",
                translation_placeholders={"event_id": event_id},
            ) from err
        raise _request_failed(hass, entry, err, "request_failed", event_id) from err
    except SiiPetError as err:
        raise _request_failed(hass, entry, err, "request_failed", event_id) from err


async def _async_send(client: SiiPetClient, event_id: str, edit: EditCall) -> None:
    if isinstance(edit, Annotate):
        await client.annotate(event_id, edit.operation, edit.result)
    else:
        await client.set_note(event_id, edit.note)


async def _async_after_change(runtime: SiiPetRuntime, visit: Visit) -> None:
    """Show the change: drop the cached day and month, and read the day again."""
    day = dt_util.as_local(visit.start).date()
    runtime.media.forget_day(day)
    runtime.calendar.forget(day)
    await runtime.coordinator.async_refresh_day(day)


def _applied(
    visit: Visit,
    target: VisitType | None,
    cats: list[str] | None,
    note: str | None,
) -> bool:
    """Return True when the visit shows the requested type, cats, and memo."""
    if target is not None and visit.type is not target:
        return False
    if cats is not None and set(visit.pet_ids) != set(cats):
        return False
    return note is None or visit.note == note


async def _async_update_visit(call: ServiceCall) -> None:
    """Change the cats, the type, or the memo of a visit."""
    hass = call.hass
    entry = loaded_entry(hass)
    runtime = entry.runtime_data
    event_id = call.data[ATTR_EVENT_ID]
    cats = None
    if ATTR_CATS in call.data:
        cats = list(
            dict.fromkeys(
                cat_id(hass, entry, device_id, allow_unknown=False)
                for device_id in call.data[ATTR_CATS]
            )
        )
    visit_type = VISIT_TYPES[call.data[ATTR_TYPE]] if ATTR_TYPE in call.data else None
    note = call.data[ATTR_NOTE].strip() if ATTR_NOTE in call.data else None
    visit = await _async_read_visit(hass, entry, event_id)
    try:
        edits = plan_edit(visit, cats=cats, visit_type=visit_type, note=note)
    except EditNotPossible as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key=err.reason
        ) from err
    sent = 0
    try:
        for edit in edits:
            await _async_send(runtime.client, event_id, edit)
            sent += 1
    except SiiPetError as err:
        if not sent and not isinstance(err, SiiPetConnectionError):
            raise _request_failed(hass, entry, err, "request_failed", event_id) from err
        # A timeout or an HTTP error does not prove that SiiPet skipped the
        # call. A retry without the type can plan from a half-changed visit,
        # so the error names the type to ask for. A memo edit has no type.
        if any(isinstance(edit, Annotate) for edit in edits):
            requested = visit_type if visit_type is not None else visit.type
            error = _request_failed(
                hass, entry, err, "edit_partial", event_id, type=requested.key
            )
        else:
            error = _request_failed(hass, entry, err, "edit_partial_note", event_id)
        await _async_after_change(runtime, visit)
        raise error from err
    try:
        check = await runtime.client.get_visit(event_id)
    except SiiPetError as err:
        raise _request_failed(hass, entry, err, "edit_unconfirmed", event_id) from err
    finally:
        await _async_after_change(runtime, visit)
    target = None
    if cats is not None or visit_type is not None:
        target = visit_type if visit_type is not None else visit.type
    if not _applied(check, target, cats, note):
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="edit_not_applied",
            translation_placeholders={"event_id": event_id},
        )


async def _async_delete_visit(call: ServiceCall) -> None:
    """Delete a visit for good."""
    hass = call.hass
    entry = loaded_entry(hass)
    runtime = entry.runtime_data
    event_id = call.data[ATTR_EVENT_ID]
    visit = await _async_read_visit(hass, entry, event_id)
    try:
        await runtime.client.delete_visit(event_id)
    except SiiPetError as err:
        raise _request_failed(hass, entry, err, "request_failed", event_id) from err
    if runtime.mirror is not None:
        await runtime.mirror.async_forget(event_id)
    await _async_after_change(runtime, visit)
