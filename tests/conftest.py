"""Shared fixtures for the SiiPet tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siipet.api import (
    AbnormalLabels,
    CalendarDay,
    Camera,
    Cat,
    MediaCredentials,
    Session,
)
from custom_components.siipet.const import (
    AUTH_EMAIL,
    AUTH_TOKEN,
    CONF_AUTH_METHOD,
    CONF_CLIENT_ID,
    CONF_EXPIRE_AT,
    CONF_MEDIA_DAYS,
    CONF_TOKEN,
    DOMAIN,
)

from .common import EMPTY_DAY, NOW, TODAY, FakeShadowLink, fixture_day, load_data


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture(autouse=True)
def no_deprecated_calls(caplog: pytest.LogCaptureFixture) -> Generator[None]:
    """Fail a test in which Home Assistant reports a deprecated call."""
    yield
    reports = [
        record.getMessage()
        for when in ("setup", "call")
        for record in caplog.get_records(when)
        if record.name == "homeassistant.helpers.frame"
    ]
    assert not reports


@pytest.fixture(autouse=True)
def mock_control() -> Generator[AsyncMock]:
    """Replace the realtime control client, so tests send no command over a socket."""
    with patch("custom_components.siipet.LrtmControl") as control_class:
        control = control_class.return_value
        control.send = AsyncMock()
        yield control


@pytest.fixture(autouse=True)
def shadow_links() -> Generator[list[FakeShadowLink]]:
    """Replace the shadow link with a fake. The list holds each fake link."""
    links: list[FakeShadowLink] = []

    def create(*args: Any, **kwargs: Any) -> FakeShadowLink:
        link = FakeShadowLink(*args, **kwargs)
        links.append(link)
        return link

    with patch("custom_components.siipet.device_state.ShadowLink", side_effect=create):
        yield links


@pytest.fixture(autouse=True)
async def utc_time_zone(hass: HomeAssistant) -> None:
    """Run every test in UTC, so local days match the fixture timestamps."""
    await hass.config.async_set_time_zone("UTC")


@pytest.fixture(autouse=True)
def media_dir(hass: HomeAssistant, tmp_path: Path) -> Path:
    """Point the local media folder of Home Assistant to a temporary folder."""
    folder = tmp_path / "media"
    hass.config.media_dirs = {"local": str(folder)}
    return folder


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time at noon on the fixture day."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def mock_client_class() -> Generator[MagicMock]:
    """Replace SiiPetClient in the integration and the config flow."""
    with (
        patch("custom_components.siipet.SiiPetClient", autospec=True) as client_class,
        patch("custom_components.siipet.config_flow.SiiPetClient", new=client_class),
    ):
        client = client_class.return_value
        client.get_cats.return_value = {
            cat.pet_id: cat
            for cat in (
                Cat.from_api(item) for item in load_data("pet_sync.json")["List"]
            )
        }
        client.get_cameras.return_value = {
            camera.sn: camera
            for camera in (
                Camera.from_api(item) for item in load_data("device_sync.json")["List"]
            )
        }
        day = fixture_day()
        client.get_day.side_effect = lambda requested, **_: (
            day if requested == TODAY else EMPTY_DAY
        )
        client.get_abnormal_labels.return_value = AbnormalLabels.from_api(
            load_data("system_config.json")
        )
        login = load_data("login.json")
        client.login.return_value = Session(login["Token"], login["ExpireAt"])
        client.request_email_code.return_value = None
        client.get_media_credentials.return_value = MediaCredentials.from_api(
            load_data("aws_auth.json")
        )
        client.get_calendar.return_value = tuple(
            CalendarDay.from_api(item)
            for item in load_data("pet_calendar.json")["DataCalendar"]
        )
        yield client_class


@pytest.fixture
def mock_client(mock_client_class: MagicMock) -> AsyncMock:
    """The mocked client instance."""
    return mock_client_class.return_value


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A signed-in SiiPet entry. Local media is off, so it makes no downloads."""
    login = load_data("login.json")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="SiiPet",
        unique_id="user-0001",
        data={
            CONF_AUTH_METHOD: AUTH_EMAIL,
            CONF_EMAIL: "cat@example.com",
            CONF_TOKEN: login["Token"],
            CONF_EXPIRE_AT: login["ExpireAt"],
            CONF_CLIENT_ID: "client-uuid-0001",
        },
        options={CONF_MEDIA_DAYS: 0},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def token_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A SiiPet entry from a pasted token, with the phone's device identifier.

    Local media is off, so it makes no downloads.
    """
    login = load_data("login.json")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="SiiPet",
        unique_id="user-0001",
        data={
            CONF_AUTH_METHOD: AUTH_TOKEN,
            CONF_TOKEN: login["Token"],
            CONF_EXPIRE_AT: login["ExpireAt"],
            CONF_CLIENT_ID: "phone-device-0001",
        },
        options={CONF_MEDIA_DAYS: 0},
    )
    entry.add_to_hass(hass)
    return entry
