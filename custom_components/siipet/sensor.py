"""Sensors for the SiiPet integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import logging
from statistics import fmean
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .api import DeviceState, Visit, VisitType
from .const import UNKNOWN_CAT_ID
from .coordinator import SiiPetConfigEntry, SiiPetCoordinator, SiiPetData
from .entity import (
    SiiPetCameraEntity,
    SiiPetCameraStateEntity,
    SiiPetCatEntity,
    async_add_camera_entities,
    async_add_camera_state_entities,
    async_add_cat_entities,
    visit_attributes,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# The codes that the Android app names. Other codes give an unknown state.
FILL_LIGHT_LEVELS: dict[int, str] = {1: "low", 2: "medium", 3: "high"}
MOTION_LEVELS: dict[int, str] = {2: "medium", 3: "high"}
UPDATE_MODES: dict[int, str] = {0: "automatic", 1: "manual"}


def _today(data: SiiPetData, cat_id: str) -> list[Visit]:
    return data.visits(cat_id, data.today)


def _count(data: SiiPetData, cat_id: str, test: Callable[[Visit], bool]) -> int:
    return sum(1 for visit in _today(data, cat_id) if test(visit))


def _average_duration(data: SiiPetData, cat_id: str) -> float | None:
    durations = [
        visit.duration_ms / 1000
        for visit in _today(data, cat_id)
        if visit.type.is_litter_use
    ]
    return round(fmean(durations), 1) if durations else None


def _baseline(data: SiiPetData, cat_id: str, field: str, scale: float) -> float | None:
    summary = data.summaries.get(cat_id)
    if summary is None:
        return None
    return round(getattr(summary, field) / scale, 1)


def _baseline_progress(data: SiiPetData, cat_id: str) -> float | None:
    summary = data.summaries.get(cat_id)
    if summary is None or summary.needed_days <= 0:
        return None
    return round(min(100.0, 100 * summary.current_days / summary.needed_days))


def _last_visit(data: SiiPetData, cat_id: str) -> Visit | None:
    visits = data.visits(cat_id)
    return max(visits, key=lambda visit: visit.start) if visits else None


@dataclass(frozen=True, kw_only=True)
class SiiPetCatSensorDescription(SensorEntityDescription):
    """A sensor of a cat."""

    value_fn: Callable[[SiiPetData, str], StateType | datetime]
    attrs_fn: Callable[[SiiPetData, str], dict[str, Any] | None] = lambda _data, _cat: (
        None
    )
    daily: bool = False
    real_cat_only: bool = False
    unknown_cat_only: bool = False


def _daily(key: str, test: Callable[[Visit], bool]) -> SiiPetCatSensorDescription:
    return SiiPetCatSensorDescription(
        key=key,
        translation_key=key,
        state_class=SensorStateClass.TOTAL,
        daily=True,
        value_fn=lambda data, cat_id: _count(data, cat_id, test),
    )


CAT_SENSORS: tuple[SiiPetCatSensorDescription, ...] = (
    _daily("visits_today", lambda visit: visit.type.is_litter_use),
    _daily("pee_today", lambda visit: visit.type is VisitType.PEE),
    _daily("poop_today", lambda visit: visit.type is VisitType.POOP),
    _daily("lingering_today", lambda visit: visit.type is VisitType.LINGERING),
    _daily("abnormal_visits_today", lambda visit: visit.abnormal),
    SiiPetCatSensorDescription(
        key="average_duration_today",
        translation_key="average_duration_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_average_duration,
    ),
    SiiPetCatSensorDescription(
        key="baseline_visits",
        translation_key="baseline_visits",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        real_cat_only=True,
        value_fn=lambda data, cat_id: _baseline(data, cat_id, "baseline_times", 1),
    ),
    SiiPetCatSensorDescription(
        key="baseline_duration",
        translation_key="baseline_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        real_cat_only=True,
        value_fn=lambda data, cat_id: _baseline(data, cat_id, "baseline_avg_ms", 1000),
    ),
    SiiPetCatSensorDescription(
        key="baseline_progress",
        translation_key="baseline_progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        real_cat_only=True,
        value_fn=_baseline_progress,
    ),
    SiiPetCatSensorDescription(
        key="last_visit",
        translation_key="last_visit",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data, cat_id: (
            visit.start if (visit := _last_visit(data, cat_id)) else None
        ),
        attrs_fn=lambda data, cat_id: (
            visit_attributes(data, visit)
            if (visit := _last_visit(data, cat_id))
            else None
        ),
    ),
    SiiPetCatSensorDescription(
        key="unassigned_visits",
        translation_key="unassigned_visits",
        state_class=SensorStateClass.MEASUREMENT,
        unknown_cat_only=True,
        value_fn=lambda data, cat_id: len(data.visits(cat_id)),
    ),
)

SUBSCRIPTION_SENSOR = SensorEntityDescription(
    key="subscription_expires",
    translation_key="subscription_expires",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
)


@dataclass(frozen=True, kw_only=True)
class SiiPetCameraStateSensorDescription(SensorEntityDescription):
    """A sensor of the device state of a camera.

    With `codes`, the sensor is an enum, and `value_fn` returns the code.
    With `icon_fn`, a returned icon replaces the default icon.
    """

    value_fn: Callable[[DeviceState], StateType | datetime]
    codes: Mapping[int, str] | None = None
    icon_fn: Callable[[DeviceState], str | None] | None = None


def _battery_icon(state: DeviceState) -> str | None:
    """A charging battery icon, or None to keep the default level icon.

    The steps floor the level like the range icons of a battery sensor,
    so the shown level stays the same when charging starts.
    """
    if state.charging is not True or state.battery is None:
        return None
    level = min(max(state.battery, 0), 100)
    if level < 10:
        return "mdi:battery-charging-outline"
    if level == 100:
        return "mdi:battery-charging"
    return f"mdi:battery-charging-{level // 10 * 10}"


def _enum(
    key: str, codes: Mapping[int, str], value_fn: Callable[[DeviceState], int | None]
) -> SiiPetCameraStateSensorDescription:
    return SiiPetCameraStateSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENUM,
        options=list(codes.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
        codes=codes,
        value_fn=value_fn,
    )


CAMERA_STATE_SENSORS: tuple[SiiPetCameraStateSensorDescription, ...] = (
    SiiPetCameraStateSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.battery,
        icon_fn=_battery_icon,
    ),
    SiiPetCameraStateSensorDescription(
        key="last_report",
        translation_key="last_report",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.reported_at,
    ),
    SiiPetCameraStateSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.rssi,
    ),
    _enum("fill_light", FILL_LIGHT_LEVELS, lambda state: state.fill_light),
    _enum("motion_sensitivity", MOTION_LEVELS, lambda state: state.motion_level),
    _enum("update_mode", UPDATE_MODES, lambda state: state.update_mode),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SiiPetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add cat and camera sensors."""

    def build_cat(coordinator: SiiPetCoordinator, cat_id: str) -> list[SiiPetCatSensor]:
        unknown = cat_id == UNKNOWN_CAT_ID
        return [
            SiiPetCatSensor(coordinator, cat_id, description)
            for description in CAT_SENSORS
            if not (unknown and description.real_cat_only)
            and not (not unknown and description.unknown_cat_only)
        ]

    def build_camera(
        coordinator: SiiPetCoordinator, sn: str
    ) -> list[SiiPetSubscriptionSensor]:
        return [SiiPetSubscriptionSensor(coordinator, sn)]

    def build_camera_state(sn: str) -> list[SiiPetCameraStateSensor]:
        return [
            SiiPetCameraStateSensor(entry, sn, description)
            for description in CAMERA_STATE_SENSORS
        ]

    async_add_cat_entities(entry, async_add_entities, build_cat)
    async_add_camera_entities(entry, async_add_entities, build_camera)
    async_add_camera_state_entities(entry, async_add_entities, build_camera_state)


class SiiPetCatSensor(SiiPetCatEntity, SensorEntity):
    """A statistics sensor of a cat."""

    entity_description: SiiPetCatSensorDescription

    def __init__(
        self,
        coordinator: SiiPetCoordinator,
        cat_id: str,
        description: SiiPetCatSensorDescription,
    ) -> None:
        """Create the sensor."""
        super().__init__(coordinator, cat_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """The sensor value."""
        return self.entity_description.value_fn(self.coordinator.data, self.cat_id)

    @property
    def last_reset(self) -> datetime | None:
        """Local midnight of the current day, for daily counts."""
        if not self.entity_description.daily:
            return None
        return dt_util.start_of_local_day(self.coordinator.data.today)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra attributes of the sensor."""
        return self.entity_description.attrs_fn(self.coordinator.data, self.cat_id)


class SiiPetSubscriptionSensor(SiiPetCameraEntity, SensorEntity):
    """The subscription expiry of a camera."""

    entity_description = SUBSCRIPTION_SENSOR

    def __init__(self, coordinator: SiiPetCoordinator, sn: str) -> None:
        """Create the sensor."""
        super().__init__(coordinator, sn, SUBSCRIPTION_SENSOR.key)

    @property
    def native_value(self) -> datetime | None:
        """The expiry time, or None without a subscription."""
        return self.coordinator.data.cameras[self.sn].subscription_expires


class SiiPetCameraStateSensor(SiiPetCameraStateEntity, SensorEntity):
    """A sensor of the device state of a camera."""

    entity_description: SiiPetCameraStateSensorDescription

    def __init__(
        self,
        entry: SiiPetConfigEntry,
        sn: str,
        description: SiiPetCameraStateSensorDescription,
    ) -> None:
        """Create the sensor."""
        super().__init__(entry, sn, description.key)
        self.entity_description = description
        self._logged_codes: set[int] = set()

    @property
    def native_value(self) -> StateType | datetime:
        """The value, or the option name of an enum code."""
        value = self.entity_description.value_fn(self.state_data)
        codes = self.entity_description.codes
        if codes is None or not isinstance(value, int):
            return value
        option = codes.get(value)
        if option is None and value not in self._logged_codes:
            self._logged_codes.add(value)
            _LOGGER.debug("%s has the unknown code %s", self.entity_id, value)
        return option

    @property
    def icon(self) -> str | None:
        """The icon from `icon_fn` while available, else the default icon."""
        icon_fn = self.entity_description.icon_fn
        if icon_fn is not None and self.available:
            return icon_fn(self.state_data) or super().icon
        return super().icon
