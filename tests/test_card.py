"""Tests for the serving of the dashboard card."""

from __future__ import annotations

from collections.abc import Generator
import hashlib
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant.typing import ClientSessionGenerator

from custom_components.siipet.card import CARD_FILE
from custom_components.siipet.const import DOMAIN


@pytest.fixture
def add_extra_js_url() -> Generator[MagicMock]:
    """Replace the frontend call that adds a module to every page."""
    with patch("custom_components.siipet.card.add_extra_js_url") as add_url:
        yield add_url


async def test_card_is_served_with_a_content_version(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    add_extra_js_url: MagicMock,
) -> None:
    """The card file is public, and its URL changes with its content."""
    hass.config.components.add("frontend")
    assert await async_setup_component(hass, DOMAIN, {})

    version = hashlib.sha256(CARD_FILE.read_bytes()).hexdigest()[:8]
    add_extra_js_url.assert_called_once_with(
        hass, f"/siipet/siipet-visits-card.js?v={version}"
    )
    client = await hass_client_no_auth()
    response = await client.get("/siipet/siipet-visits-card.js")
    assert response.status == HTTPStatus.OK
    assert await response.read() == CARD_FILE.read_bytes()


async def test_card_is_not_added_without_the_frontend(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    add_extra_js_url: MagicMock,
) -> None:
    """A setup without the frontend serves the file but adds it to no page."""
    assert await async_setup_component(hass, DOMAIN, {})
    add_extra_js_url.assert_not_called()
    client = await hass_client_no_auth()
    response = await client.get("/siipet/siipet-visits-card.js")
    assert response.status == HTTPStatus.OK
    assert await response.read() == CARD_FILE.read_bytes()


async def test_integration_sets_up_without_the_card_file(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    add_extra_js_url: MagicMock,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """A missing card file logs a warning, and the rest of the setup goes on."""
    hass.config.components.add("frontend")
    with patch("custom_components.siipet.card.CARD_FILE", tmp_path / "missing.js"):
        assert await async_setup_component(hass, DOMAIN, {})

    assert (
        "The SiiPet card file is missing, so dashboards do not load the card"
        in caplog.text
    )
    add_extra_js_url.assert_not_called()
    assert hass.services.has_service(DOMAIN, "list_visits")
    client = await hass_client_no_auth()
    response = await client.get("/siipet/siipet-visits-card.js")
    assert response.status == HTTPStatus.NOT_FOUND
