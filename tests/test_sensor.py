"""Tests for the SiiPet sensors."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.siipet.api import Cat, DayVisits

from .common import EMPTY_DAY, TODAY, fixture_day, setup_integration


@pytest.mark.parametrize(
    ("entity_id", "state"),
    [
        ("sensor.luna_visits_today", "2"),
        ("sensor.luna_pee_today", "1"),
        ("sensor.luna_poop_today", "1"),
        ("sensor.luna_lingering_today", "1"),
        ("sensor.luna_abnormal_visits_today", "1"),
        ("sensor.luna_average_visit_duration_today", "140.0"),
        ("sensor.luna_baseline_visits", "3.5"),
        ("sensor.luna_baseline_visit_duration", "95.0"),
        ("sensor.luna_baseline_progress", "100"),
        ("sensor.luna_last_visit", "2026-09-26T09:00:00+00:00"),
        ("sensor.milo_visits_today", "2"),
        ("sensor.milo_abnormal_visits_today", "1"),
        ("sensor.milo_average_visit_duration_today", "67.5"),
        ("sensor.milo_baseline_progress", "43"),
        ("sensor.unknown_cat_visits_today", "1"),
        ("sensor.unknown_cat_pee_today", "1"),
        ("sensor.unknown_cat_unassigned_visits", "1"),
        ("sensor.bathroom_subscription_expires", "2027-01-01T00:00:00+00:00"),
        ("sensor.hallway_subscription_expires", "unknown"),
    ],
)
async def test_sensor_states(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    entity_id: str,
    state: str,
) -> None:
    """Each sensor reports the value of the fixture day."""
    await setup_integration(hass, config_entry)
    assert hass.states.get(entity_id).state == state


async def test_daily_count_attributes(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """Daily counts are totals that reset at local midnight."""
    await setup_integration(hass, config_entry)
    attributes = hass.states.get("sensor.luna_visits_today").attributes
    assert attributes["state_class"] == "total"
    assert attributes["last_reset"] == "2026-09-26T00:00:00+00:00"


async def test_unknown_cat_has_no_baselines(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The Unknown cat has no baseline sensors, and real cats have no queue sensor."""
    await setup_integration(hass, config_entry)
    assert hass.states.get("sensor.luna_baseline_visits") is not None
    assert hass.states.get("sensor.unknown_cat_unassigned_visits") is not None
    assert hass.states.get("sensor.unknown_cat_baseline_visits") is None
    assert hass.states.get("sensor.unknown_cat_baseline_progress") is None
    assert hass.states.get("sensor.luna_unassigned_visits") is None


async def test_last_visit_attributes(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The last visit shows names and abnormal reasons, and no private ids."""
    await setup_integration(hass, config_entry)
    attributes = dict(hass.states.get("sensor.luna_last_visit").attributes)
    assert attributes["event_id"] == "ev-6"
    assert attributes["type"] == "pee"
    assert attributes["duration"] == 200
    assert attributes["camera"] == "Bathroom"
    assert attributes["cats"] == ["Luna"]
    assert attributes["abnormal"] is True
    assert attributes["abnormal_reasons"] == ["Potty Overtime"]
    text = str(attributes)
    for private in ("SN0001", "pet-luna", "group-0001", "events/"):
        assert private not in text


async def test_reassign_lowers_count(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """A visit that moves to another cat leaves the old count."""
    await setup_integration(hass, config_entry)
    base = fixture_day()
    moved = tuple(
        replace(visit, pet_ids=("pet-milo",)) if visit.event_id == "ev-1" else visit
        for visit in base.visits
    )
    day = DayVisits(moved, base.summaries, False)
    mock_client.get_day.side_effect = lambda requested, **_: (
        day if requested == TODAY else EMPTY_DAY
    )
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.luna_visits_today").state == "1"
    assert hass.states.get("sensor.milo_visits_today").state == "3"


async def test_new_cat_gets_entities(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A cat added to the account gets entities at the next sync."""
    await setup_integration(hass, config_entry)
    cats = dict(mock_client.get_cats.return_value)
    cats["pet-nala"] = Cat(pet_id="pet-nala", name="Nala", avatar_key=None)
    mock_client.get_cats.return_value = cats
    frozen_time.tick(timedelta(hours=1))
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.nala_visits_today").state == "0"
    assert (
        hass.states.get("sensor.nala_average_visit_duration_today").state == "unknown"
    )


async def test_removed_cat_is_unavailable(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """A cat removed from the account becomes unavailable."""
    await setup_integration(hass, config_entry)
    cats = dict(mock_client.get_cats.return_value)
    del cats["pet-milo"]
    mock_client.get_cats.return_value = cats
    frozen_time.tick(timedelta(hours=1))
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.milo_visits_today").state == "unavailable"
