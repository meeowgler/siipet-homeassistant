"""Tests for the entity bases."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import async_get_platforms
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.siipet.const import DOMAIN

from .common import DEVICE_STATE, FakeShadowLink, setup_integration


@pytest.mark.parametrize(
    "entity_id",
    [
        "event.luna_visit",
        "sensor.bathroom_battery",
        "binary_sensor.bathroom_online",
    ],
)
async def test_new_entity_id_keeps_the_entity_added(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    config_entry: MockConfigEntry,
    shadow_links: list[FakeShadowLink],
    entity_id: str,
) -> None:
    """A new entity id changes the entity in place, with no remove and no add."""
    await setup_integration(hass, config_entry)
    shadow_links[0].on_connection(True)
    shadow_links[0].on_state("SN0001", DEVICE_STATE)
    await hass.async_block_till_done()
    entity = next(
        platform.entities[entity_id]
        for platform in async_get_platforms(hass, DOMAIN)
        if entity_id in platform.entities
    )
    new_entity_id = f"{entity_id.split('.')[0]}.renamed"

    with (
        patch.object(
            entity,
            "async_will_remove_from_hass",
            wraps=entity.async_will_remove_from_hass,
        ) as will_remove,
        patch.object(
            entity, "async_added_to_hass", wraps=entity.async_added_to_hass
        ) as added,
    ):
        er.async_get(hass).async_update_entity(entity_id, new_entity_id=new_entity_id)
        await hass.async_block_till_done()

    will_remove.assert_not_called()
    added.assert_not_called()
    assert entity.entity_id == new_entity_id
    assert hass.states.get(new_entity_id) is not None
    assert hass.states.get(entity_id) is None
