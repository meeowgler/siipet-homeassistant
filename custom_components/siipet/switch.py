"""The fill-light switches of each camera: auto fill light and night vision."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DeviceState
from .commands import FILL_LIGHT_COMMAND, fill_light_payload
from .coordinator import SiiPetConfigEntry
from .entity import SiiPetCameraControlEntity, async_add_camera_state_entities


@dataclass(frozen=True, kw_only=True)
class SiiPetSwitchDescription(SwitchEntityDescription):
    """A camera switch: how to read it, and the payload to set it."""

    value_fn: Callable[[DeviceState], bool | None]
    payload_fn: Callable[[DeviceState, bool], dict[str, object]]


SWITCHES: tuple[SiiPetSwitchDescription, ...] = (
    SiiPetSwitchDescription(
        key="auto_fill_light",
        translation_key="auto_fill_light",
        value_fn=lambda state: state.fill_light_auto,
        payload_fn=lambda state, on: fill_light_payload(state, auto=on),
    ),
    SiiPetSwitchDescription(
        key="night_vision",
        translation_key="night_vision",
        value_fn=lambda state: state.fill_light_low,
        payload_fn=lambda state, on: fill_light_payload(state, low=on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SiiPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the fill-light switches of each camera."""
    async_add_camera_state_entities(
        entry,
        async_add_entities,
        lambda sn: [SiiPetSwitch(entry, sn, description) for description in SWITCHES],
    )


class SiiPetSwitch(SiiPetCameraControlEntity, SwitchEntity):
    """A camera fill-light switch."""

    entity_description: SiiPetSwitchDescription

    def __init__(
        self, entry: SiiPetConfigEntry, sn: str, description: SiiPetSwitchDescription
    ) -> None:
        """Bind the switch to a camera."""
        super().__init__(entry, sn, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Whether the field is on, or the pending choice."""
        if self._pending is not None:
            return self._pending
        return self.entity_description.value_fn(self.state_data)

    async def async_turn_on(self, **kwargs: object) -> None:
        """Turn the field on."""
        await self._set(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Turn the field off."""
        await self._set(False)

    async def _set(self, on: bool) -> None:
        payload = self.entity_description.payload_fn(self.state_data, on)
        await self._async_send(FILL_LIGHT_COMMAND, payload, on)
