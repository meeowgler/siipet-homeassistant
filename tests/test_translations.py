"""Tests for the translation files."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant.common import MockConfigEntry

from .common import DEVICE_STATE, FakeShadowLink, setup_integration

TRANSLATIONS = (
    Path(__file__).parent.parent / "custom_components" / "siipet" / "translations"
)
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Return the strings of a translation file by their dotted keys."""
    strings: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            strings |= _flatten(value, f"{prefix}{key}.")
        else:
            strings[f"{prefix}{key}"] = value
    return strings


def _load(language: str) -> dict[str, str]:
    path = TRANSLATIONS / f"{language}.json"
    return _flatten(json.loads(path.read_text(encoding="utf-8")))


def test_languages() -> None:
    """The integration ships English and Polish."""
    assert sorted(path.name for path in TRANSLATIONS.iterdir()) == [
        "en.json",
        "pl.json",
    ]


def test_polish_has_every_key() -> None:
    """Polish has a string for each English string, and no other."""
    assert _load("pl").keys() == _load("en").keys()


def test_polish_keeps_the_placeholders() -> None:
    """Each Polish string has the placeholders of its English string."""
    english = _load("en")
    polish = _load("pl")
    for key, text in english.items():
        assert set(PLACEHOLDER.findall(polish[key])) == set(
            PLACEHOLDER.findall(text)
        ), key


@pytest.mark.parametrize("language", ["en", "pl"])
def test_no_references(language: str) -> None:
    """No string holds a [%key: reference."""
    for key, text in _load(language).items():
        assert "[%key:" not in text, key


async def _setup(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    await setup_integration(hass, config_entry)
    shadow_links[0].on_connection(True)
    shadow_links[0].on_state("SN0001", DEVICE_STATE)
    await hass.async_block_till_done()


def _name(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, "siipet", unique_id)
    assert entity_id is not None, unique_id
    return hass.states.get(entity_id).attributes["friendly_name"]


async def test_polish_entity_names(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """On a Polish server, the entities take the Polish names."""
    hass.config.language = "pl"
    await _setup(hass, config_entry, shadow_links)
    assert _name(hass, "sensor", "pet-luna_pee_today") == "Luna Siku dzisiaj"
    assert _name(hass, "event", "pet-luna_visit") == "Luna Wizyta"
    assert _name(hass, "sensor", "SN0001_battery") == "Bathroom Bateria"
    assert _name(hass, "binary_sensor", "SN0001_charging") == "Bathroom Ładowanie"


async def test_device_class_names(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
) -> None:
    """Battery and Charging take the English names of their device classes."""
    await _setup(hass, config_entry, shadow_links)
    assert _name(hass, "sensor", "SN0001_battery") == "Bathroom Battery"
    assert _name(hass, "binary_sensor", "SN0001_charging") == "Bathroom Charging"
