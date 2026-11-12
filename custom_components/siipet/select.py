"""Camera setting selects: night light brightness and motion sensitivity."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DeviceState
from .api.settings import FillLightChange, MotionChange, SettingChange
from .coordinator import SiiPetConfigEntry
from .entity import SiiPetCameraStateEntity, async_add_camera_state_entities

# The device hub queues changes itself.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SiiPetSelectDescription(SelectEntityDescription):
    """A select of one camera setting: its levels, how to read it, how to change it."""

    levels: Mapping[int, str]
    value_fn: Callable[[DeviceState], int | None]
    change_fn: Callable[[int], SettingChange]


SELECTS: tuple[SiiPetSelectDescription, ...] = (
    SiiPetSelectDescription(
        key="fill_light_level",
        translation_key="fill_light_level",
        entity_category=EntityCategory.CONFIG,
        levels={1: "low", 2: "standard", 3: "high"},
        value_fn=lambda state: state.fill_light,
        change_fn=lambda level: FillLightChange(level=level),
    ),
    SiiPetSelectDescription(
        key="motion_sensitivity",
        translation_key="motion_sensitivity",
        entity_category=EntityCategory.CONFIG,
        levels={2: "standard", 3: "high"},
        value_fn=lambda state: state.motion_level,
        change_fn=lambda level: MotionChange(level=level),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SiiPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the setting selects of each camera."""
    async_add_camera_state_entities(
        entry,
        async_add_entities,
        lambda sn: [
            SiiPetSettingSelect(entry, sn, description) for description in SELECTS
        ],
    )


class SiiPetSettingSelect(SiiPetCameraStateEntity, SelectEntity):
    """A camera setting with levels."""

    entity_description: SiiPetSelectDescription

    def __init__(
        self, entry: SiiPetConfigEntry, sn: str, description: SiiPetSelectDescription
    ) -> None:
        """Bind the select to a camera."""
        super().__init__(entry, sn, description.key)
        self.entity_description = description
        self._attr_options = list(description.levels.values())
        self._levels = {name: level for level, name in description.levels.items()}

    @property
    def current_option(self) -> str | None:
        """The reported level, or None for a level outside the options."""
        level = self.entity_description.value_fn(self.state_data)
        return self.entity_description.levels.get(level) if level is not None else None

    async def async_select_option(self, option: str) -> None:
        """Change the level and wait until the camera reports it."""
        await self.coordinator.async_apply(
            self.sn, self.entity_description.change_fn(self._levels[option])
        )
