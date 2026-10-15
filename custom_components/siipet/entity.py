"""Base entities for the SiiPet integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Camera, DeviceState, SiiPetError, Visit
from .const import CAT_MODEL, DOMAIN, MANUFACTURER, UNKNOWN_CAT_ID, UNKNOWN_CAT_NAME
from .coordinator import SiiPetConfigEntry, SiiPetCoordinator, SiiPetData
from .device_state import SiiPetDeviceCoordinator


def camera_device_info(camera: Camera) -> DeviceInfo:
    """The device of a camera. Every camera entity uses the same info."""
    return DeviceInfo(
        identifiers={(DOMAIN, camera.sn)},
        name=camera.name,
        manufacturer=MANUFACTURER,
        model=camera.product_id or None,
    )


def visit_attributes(data: SiiPetData, visit: Visit) -> dict[str, Any]:
    """State attributes of a visit. They hold no serial numbers or account ids."""
    camera = data.cameras.get(visit.sn)
    return {
        "event_id": visit.event_id,
        "type": visit.type.key,
        "duration": round(visit.duration_ms / 1000),
        "camera": camera.name if camera else None,
        "cats": [
            data.cats[cat_id].name
            for cat_id in data.cat_ids(visit)
            if cat_id in data.cats
        ],
        "abnormal": visit.abnormal,
        "abnormal_reasons": data.labels.reasons(visit),
    }


class SiiPetCatEntity(CoordinatorEntity[SiiPetCoordinator]):
    """An entity of one cat, or of the virtual Unknown cat."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SiiPetCoordinator, cat_id: str, key: str) -> None:
        """Bind the entity to a cat device."""
        super().__init__(coordinator)
        self.cat_id = cat_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{cat_id}_{key}"
        cat = coordinator.data.cats.get(cat_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, cat_id)},
            name=cat.name if cat else UNKNOWN_CAT_NAME,
            manufacturer=MANUFACTURER,
            model=CAT_MODEL,
        )

    @property
    def available(self) -> bool:
        """A cat that left the account becomes unavailable."""
        return super().available and (
            self.cat_id == UNKNOWN_CAT_ID or self.cat_id in self.coordinator.data.cats
        )


class SiiPetCameraEntity(CoordinatorEntity[SiiPetCoordinator]):
    """An entity of one camera."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SiiPetCoordinator, sn: str, key: str) -> None:
        """Bind the entity to a camera device."""
        super().__init__(coordinator)
        self.sn = sn
        self._attr_translation_key = key
        self._attr_unique_id = f"{sn}_{key}"
        self._attr_device_info = camera_device_info(coordinator.data.cameras[sn])

    @property
    def available(self) -> bool:
        """A camera that left the account becomes unavailable."""
        return super().available and self.sn in self.coordinator.data.cameras


class SiiPetCameraStateEntity(CoordinatorEntity[SiiPetDeviceCoordinator]):
    """An entity of one camera that shows its device state."""

    _attr_has_entity_name = True

    def __init__(self, entry: SiiPetConfigEntry, sn: str, key: str) -> None:
        """Bind the entity to a camera device."""
        runtime = entry.runtime_data
        super().__init__(runtime.device_state)
        self._main = runtime.coordinator
        self.sn = sn
        self._attr_translation_key = key
        self._attr_unique_id = f"{sn}_{key}"
        self._attr_device_info = camera_device_info(
            runtime.coordinator.data.cameras[sn]
        )

    @property
    def state_data(self) -> DeviceState:
        """The device state of the camera. Read it only while available."""
        return self.coordinator.data[self.sn]

    @property
    def available(self) -> bool:
        """Available while the link works, and the camera has a state."""
        return (
            super().available
            and self.sn in self._main.data.cameras
            and self.sn in self.coordinator.data
        )

    async def async_added_to_hass(self) -> None:
        """Also follow the camera list, so a removed camera turns unavailable."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._main.async_add_listener(self._handle_coordinator_update)
        )

    async def async_update(self) -> None:
        """Do nothing. The shadow link pushes every value, so there is nothing to read."""


class SiiPetCameraControlEntity(SiiPetCameraStateEntity):
    """A camera device-state entity that can also send a control command.

    It shows a pending value until the next reported state arrives, so the
    control reacts at once even though the camera confirms over the shadow.
    """

    def __init__(self, entry: SiiPetConfigEntry, sn: str, key: str) -> None:
        """Bind the entity to a camera and its control client."""
        super().__init__(entry, sn, key)
        self._control = entry.runtime_data.control
        self._pending: Any = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """A fresh reported state clears the pending value."""
        self._pending = None
        super()._handle_coordinator_update()

    async def _async_send(
        self, command: str, payload: dict[str, Any], optimistic: Any
    ) -> None:
        """Send a command, showing `optimistic` until the camera confirms."""
        self._pending = optimistic
        self.async_write_ha_state()
        try:
            await self._control.send(self.sn, command, payload)
        except SiiPetError as err:
            self._pending = None
            self.async_write_ha_state()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="control_failed"
            ) from err


@callback
def async_add_cat_entities(
    entry: SiiPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[SiiPetCoordinator, str], Iterable[Entity]],
) -> None:
    """Add entities for each cat and the Unknown cat, and later for new cats."""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def _async_add_new() -> None:
        new = [
            cat_id
            for cat_id in (UNKNOWN_CAT_ID, *coordinator.data.cats)
            if cat_id not in known
        ]
        if not new:
            return
        known.update(new)
        async_add_entities(
            [entity for cat_id in new for entity in build(coordinator, cat_id)]
        )

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


@callback
def async_add_camera_entities(
    entry: SiiPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[SiiPetCoordinator, str], Iterable[Entity]],
) -> None:
    """Add entities for each camera, and later for new cameras."""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def _async_add_new() -> None:
        new = [sn for sn in coordinator.data.cameras if sn not in known]
        if not new:
            return
        known.update(new)
        async_add_entities([entity for sn in new for entity in build(coordinator, sn)])

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


@callback
def async_add_camera_state_entities(
    entry: SiiPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[str], Iterable[Entity]],
) -> None:
    """Add the device state entities of a camera when its first state arrives."""
    device_state = entry.runtime_data.device_state
    known: set[str] = set()

    @callback
    def _async_add_new() -> None:
        cameras = entry.runtime_data.coordinator.data.cameras
        new = [sn for sn in device_state.data if sn not in known and sn in cameras]
        if not new:
            return
        known.update(new)
        async_add_entities([entity for sn in new for entity in build(sn)])

    _async_add_new()
    entry.async_on_unload(device_state.async_add_listener(_async_add_new))
