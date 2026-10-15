"""The fill-light brightness select of each camera."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .commands import (
    FILL_LIGHT_COMMAND,
    FILL_LIGHT_LEVELS,
    FILL_LIGHT_OPTIONS,
    fill_light_payload,
)
from .coordinator import SiiPetConfigEntry
from .entity import SiiPetCameraControlEntity, async_add_camera_state_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SiiPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the fill-light select of each camera."""
    async_add_camera_state_entities(
        entry, async_add_entities, lambda sn: [SiiPetFillLightSelect(entry, sn)]
    )


class SiiPetFillLightSelect(SiiPetCameraControlEntity, SelectEntity):
    """Set the night-light brightness level of a camera."""

    def __init__(self, entry: SiiPetConfigEntry, sn: str) -> None:
        """Bind the select to a camera."""
        super().__init__(entry, sn, "fill_light_brightness")
        self._attr_options = list(FILL_LIGHT_OPTIONS)

    @property
    def current_option(self) -> str | None:
        """The level the camera reports, or the pending choice."""
        if self._pending is not None:
            return self._pending
        return FILL_LIGHT_LEVELS.get(self.state_data.fill_light)

    async def async_select_option(self, option: str) -> None:
        """Set a new brightness level."""
        payload = fill_light_payload(self.state_data, level=FILL_LIGHT_OPTIONS[option])
        await self._async_send(FILL_LIGHT_COMMAND, payload, option)
