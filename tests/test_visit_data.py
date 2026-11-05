"""Tests for the visit and cat data shared by the actions and the card."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.siipet.const import UNKNOWN_CAT_ID
from custom_components.siipet.visit_data import (
    cat_id,
    check_history_day,
    device_ids,
    loaded_entry,
    visit_dict,
)

from .common import TODAY, setup_integration


@pytest.mark.parametrize("offset", [0, 30])
async def test_check_history_day_accepts(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    offset: int,
) -> None:
    """Today and the 30 days before it are in the history."""
    await setup_integration(hass, config_entry)
    data = config_entry.runtime_data.coordinator.data
    check_history_day(data, TODAY - timedelta(days=offset))


@pytest.mark.parametrize("offset", [31, -1])
async def test_check_history_day_refuses(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    offset: int,
) -> None:
    """A day before the history or after today raises a translated error."""
    await setup_integration(hass, config_entry)
    data = config_entry.runtime_data.coordinator.data
    with pytest.raises(ServiceValidationError) as info:
        check_history_day(data, TODAY - timedelta(days=offset))
    assert info.value.translation_key == "date_out_of_range"
    assert info.value.translation_placeholders == {
        "first": "2026-08-27",
        "last": "2026-09-26",
    }


async def test_cat_id_and_visit_dict(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Cat devices map to pet ids, and a visit dict names cats by device id."""
    await setup_integration(hass, config_entry)
    entry = loaded_entry(hass)
    devices = device_ids(hass, entry)
    assert cat_id(hass, entry, devices["pet-luna"], allow_unknown=False) == "pet-luna"
    assert (
        cat_id(hass, entry, devices[UNKNOWN_CAT_ID], allow_unknown=True)
        == UNKNOWN_CAT_ID
    )
    with pytest.raises(ServiceValidationError):
        cat_id(hass, entry, devices[UNKNOWN_CAT_ID], allow_unknown=False)
    data = entry.runtime_data.coordinator.data
    visit = next(v for v in data.days[TODAY] if v.event_id == "ev-1")
    result = visit_dict(data, devices, visit)
    assert result["cats"] == [{"device_id": devices["pet-luna"], "name": "Luna"}]
    assert result["type"] == "poop"
