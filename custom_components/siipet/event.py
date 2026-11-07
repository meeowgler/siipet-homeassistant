"""Visit event entities for the SiiPet integration."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import VisitType
from .coordinator import SiiPetConfigEntry, SiiPetCoordinator, SiiPetData
from .entity import SiiPetCatEntity, async_add_cat_entities, visit_attributes

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SiiPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a visit event entity for each cat and the Unknown cat."""

    def build(coordinator: SiiPetCoordinator, cat_id: str) -> list[SiiPetVisitEvent]:
        return [SiiPetVisitEvent(coordinator, cat_id)]

    async_add_cat_entities(entry, async_add_entities, build)


class SiiPetVisitEvent(SiiPetCatEntity, EventEntity):
    """Fires once for each new visit of the cat."""

    def __init__(self, coordinator: SiiPetCoordinator, cat_id: str) -> None:
        """Create the event entity."""
        super().__init__(coordinator, cat_id, "visit")
        self._attr_event_types = [visit_type.key for visit_type in VisitType]
        self._handled_data: SiiPetData | None = None

    async def async_added_to_hass(self) -> None:
        """Fire the new visits of the update that added this entity."""
        await super().async_added_to_hass()
        data = self.coordinator.data
        self._handled_data = data
        # Home Assistant drops state writes until the entity is fully added,
        # so fire on the next loop iteration.
        handle = self.hass.loop.call_soon(self._fire_new_visits, data)
        self.async_on_remove(handle.cancel)

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        """Keep the entity added. Nothing here depends on the entity id."""
        super().async_entity_id_changed(old_entity_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data is self._handled_data:
            # A failed refresh notifies listeners with the same snapshot
            # again. Its visits were already fired, so only availability
            # changed.
            super()._handle_coordinator_update()
            return
        self._handled_data = data
        if not self._fire_new_visits(data):
            super()._handle_coordinator_update()

    @callback
    def _fire_new_visits(self, data: SiiPetData) -> bool:
        """Fire each new visit of this cat in the snapshot. Return True if any fired."""
        fired = False
        for visit in data.new_visits:
            if self.cat_id in data.cat_ids(visit):
                self._trigger_event(visit.type.key, visit_attributes(data, visit))
                self.async_write_ha_state()
                fired = True
        return fired
