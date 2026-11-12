"""Camera setting switches: auto fill light, night vision fill light, privacy mode."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DeviceState
from .api.settings import FillLightChange, PrivacyChange, SettingChange
from .coordinator import SiiPetConfigEntry
from .entity import SiiPetCameraStateEntity, async_add_camera_state_entities

# The device hub queues changes itself.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SiiPetSwitchDescription(SwitchEntityDescription):
    """A switch of one camera setting: how to read it and how to change it."""

    value_fn: Callable[[DeviceState], bool | None]
    change_fn: Callable[[bool], SettingChange]


SWITCHES: tuple[SiiPetSwitchDescription, ...] = (
    SiiPetSwitchDescription(
        key="auto_fill_light",
        translation_key="auto_fill_light",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: state.fill_light_auto,
        change_fn=lambda on: FillLightChange(auto=on),
    ),
    SiiPetSwitchDescription(
        key="night_vision_fill_light",
        translation_key="night_vision_fill_light",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda state: state.fill_light_night_vision,
        change_fn=lambda on: FillLightChange(night_vision=on),
    ),
    SiiPetSwitchDescription(
        key="privacy_mode",
        translation_key="privacy_mode",
        value_fn=lambda state: state.privacy,
        change_fn=lambda on: PrivacyChange(active=on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SiiPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the setting switches of each camera."""
    async_add_camera_state_entities(
        entry,
        async_add_entities,
        lambda sn: [
            SiiPetSettingSwitch(entry, sn, description) for description in SWITCHES
        ],
    )


class SiiPetSettingSwitch(SiiPetCameraStateEntity, SwitchEntity):
    """A camera setting that is on or off."""

    entity_description: SiiPetSwitchDescription

    def __init__(
        self, entry: SiiPetConfigEntry, sn: str, description: SiiPetSwitchDescription
    ) -> None:
        """Bind the switch to a camera."""
        super().__init__(entry, sn, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """The reported value."""
        return self.entity_description.value_fn(self.state_data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on and wait until the camera reports it."""
        await self.coordinator.async_apply(
            self.sn, self.entity_description.change_fn(True)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off and wait until the camera reports it."""
        await self.coordinator.async_apply(
            self.sn, self.entity_description.change_fn(False)
        )
