"""Async client for the SiiPet cloud API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date, time as time_of_day, timedelta
import json
import logging
import time
from typing import Any

import aiohttp

from .auth import Session, encrypt_challenge, hash_password, needs_renewal
from .errors import SiiPetApiError, SiiPetAuthError, SiiPetConnectionError, SiiPetError
from .models import (
    AbnormalLabels,
    CalendarDay,
    Camera,
    Cat,
    DayVisits,
    IotCredentials,
    MediaCredentials,
    Visit,
)

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api-siipet.linkric.com"
APP_VERSION = "2.1.5"
USER_AGENT = f"lc01-app/{APP_VERSION}"
# If the model does not start with "iPhone" or "android-phone", every
# authenticated call fails with Code -2.
DEVICE_MODEL = "android-phone Home Assistant"
# The other headers copy the captured iOS app. The API accepts them with the
# Android-style model.
DEVICE_OS = "iOS 27.0"
DEVICE_LANGUAGE = "en"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Envelope codes that the vendor app treats as an ended session.
AUTH_ERROR_CODES: frozenset[int] = frozenset({-2, -4})
# Envelope code for a wrong email code at sign-in.
WRONG_CODE = 10004
# Envelope code for too many email code requests in one day.
TOO_MANY_REQUESTS = 10010
# Wait after a failed renewal. Renewal starts one day before ExpireAt, so
# this gives about 24 tries before ExpireAt. The token's encoded expiry is
# 15 days later, but the lifetime that the server enforces is not known.
RENEW_RETRY_MS = 3_600_000
# Wait after a sign-in with the stored password before the next one. Another
# sign-in to the same account ends this session. Without a wait, Home Assistant
# and the other device would keep ending each other's session.
RELOGIN_COOLDOWN_MS = 900_000


@contextmanager
def _parsing(path: str) -> Iterator[None]:
    """Raise SiiPetError when a response does not have the documented shape.

    The message names only the path and the error type.
    """
    try:
        yield
    except (AttributeError, KeyError, TypeError, ValueError) as err:
        raise SiiPetError(
            f"Unexpected response from {path} ({type(err).__name__})"
        ) from err


class SiiPetClient:
    """Client for the SiiPet cloud API. Every call is a JSON POST."""

    def __init__(
        self,
        websession: aiohttp.ClientSession,
        *,
        client_id: str,
        time_zone: str,
        session: Session | None = None,
        on_session_update: Callable[[Session], None] | None = None,
        email: str | None = None,
        password: str | None = None,
        base_url: str = BASE_URL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Create a client. `client_id` is sent as `x-device-identifier`.

        With `email` and `password`, the client signs in again by itself when
        SiiPet ends the session.
        """
        self._websession = websession
        self._client_id = client_id
        self._time_zone = time_zone
        self._session = session
        self._on_session_update = on_session_update
        self._base_url = base_url
        self._clock = clock
        self._email = email
        self._password = password
        self._renew_lock = asyncio.Lock()
        self._renew_retry_at = 0
        self._renew_warned = False
        self._relogin_lock = asyncio.Lock()
        self._relogin_after = 0

    @property
    def session(self) -> Session | None:
        """The current session, or None before sign-in."""
        return self._session

    async def request_email_code(self, email: str) -> None:
        """Solve the client challenge and ask the service to email a code."""
        path = "/api/v1/user/client/verify"
        challenge = await self._send(path, {})
        with _parsing(path):
            client_id = challenge["ClientId"]
            verify_code = str(challenge["VerifyCode"])
        await self._send(
            "/api/v1/user/email/send/trustworthy",
            {
                "Scene": 0,
                "ClientId": client_id,
                "VerifyCiphertext": encrypt_challenge(verify_code),
                "Email": email,
            },
        )

    async def login(self, email: str, code: str) -> Session:
        """Sign in with the emailed code and keep the new session."""
        path = "/api/v1/user/email/register/login"
        data = await self._send(path, {"Code": code, "Email": email})
        self._session = _session_from(path, data)
        return self._session

    async def login_with_password(self, email: str, password: str) -> Session:
        """Sign in with the account password and keep the new session."""
        path = "/api/v1/user/email/login"
        data = await self._send(
            path, {"Email": email, "Password": hash_password(password)}
        )
        self._session = _session_from(path, data)
        return self._session

    async def set_password(self, email: str, code: str, password: str) -> None:
        """Set the account password with an emailed code. This does not sign in."""
        await self._send(
            "/api/v1/user/email/reset",
            {"Code": code, "Email": email, "Password": hash_password(password)},
        )

    async def get_cats(self) -> dict[str, Cat]:
        """Return the cats of the account by `PetId`."""
        path = "/api/v1/user/pet/sync"
        data = await self._post(path, {})
        with _parsing(path):
            cats = [Cat.from_api(item) for item in data.get("List") or ()]
        return {cat.pet_id: cat for cat in cats}

    async def get_cameras(self) -> dict[str, Camera]:
        """Return the cameras of the account by `SN`."""
        path = "/api/v1/user/device/sync"
        data = await self._post(path, {})
        with _parsing(path):
            cameras = [Camera.from_api(item) for item in data.get("List") or ()]
        return {camera.sn: camera for camera in cameras}

    async def get_day(
        self, day: date, *, until: time_of_day | None = None
    ) -> DayVisits:
        """Return the visits and summaries of one day in the registered time zone.

        The visit list covers the whole day. The baselines in the summaries
        count from midnight to `until`, or to midnight when it is not given.
        """
        at = (until or time_of_day()).strftime("%H:%M:%S")
        path = "/api/v1/pet/toilet/event"
        data = await self._post(
            path,
            {
                "IncludeLocal": True,
                "FollowRegisterTimezone": True,
                "Date": f"{day.isoformat()} {at}",
            },
        )
        with _parsing(path):
            return DayVisits.from_api(data or {})

    async def get_calendar(
        self, pet_id: str, first: date, last: date
    ) -> tuple[CalendarDay, ...]:
        """Return the calendar days of one cat from `first` to `last`, both included.

        Days without visits are missing from the result.
        """
        path = "/api/v1/pet/toilet/data/calendar"
        data = await self._post(
            path,
            {
                "PetId": pet_id,
                "StartDate": f"{first.isoformat()} 00:00:00",
                # The server excludes the end date, so it gets the midnight after `last`.
                "EndDate": f"{(last + timedelta(days=1)).isoformat()} 00:00:00",
                "IncludeLocal": True,
                "FollowRegisterTimezone": True,
            },
        )
        with _parsing(path):
            return tuple(
                CalendarDay.from_api(item)
                for item in (data or {}).get("DataCalendar") or ()
            )

    async def get_visit(self, event_id: str) -> Visit:
        """Return one visit with its media keys."""
        path = "/api/v1/device/toilet/event/detail"
        data = await self._post(path, {"EventId": event_id})
        with _parsing(path):
            return Visit.from_api(data or {})

    async def get_abnormal_labels(self) -> AbnormalLabels:
        """Return the abnormal code titles from the system config."""
        path = "/api/v1/config/system/config"
        data = await self._post(path, {})
        with _parsing(path):
            return AbnormalLabels.from_api(data or {})

    async def annotate(
        self, event_id: str, operation: int, result: Mapping[str, Any]
    ) -> None:
        """Send one annotate operation. `result` goes out as a compact JSON string."""
        await self._post(
            "/api/v1/pet/toilet/event/annotate",
            {
                "EventId": event_id,
                "Type": operation,
                "Result": json.dumps(result, separators=(",", ":")),
            },
        )

    async def set_note(self, event_id: str, note: str) -> None:
        """Set the memo of a visit. An empty note clears it."""
        await self._post(
            "/api/v1/pet/toilet/event/edit", {"EventId": event_id, "Note": note}
        )

    async def delete_visit(self, event_id: str) -> None:
        """Delete a visit for good."""
        await self._post("/api/v1/device/toilet/event/delete", {"EventId": event_id})

    async def get_media_credentials(self) -> MediaCredentials:
        """Return temporary credentials for the media bucket."""
        path = "/api/v1/config/aws/auth"
        data = await self._post(path, {})
        with _parsing(path):
            return MediaCredentials.from_api(data)

    async def get_iot_credentials(self) -> IotCredentials:
        """Return temporary credentials for the device shadows on AWS IoT."""
        path = "/api/v1/config/aws/auth"
        data = await self._post(path, {})
        with _parsing(path):
            return IotCredentials.from_api(data)

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        """Send an authenticated request. Renew the session first when due.

        When SiiPet ended the session and the client has a password, sign in
        again and send the request once more.
        """
        session = await self._ensure_session()
        try:
            return await self._send(path, body, token=session.token)
        except SiiPetAuthError:
            if not await self._relogin(session):
                raise
        assert self._session is not None
        return await self._send(path, body, token=self._session.token)

    async def _ensure_session(self) -> Session:
        """Renew the token when less than one day remains before `ExpireAt`.

        A renewal that fails without an auth error keeps the current token,
        and the next try waits `RENEW_RETRY_MS`.
        """
        if self._session is None:
            raise SiiPetAuthError("No session. Sign in first.")
        if not self._renewal_due():
            return self._session
        async with self._renew_lock:
            if self._renewal_due():
                try:
                    await self._renew()
                except SiiPetAuthError:
                    assert self._session is not None
                    if not await self._relogin(self._session):
                        raise
                except SiiPetError as err:
                    self._renew_retry_at = self._now_ms() + RENEW_RETRY_MS
                    if self._renew_warned:
                        _LOGGER.debug("Could not renew the SiiPet token: %s", err)
                    else:
                        _LOGGER.warning(
                            "Could not renew the SiiPet token, retry in one hour: %s",
                            err,
                        )
                        self._renew_warned = True
                else:
                    self._renew_warned = False
        return self._session

    def _renewal_due(self) -> bool:
        assert self._session is not None
        now = self._now_ms()
        return needs_renewal(self._session.expire_at, now) and (
            now >= self._renew_retry_at
        )

    async def _relogin(self, failed: Session) -> bool:
        """Sign in again with the stored password after SiiPet ended `failed`.

        Return True when a new session is ready. Return False when there is no
        password, when the last sign-in was too recent, or when SiiPet rejects
        the password. A connection error is raised.
        """
        if self._email is None or self._password is None:
            return False
        async with self._relogin_lock:
            if self._session != failed:
                # Another call signed in while this one waited.
                return self._session is not None
            now = self._now_ms()
            if now < self._relogin_after:
                return False
            try:
                session = await self.login_with_password(self._email, self._password)
            except SiiPetConnectionError:
                # A network failure is not an answer, so it starts no wait.
                raise
            except SiiPetError as err:
                self._relogin_after = now + RELOGIN_COOLDOWN_MS
                _LOGGER.debug("SiiPet rejected the stored password: %s", err)
                return False
            self._relogin_after = now + RELOGIN_COOLDOWN_MS
            _LOGGER.info("SiiPet ended the session. Signed in again with the password")
            if self._on_session_update is not None:
                self._on_session_update(session)
            return True

    async def _renew(self) -> None:
        """Exchange the current token for a new one."""
        assert self._session is not None
        path = "/api/v1/user/token/refresh"
        data = await self._send(path, {}, token=self._session.token)
        self._session = _session_from(path, data)
        if self._on_session_update is not None:
            self._on_session_update(self._session)

    async def _send(
        self, path: str, body: dict[str, Any], *, token: str | None = None
    ) -> Any:
        """POST one request and unwrap the response envelope."""
        headers = {
            "x-app-version": APP_VERSION,
            "x-device-identifier": self._client_id,
            "x-device-language": DEVICE_LANGUAGE,
            "x-device-model": DEVICE_MODEL,
            "x-device-os": DEVICE_OS,
            "x-timestamp": str(self._now_ms()),
            "x-timezone": self._time_zone,
            "user-agent": USER_AGENT,
        }
        if token is not None:
            headers["authorization"] = f"Bearer {token}"
        try:
            async with self._websession.post(
                f"{self._base_url}{path}",
                json=body,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    raise SiiPetAuthError(f"HTTP {response.status} from {path}")
                if response.status >= 400:
                    raise SiiPetConnectionError(f"HTTP {response.status} from {path}")
                payload = await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise SiiPetConnectionError(f"Request to {path} failed: {err}") from err
        except ValueError as err:
            raise SiiPetConnectionError(f"Response from {path} is not JSON") from err
        if not isinstance(payload, dict):
            raise SiiPetConnectionError(f"Response from {path} is not an object")
        with _parsing(path):
            code = int(payload.get("Code", -1))
        msg = str(payload.get("Msg") or "")
        if code in AUTH_ERROR_CODES:
            raise SiiPetAuthError(f"{code}: {msg}")
        if code != 0:
            raise SiiPetApiError(code, msg)
        return payload.get("Data")

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)


def _session_from(path: str, data: Any) -> Session:
    """Build a session from the `Data` of a login or renewal response."""
    with _parsing(path):
        token = data["Token"]
        expire_at = int(data["ExpireAt"])
    if not isinstance(token, str) or not token:
        raise SiiPetError(f"Unexpected response from {path} (no token)")
    return Session(token=token, expire_at=expire_at)
