"""Tests for the SiiPet API client."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date, time
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
)
from yarl import URL

from custom_components.siipet.api import (
    Session,
    SiiPetApiError,
    SiiPetAuthError,
    SiiPetClient,
    SiiPetConnectionError,
    SiiPetError,
)
from custom_components.siipet.api.client import BASE_URL

from ..common import load_data, load_fixture

NOW_MS = 1_790_424_000_000  # 2026-09-26T12:00:00Z
TOKEN = load_data("login.json")["Token"]
FRESH = Session(TOKEN, NOW_MS + 10 * 86_400_000)
DUE = Session(TOKEN, NOW_MS + 3_600_000)
OK_EMPTY = {"Code": 0, "Msg": "success", "Data": {}}


def url(path: str) -> str:
    return f"{BASE_URL}/api/v1/{path}"


def calls(mocked: AiohttpClientMocker, path: str) -> list[tuple[Any, dict[str, str]]]:
    """Return the body and headers of each recorded request to a path."""
    target = URL(url(path))
    return [
        (data, headers)
        for _method, call_url, data, headers in mocked.mock_calls
        if call_url == target
    ]


@pytest.fixture
async def websession(
    aioclient_mock: AiohttpClientMocker,
) -> AsyncIterator[aiohttp.ClientSession]:
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield session
    await session.close()


def make_client(
    websession: aiohttp.ClientSession,
    session: Session | None = FRESH,
    updates: list[Session] | None = None,
) -> SiiPetClient:
    return SiiPetClient(
        websession,
        client_id="client-uuid-0001",
        time_zone="Europe/Warsaw",
        session=session,
        on_session_update=updates.append if updates is not None else None,
        clock=lambda: NOW_MS / 1000,
    )


async def test_headers_and_envelope(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A request carries the app headers and returns the envelope data."""
    aioclient_mock.post(url("user/pet/sync"), json=load_fixture("pet_sync.json"))
    cats = await make_client(websession).get_cats()
    assert list(cats) == ["pet-luna", "pet-milo"]
    [(body, headers)] = calls(aioclient_mock, "user/pet/sync")
    assert body == {}
    assert headers["authorization"] == f"Bearer {TOKEN}"
    assert headers["x-device-identifier"] == "client-uuid-0001"
    assert headers["x-timezone"] == "Europe/Warsaw"
    assert headers["x-timestamp"] == str(NOW_MS)
    assert headers["x-app-version"] == "2.1.5"
    assert headers["user-agent"] == "lc01-app/2.1.5"
    assert headers["x-device-os"] == "iOS 27.0"
    assert headers["x-device-model"] == "android-phone Home Assistant"


async def test_get_cameras(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Cameras are keyed by serial number."""
    aioclient_mock.post(url("user/device/sync"), json=load_fixture("device_sync.json"))
    cameras = await make_client(websession).get_cameras()
    assert list(cameras) == ["SN0001", "SN0002"]


async def test_get_day(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The day request uses local midnight and the app flags."""
    aioclient_mock.post(
        url("pet/toilet/event"), json=load_fixture("toilet_event_day.json")
    )
    day = await make_client(websession).get_day(date(2026, 9, 26))
    assert len(day.visits) == 6
    [(body, _headers)] = calls(aioclient_mock, "pet/toilet/event")
    assert body == {
        "IncludeLocal": True,
        "FollowRegisterTimezone": True,
        "Date": "2026-09-26 00:00:00",
    }


async def test_get_day_until(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The day request can carry a time of day for the summaries."""
    aioclient_mock.post(
        url("pet/toilet/event"), json=load_fixture("toilet_event_day.json")
    )
    await make_client(websession).get_day(
        date(2026, 9, 26), until=time(18, 41, 34, 999_999)
    )
    [(body, _headers)] = calls(aioclient_mock, "pet/toilet/event")
    assert body["Date"] == "2026-09-26 18:41:34"


async def test_get_visit(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The detail request sends the event id."""
    aioclient_mock.post(
        url("device/toilet/event/detail"), json=load_fixture("event_detail.json")
    )
    visit = await make_client(websession).get_visit("ev-1")
    assert visit.event_id == "ev-1"
    [(body, _headers)] = calls(aioclient_mock, "device/toilet/event/detail")
    assert body == {"EventId": "ev-1"}


async def test_get_abnormal_labels(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Labels come from the system config."""
    aioclient_mock.post(
        url("config/system/config"), json=load_fixture("system_config.json")
    )
    labels = await make_client(websession).get_abnormal_labels()
    assert labels.event == {301: "Potty Overtime"}


async def test_get_media_credentials(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The media credentials call sends an empty body with the bearer token."""
    aioclient_mock.post(url("config/aws/auth"), json=load_fixture("aws_auth.json"))
    credentials = await make_client(websession).get_media_credentials()
    assert credentials.bucket == "media-bucket"
    [(body, headers)] = calls(aioclient_mock, "config/aws/auth")
    assert body == {}
    assert headers["authorization"] == f"Bearer {TOKEN}"


async def test_get_iot_credentials(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The IoT credentials call sends an empty body with the bearer token."""
    aioclient_mock.post(url("config/aws/auth"), json=load_fixture("aws_auth.json"))
    credentials = await make_client(websession).get_iot_credentials()
    assert credentials.endpoint == "example-ats.iot.us-east-1.amazonaws.com"
    assert credentials.identity_id == "us-east-1:identity-0001"
    [(body, headers)] = calls(aioclient_mock, "config/aws/auth")
    assert body == {}
    assert headers["authorization"] == f"Bearer {TOKEN}"


async def test_get_calendar(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The calendar request covers whole days and ends at midnight after the last day."""
    aioclient_mock.post(
        url("pet/toilet/data/calendar"), json=load_fixture("pet_calendar.json")
    )
    days = await make_client(websession).get_calendar(
        "pet-luna", date(2026, 9, 1), date(2026, 9, 30)
    )
    assert [day.date for day in days] == [
        date(2026, 9, 24),
        date(2026, 9, 25),
        date(2026, 9, 26),
    ]
    [(body, headers)] = calls(aioclient_mock, "pet/toilet/data/calendar")
    assert body == {
        "PetId": "pet-luna",
        "StartDate": "2026-09-01 00:00:00",
        "EndDate": "2026-10-01 00:00:00",
        "IncludeLocal": True,
        "FollowRegisterTimezone": True,
    }
    assert headers["authorization"] == f"Bearer {TOKEN}"


async def test_get_calendar_without_days(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A month without visits comes back as null and becomes an empty result."""
    aioclient_mock.post(
        url("pet/toilet/data/calendar"),
        json=_envelope({"PetId": "pet-luna", "DataCalendar": None}),
    )
    days = await make_client(websession).get_calendar(
        "pet-luna", date(2026, 8, 1), date(2026, 8, 31)
    )
    assert days == ()


async def test_annotate(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Annotate sends the operation and the result as a compact JSON string."""
    aioclient_mock.post(url("pet/toilet/event/annotate"), json=OK_EMPTY)
    await make_client(websession).annotate(
        "ev-1", 2, {"PetIds": ["pet-milo"], "GonePotty": True, "Manual": True}
    )
    [(body, headers)] = calls(aioclient_mock, "pet/toilet/event/annotate")
    assert body == {
        "EventId": "ev-1",
        "Type": 2,
        "Result": '{"PetIds":["pet-milo"],"GonePotty":true,"Manual":true}',
    }
    assert headers["authorization"] == f"Bearer {TOKEN}"


async def test_set_note(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The memo edit sends the event id and the note."""
    aioclient_mock.post(url("pet/toilet/event/edit"), json=OK_EMPTY)
    await make_client(websession).set_note("ev-1", "")
    [(body, _headers)] = calls(aioclient_mock, "pet/toilet/event/edit")
    assert body == {"EventId": "ev-1", "Note": ""}


async def test_delete_visit(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The delete sends the event id to the device delete endpoint."""
    aioclient_mock.post(url("device/toilet/event/delete"), json=OK_EMPTY)
    await make_client(websession).delete_visit("ev-1")
    [(body, _headers)] = calls(aioclient_mock, "device/toilet/event/delete")
    assert body == {"EventId": "ev-1"}


@pytest.mark.parametrize(
    ("path", "call"),
    [
        ("pet/toilet/event/annotate", lambda c: c.annotate("ev-1", 3, {"Type": 3})),
        ("pet/toilet/event/edit", lambda c: c.set_note("ev-1", "x")),
        ("device/toilet/event/delete", lambda c: c.delete_visit("ev-1")),
    ],
)
async def test_edit_rejected(
    websession: aiohttp.ClientSession,
    aioclient_mock: AiohttpClientMocker,
    path: str,
    call: Any,
) -> None:
    """A rejected edit raises SiiPetApiError with the envelope code."""
    aioclient_mock.post(url(path), json={"Code": 40000, "Msg": "expired", "Data": None})
    with pytest.raises(SiiPetApiError) as info:
        await call(make_client(websession))
    assert info.value.code == 40000


async def test_api_error(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A non-zero code raises SiiPetApiError with code and message."""
    aioclient_mock.post(
        url("user/pet/sync"), json={"Code": 1234, "Msg": "bad request", "Data": None}
    )
    with pytest.raises(SiiPetApiError) as err:
        await make_client(websession).get_cats()
    assert (err.value.code, err.value.msg) == (1234, "bad request")


@pytest.mark.parametrize("code", [-2, -4])
async def test_envelope_auth_error(
    websession: aiohttp.ClientSession,
    aioclient_mock: AiohttpClientMocker,
    code: int,
) -> None:
    """Envelope codes -2 and -4 raise SiiPetAuthError."""
    aioclient_mock.post(
        url("user/pet/sync"), json={"Code": code, "Msg": "token illegal", "Data": None}
    )
    with pytest.raises(SiiPetAuthError):
        await make_client(websession).get_cats()


@pytest.mark.parametrize("status", [401, 403])
async def test_http_auth_error(
    websession: aiohttp.ClientSession,
    aioclient_mock: AiohttpClientMocker,
    status: int,
) -> None:
    """HTTP 401 and 403 raise SiiPetAuthError."""
    aioclient_mock.post(url("user/pet/sync"), status=status)
    with pytest.raises(SiiPetAuthError):
        await make_client(websession).get_cats()


async def test_http_server_error(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """HTTP 500 raises SiiPetConnectionError."""
    aioclient_mock.post(url("user/pet/sync"), status=500)
    with pytest.raises(SiiPetConnectionError):
        await make_client(websession).get_cats()


@pytest.mark.parametrize("exc", [TimeoutError(), aiohttp.ClientConnectionError()])
async def test_connection_failure(
    websession: aiohttp.ClientSession,
    aioclient_mock: AiohttpClientMocker,
    exc: Exception,
) -> None:
    """A timeout or a connection error raises SiiPetConnectionError."""
    aioclient_mock.post(url("user/pet/sync"), exc=exc)
    with pytest.raises(SiiPetConnectionError):
        await make_client(websession).get_cats()


async def test_invalid_json(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A body that is not JSON raises SiiPetConnectionError."""
    aioclient_mock.post(url("user/pet/sync"), text="<html>")
    with pytest.raises(SiiPetConnectionError):
        await make_client(websession).get_cats()


def _envelope(data: Any) -> dict[str, Any]:
    return {"Code": 0, "Msg": "success", "Data": data}


@pytest.mark.parametrize(
    ("path", "response", "call"),
    [
        ("user/pet/sync", {"Code": "zero", "Msg": ""}, lambda c: c.get_cats()),
        ("user/pet/sync", _envelope(None), lambda c: c.get_cats()),
        (
            "user/pet/sync",
            _envelope({"List": [{"Name": "Luna"}]}),
            lambda c: c.get_cats(),
        ),
        (
            "user/device/sync",
            _envelope({"List": [{"DeviceName": "Hall"}]}),
            lambda c: c.get_cameras(),
        ),
        (
            "pet/toilet/event",
            _envelope({"List": [{"SN": "SN0001"}]}),
            lambda c: c.get_day(date(2026, 9, 26)),
        ),
        ("device/toilet/event/detail", _envelope(None), lambda c: c.get_visit("ev-1")),
        (
            "config/system/config",
            _envelope({"Memory": {"AbnormalToilet": [{"Shape": [{"Type": "x"}]}]}}),
            lambda c: c.get_abnormal_labels(),
        ),
        (
            "user/email/register/login",
            _envelope({"ExpireAt": 1}),
            lambda c: c.login("cat@example.com", "012345"),
        ),
        (
            "user/email/register/login",
            _envelope({"Token": None, "ExpireAt": 1}),
            lambda c: c.login("cat@example.com", "012345"),
        ),
        (
            "user/email/register/login",
            _envelope({"Token": "", "ExpireAt": 1}),
            lambda c: c.login("cat@example.com", "012345"),
        ),
        (
            "user/client/verify",
            _envelope(None),
            lambda c: c.request_email_code("cat@example.com"),
        ),
        (
            "config/aws/auth",
            _envelope({"S3": {"S3Bucket": "media-bucket"}}),
            lambda c: c.get_media_credentials(),
        ),
        (
            "config/aws/auth",
            _envelope({"IdentityId": "id", "IotCore": {"Endpoint": "https://x"}}),
            lambda c: c.get_iot_credentials(),
        ),
        (
            "pet/toilet/data/calendar",
            _envelope({"DataCalendar": [{"Normal": 1}]}),
            lambda c: c.get_calendar("pet-luna", date(2026, 9, 1), date(2026, 9, 30)),
        ),
    ],
)
async def test_malformed_response(
    websession: aiohttp.ClientSession,
    aioclient_mock: AiohttpClientMocker,
    path: str,
    response: dict[str, Any],
    call: Any,
) -> None:
    """A response without the documented shape raises SiiPetError."""
    aioclient_mock.post(url(path), json=response)
    with pytest.raises(SiiPetError, match=f"Unexpected response from /api/v1/{path}"):
        await call(make_client(websession))


async def test_own_error_is_not_a_malformed_response(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """An error in the challenge encryption is not reported as a bad response."""
    aioclient_mock.post(
        url("user/client/verify"),
        json=_envelope({"ClientId": "client-1", "VerifyCode": "code"}),
    )
    with (
        patch(
            "custom_components.siipet.api.client.encrypt_challenge",
            side_effect=ValueError("bad key"),
        ),
        pytest.raises(ValueError, match="bad key"),
    ):
        await make_client(websession, session=None).request_email_code(
            "cat@example.com"
        )


async def test_no_session(websession: aiohttp.ClientSession) -> None:
    """An authenticated call without a session raises SiiPetAuthError."""
    with pytest.raises(SiiPetAuthError):
        await make_client(websession, session=None).get_cats()


async def test_request_email_code(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """The code request solves the challenge and sends no token."""
    aioclient_mock.post(
        url("user/client/verify"), json=load_fixture("client_verify.json")
    )
    aioclient_mock.post(url("user/email/send/trustworthy"), json=OK_EMPTY)
    await make_client(websession, session=None).request_email_code("cat@example.com")
    [(verify_body, verify_headers)] = calls(aioclient_mock, "user/client/verify")
    [(send_body, send_headers)] = calls(aioclient_mock, "user/email/send/trustworthy")
    assert verify_body == {}
    assert "authorization" not in verify_headers
    assert "authorization" not in send_headers
    assert send_body["Scene"] == 0
    assert send_body["ClientId"] == "client-0001"
    assert send_body["Email"] == "cat@example.com"
    assert len(send_body["VerifyCiphertext"]) == 80


async def test_login(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Login sends the code as a string and keeps the session."""
    aioclient_mock.post(
        url("user/email/register/login"), json=load_fixture("login.json")
    )
    client = make_client(websession, session=None)
    session = await client.login("cat@example.com", "012345")
    [(body, headers)] = calls(aioclient_mock, "user/email/register/login")
    assert body == {"Code": "012345", "Email": "cat@example.com"}
    assert "authorization" not in headers
    assert session.user_id == "user-0001"
    assert client.session == session


async def test_renewal_when_due(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A due session renews first, reports the new session, and uses it."""
    updates: list[Session] = []
    refreshed = load_data("token_refresh.json")
    aioclient_mock.post(
        url("user/token/refresh"), json=load_fixture("token_refresh.json")
    )
    aioclient_mock.post(url("user/pet/sync"), json=load_fixture("pet_sync.json"))
    await make_client(websession, session=DUE, updates=updates).get_cats()
    [(refresh_body, refresh_headers)] = calls(aioclient_mock, "user/token/refresh")
    [(_body, sync_headers)] = calls(aioclient_mock, "user/pet/sync")
    assert refresh_body == {}
    assert refresh_headers["authorization"] == f"Bearer {TOKEN}"
    assert sync_headers["authorization"] == f"Bearer {refreshed['Token']}"
    assert updates == [Session(refreshed["Token"], refreshed["ExpireAt"])]


async def test_no_renewal_when_fresh(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A fresh session does not renew."""
    aioclient_mock.post(url("user/pet/sync"), json=load_fixture("pet_sync.json"))
    await make_client(websession).get_cats()
    assert calls(aioclient_mock, "user/token/refresh") == []


async def test_one_renewal_for_parallel_calls(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """Parallel calls on a due session renew once."""
    updates: list[Session] = []
    aioclient_mock.post(
        url("user/token/refresh"), json=load_fixture("token_refresh.json")
    )
    aioclient_mock.post(url("user/pet/sync"), json=load_fixture("pet_sync.json"))
    client = make_client(websession, session=DUE, updates=updates)
    await asyncio.gather(client.get_cats(), client.get_cats(), client.get_cats())
    assert len(calls(aioclient_mock, "user/token/refresh")) == 1
    assert len(calls(aioclient_mock, "user/pet/sync")) == 3
    assert len(updates) == 1


@pytest.mark.parametrize(
    "refresh",
    [
        {"exc": aiohttp.ClientConnectionError()},
        {"json": {"Code": 1001, "Msg": "busy", "Data": None}},
        {"json": {"Code": 0, "Msg": "success", "Data": None}},
    ],
    ids=["connection", "api-error", "malformed"],
)
async def test_renewal_failure_keeps_token(
    websession: aiohttp.ClientSession,
    aioclient_mock: AiohttpClientMocker,
    refresh: dict[str, Any],
) -> None:
    """A renewal that fails without an auth error keeps the old token for the call."""
    updates: list[Session] = []
    aioclient_mock.post(url("user/token/refresh"), **refresh)
    aioclient_mock.post(url("user/pet/sync"), json=load_fixture("pet_sync.json"))
    client = make_client(websession, session=DUE, updates=updates)
    await client.get_cats()
    [(_body, sync_headers)] = calls(aioclient_mock, "user/pet/sync")
    assert sync_headers["authorization"] == f"Bearer {TOKEN}"
    assert updates == []
    assert client.session == DUE


async def test_renewal_retries_after_one_hour(
    websession: aiohttp.ClientSession,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After a failed renewal, calls skip renewal for one hour and warn once."""
    now = [NOW_MS / 1000]
    client = SiiPetClient(
        websession,
        client_id="client-uuid-0001",
        time_zone="Europe/Warsaw",
        session=DUE,
        clock=lambda: now[0],
    )
    aioclient_mock.post(url("user/token/refresh"), exc=aiohttp.ClientConnectionError())
    aioclient_mock.post(url("user/pet/sync"), json=load_fixture("pet_sync.json"))

    await client.get_cats()
    now[0] += 3599
    await client.get_cats()
    await client.get_cats()
    assert len(calls(aioclient_mock, "user/token/refresh")) == 1

    now[0] += 1
    await client.get_cats()
    assert len(calls(aioclient_mock, "user/token/refresh")) == 2
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "renew" in warnings[0].getMessage()


async def test_renewal_auth_error_raises(
    websession: aiohttp.ClientSession, aioclient_mock: AiohttpClientMocker
) -> None:
    """A renewal that the server rejects raises SiiPetAuthError."""
    aioclient_mock.post(url("user/token/refresh"), status=401)
    with pytest.raises(SiiPetAuthError):
        await make_client(websession, session=DUE).get_cats()
