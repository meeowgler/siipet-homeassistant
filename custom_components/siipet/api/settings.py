"""Plans for one camera setting change, built from the reported state. No I/O.

The values and the confirmation fields copy the Android app: the fill light
and the motion sensitivity are written to the shadow `desired` and sent as a
realtime command with the same object, privacy mode only as a command.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .errors import SettingUnavailableError
from .models import DeviceSettings, DeviceState

# The firmware feature that shows the fill light and motion settings in the app.
FEATURE_PIR_AND_FILL_LIGHT = "6"
FILL_LIGHT_LEVELS = (1, 2, 3)
MOTION_LEVELS = (2, 3)
# The app's values when `JOY1SystemConfig` has no entry for a level.
FILL_LIGHT_BRIGHTNESS_FALLBACK = 60
MOTION_SENSE_FALLBACK = {2: 75, 3: 60}


class SettingGroup(StrEnum):
    """Settings that one change writes together. One change per group runs at a time."""

    FILL_LIGHT = "fill_light"
    MOTION = "motion"
    PRIVACY = "privacy"


@dataclass(frozen=True, slots=True)
class FillLightChange:
    """Change one field of the fill light."""

    level: int | None = None
    auto: bool | None = None
    night_vision: bool | None = None

    def __post_init__(self) -> None:
        """Allow exactly one field, and a level the app offers."""
        given = [v for v in (self.level, self.auto, self.night_vision) if v is not None]
        if len(given) != 1:
            raise ValueError("Set exactly one fill light field")
        if self.level is not None and self.level not in FILL_LIGHT_LEVELS:
            raise ValueError("The fill light level must be 1, 2, or 3")


@dataclass(frozen=True, slots=True)
class MotionChange:
    """Change the motion sensitivity level."""

    level: int

    def __post_init__(self) -> None:
        """Allow the levels the app offers."""
        if self.level not in MOTION_LEVELS:
            raise ValueError("The motion level must be 2 or 3")


@dataclass(frozen=True, slots=True)
class PrivacyChange:
    """Turn privacy mode on or off."""

    active: bool


type SettingChange = FillLightChange | MotionChange | PrivacyChange


@dataclass(frozen=True, slots=True)
class PlannedChange:
    """What one change sends, and which reported fields confirm it."""

    group: SettingGroup
    desired_key: str | None
    command: str
    payload: Mapping[str, Any]
    expected: Mapping[str, Any]


def group_of(change: SettingChange) -> SettingGroup:
    """Return the group that a change writes."""
    if isinstance(change, FillLightChange):
        return SettingGroup.FILL_LIGHT
    if isinstance(change, MotionChange):
        return SettingGroup.MOTION
    return SettingGroup.PRIVACY


def reports(state: DeviceState, expected: Mapping[str, Any]) -> bool:
    """True when the state reports every expected field value."""
    return all(getattr(state, name) == value for name, value in expected.items())


def plan_change(
    change: SettingChange, state: DeviceState, settings: DeviceSettings
) -> PlannedChange | None:
    """Plan a change. Return None when the camera already reports it.

    Raise SettingUnavailableError when a field that the change keeps is unknown.
    """
    if isinstance(change, FillLightChange):
        planned = _plan_fill_light(change, state, settings)
    elif isinstance(change, MotionChange):
        planned = _plan_motion(change, settings)
    else:
        planned = PlannedChange(
            group=SettingGroup.PRIVACY,
            desired_key=None,
            command="config.privacyMode",
            payload={"active": change.active},
            expected={"privacy": change.active},
        )
    return None if reports(state, planned.expected) else planned


def _plan_fill_light(
    change: FillLightChange, state: DeviceState, settings: DeviceSettings
) -> PlannedChange:
    level = change.level
    if level is None:
        level = _known(state.fill_light, "fill_light")
        if level not in FILL_LIGHT_LEVELS:
            raise SettingUnavailableError("fill_light")
    auto = change.auto
    if auto is None:
        auto = _known(state.fill_light_auto, "fill_light_auto")
    night_vision = change.night_vision
    if night_vision is None:
        night_vision = _known(state.fill_light_night_vision, "fill_light_night_vision")
    return PlannedChange(
        group=SettingGroup.FILL_LIGHT,
        desired_key="fillLight",
        command="config.fillLight",
        payload={
            "level": level,
            "brightness2": settings.fill_light.get(
                level, FILL_LIGHT_BRIGHTNESS_FALLBACK
            ),
            "autoLight": auto,
            "lowLight": night_vision,
        },
        expected={
            "fill_light": level,
            "fill_light_auto": auto,
            "fill_light_night_vision": night_vision,
        },
    )


def _plan_motion(change: MotionChange, settings: DeviceSettings) -> PlannedChange:
    sense = settings.pir.get(change.level, MOTION_SENSE_FALLBACK[change.level])
    return PlannedChange(
        group=SettingGroup.MOTION,
        desired_key="pir",
        command="config.pir.sense",
        payload={"sense": sense, "level": change.level},
        expected={"motion_level": change.level},
    )


def _known[T](value: T | None, name: str) -> T:
    if value is None:
        raise SettingUnavailableError(name)
    return value
