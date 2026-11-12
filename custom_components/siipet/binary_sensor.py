"""Binary sensors for the SiiPet integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DeviceState
from .coordinator import SiiPetConfigEntry
from .entity import SiiPetCameraStateEntity, async_add_camera_state_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SiiPetCameraStateBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor of the device state of a camera."""

    value_fn: Callable[[DeviceState], bool | None]


CAMERA_STATE_BINARY_SENSORS: tuple[SiiPetCameraStateBinarySensorDescription, ...] = (
    SiiPetCameraStateBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=lambda state: state.charging,
    ),
    SiiPetCameraStateBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.online,
    ),
    SiiPetCameraStateBinarySensorDescription(
        key="cloud_storage",
        translation_key="cloud_storage",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.cloud_storage,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SiiPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the device state binary sensors of each camera."""

    def build(sn: str) -> list[SiiPetCameraStateBinarySensor]:
        return [
            SiiPetCameraStateBinarySensor(entry, sn, description)
            for description in CAMERA_STATE_BINARY_SENSORS
        ]

    async_add_camera_state_entities(entry, async_add_entities, build)


class SiiPetCameraStateBinarySensor(SiiPetCameraStateEntity, BinarySensorEntity):
    """A binary sensor of the device state of a camera."""

    entity_description: SiiPetCameraStateBinarySensorDescription

    def __init__(
        self,
        entry: SiiPetConfigEntry,
        sn: str,
        description: SiiPetCameraStateBinarySensorDescription,
    ) -> None:
        """Create the binary sensor."""
        super().__init__(entry, sn, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """The value, or None when the shadow has none."""
        return self.entity_description.value_fn(self.state_data)
