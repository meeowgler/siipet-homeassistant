"""Tests for the SiiPet integration setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siipet import async_remove_config_entry_device
from custom_components.siipet.api import Session, SiiPetAuthError, SiiPetConnectionError
from custom_components.siipet.const import (
    AUTH_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_CLIENT_ID,
    CONF_EXPIRE_AT,
    CONF_TOKEN,
    DOMAIN,
)

from .common import setup_integration


async def test_setup_and_unload(
    hass: HomeAssistant, mock_client_class: MagicMock, config_entry: MockConfigEntry
) -> None:
    """The entry loads with the stored session and unloads."""
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.async_entity_ids("binary_sensor") == []
    kwargs = mock_client_class.call_args.kwargs
    assert kwargs["client_id"] == "client-uuid-0001"
    assert kwargs["time_zone"] == "UTC"
    assert kwargs["session"] == Session(
        config_entry.data[CONF_TOKEN], config_entry.data[CONF_EXPIRE_AT]
    )

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_session_update_is_saved(
    hass: HomeAssistant, mock_client_class: MagicMock, config_entry: MockConfigEntry
) -> None:
    """A renewed session is written to the entry data."""
    await setup_integration(hass, config_entry)
    save = mock_client_class.call_args.kwargs["on_session_update"]
    save(Session("renewed-token", 1_900_000_000_000))
    assert config_entry.data[CONF_TOKEN] == "renewed-token"
    assert config_entry.data[CONF_EXPIRE_AT] == 1_900_000_000_000


async def test_setup_auth_error_starts_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A rejected session fails setup and starts reauth."""
    mock_client.get_cats.side_effect = SiiPetAuthError("expired")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_setup_connection_error_retries(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A connection error at setup retries later."""
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_entry_without_session(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """An entry from version 0.0.1 has no session and fails setup."""
    entry = MockConfigEntry(domain=DOMAIN, title="SiiPet", unique_id=DOMAIN, data={})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


async def test_token_entry_setup(
    hass: HomeAssistant, mock_client_class: MagicMock, token_entry: MockConfigEntry
) -> None:
    """An entry from a pasted token loads with the phone's device identifier."""
    await setup_integration(hass, token_entry)
    assert token_entry.state is ConfigEntryState.LOADED
    kwargs = mock_client_class.call_args.kwargs
    assert kwargs["client_id"] == "phone-device-0001"
    assert kwargs["session"] == Session(
        token_entry.data[CONF_TOKEN], token_entry.data[CONF_EXPIRE_AT]
    )
    assert kwargs["on_session_update"] is not None


@pytest.mark.parametrize("key", [CONF_TOKEN, CONF_EXPIRE_AT, CONF_CLIENT_ID])
async def test_entry_missing_key(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    key: str,
) -> None:
    """An entry without a session key fails setup cleanly and starts no reauth."""
    hass.config_entries.async_update_entry(
        config_entry, data={k: v for k, v in config_entry.data.items() if k != key}
    )
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert config_entry.error_reason_translation_key == "entry_outdated"
    assert "Remove the SiiPet entry and add it again" in caplog.text
    assert "KeyError" not in caplog.text
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


@pytest.mark.parametrize(
    ("identifier", "removable"),
    [("pet-luna", False), ("unknown", False), ("SN0001", False), ("pet-gone", True)],
)
async def test_remove_device(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    identifier: str,
    removable: bool,
) -> None:
    """Only a device that the account no longer has can be removed."""
    await setup_integration(hass, config_entry)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, identifier)}
    )
    assert (
        await async_remove_config_entry_device(hass, config_entry, device) is removable
    )


async def test_remove_device_while_not_loaded(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A device cannot be removed while the entry is not loaded."""
    mock_client.get_day.side_effect = SiiPetConnectionError("down")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={(DOMAIN, "pet-gone")}
    )
    assert await async_remove_config_entry_device(hass, config_entry, device) is False


async def test_email_entry_has_no_password(
    hass: HomeAssistant, mock_client_class: MagicMock, config_entry: MockConfigEntry
) -> None:
    """An email-code entry gives the client no password, so it cannot sign in again."""
    await setup_integration(hass, config_entry)
    assert mock_client_class.call_args.kwargs["password"] is None


async def test_password_entry_setup(
    hass: HomeAssistant, mock_client_class: MagicMock, config_entry: MockConfigEntry
) -> None:
    """A password entry gives the client its email and password."""
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            CONF_AUTH_METHOD: AUTH_PASSWORD,
            CONF_PASSWORD: "secret-1",
        },
    )
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    kwargs = mock_client_class.call_args.kwargs
    assert kwargs["email"] == "cat@example.com"
    assert kwargs["password"] == "secret-1"


async def test_password_relogin_is_saved(
    hass: HomeAssistant, mock_client_class: MagicMock, config_entry: MockConfigEntry
) -> None:
    """A session from a new sign-in is written to the entry and keeps the password."""
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            CONF_AUTH_METHOD: AUTH_PASSWORD,
            CONF_PASSWORD: "secret-1",
        },
    )
    await setup_integration(hass, config_entry)
    save = mock_client_class.call_args.kwargs["on_session_update"]
    save(Session("signed-in-again", 1_900_000_000_000))
    assert config_entry.data[CONF_TOKEN] == "signed-in-again"
    assert config_entry.data[CONF_PASSWORD] == "secret-1"
    assert config_entry.data[CONF_EMAIL] == "cat@example.com"
