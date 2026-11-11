"""Tests for the plans of camera setting changes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.siipet.api import (
    DeviceSettings,
    DeviceState,
    SettingUnavailableError,
)
from custom_components.siipet.api.settings import (
    FillLightChange,
    MotionChange,
    PrivacyChange,
    SettingGroup,
    group_of,
    plan_change,
    reports,
)

STATE = DeviceState(
    privacy=False,
    fill_light=2,
    fill_light_auto=True,
    fill_light_night_vision=True,
    motion_level=3,
    online=True,
    firmware="0.0.7.13",
)
SETTINGS = DeviceSettings(fill_light={1: 40, 2: 70, 3: 120}, pir={2: 75, 3: 60})


def test_fill_light_level() -> None:
    """A level change sends the whole object with the mapped brightness."""
    planned = plan_change(FillLightChange(level=3), STATE, SETTINGS)
    assert planned is not None
    assert planned.group is SettingGroup.FILL_LIGHT
    assert planned.desired_key == "fillLight"
    assert planned.command == "config.fillLight"
    assert planned.payload == {
        "level": 3,
        "brightness2": 120,
        "autoLight": True,
        "lowLight": True,
    }
    assert planned.expected == {
        "fill_light": 3,
        "fill_light_auto": True,
        "fill_light_night_vision": True,
    }


def test_fill_light_switch_keeps_the_other_fields() -> None:
    """Turning auto off keeps the reported level and night vision."""
    planned = plan_change(FillLightChange(auto=False), STATE, SETTINGS)
    assert planned is not None
    assert planned.payload == {
        "level": 2,
        "brightness2": 70,
        "autoLight": False,
        "lowLight": True,
    }


def test_fill_light_brightness_fallback() -> None:
    """Without a map entry, brightness2 is 60, as in the app."""
    planned = plan_change(FillLightChange(night_vision=False), STATE, DeviceSettings())
    assert planned is not None
    assert planned.payload["brightness2"] == 60


def test_fill_light_missing_sibling() -> None:
    """A field the camera has not reported is never invented."""
    state = replace(STATE, fill_light_auto=None)
    with pytest.raises(SettingUnavailableError) as err:
        plan_change(FillLightChange(level=1), state, SETTINGS)
    assert err.value.field == "fill_light_auto"


def test_fill_light_level_outside_range() -> None:
    """A reported level the app never sends is treated as unknown."""
    state = replace(STATE, fill_light=0)
    with pytest.raises(SettingUnavailableError):
        plan_change(FillLightChange(auto=False), state, SETTINGS)


def test_motion() -> None:
    """Motion sends sense from the map and the level."""
    planned = plan_change(MotionChange(level=2), STATE, SETTINGS)
    assert planned is not None
    assert planned.group is SettingGroup.MOTION
    assert planned.desired_key == "pir"
    assert planned.command == "config.pir.sense"
    assert planned.payload == {"sense": 75, "level": 2}
    assert planned.expected == {"motion_level": 2}


@pytest.mark.parametrize(("level", "sense"), [(2, 75), (3, 60)])
def test_motion_sense_fallback(level: int, sense: int) -> None:
    """Without a map entry, sense uses the app's values."""
    state = replace(STATE, motion_level=None)
    planned = plan_change(MotionChange(level=level), state, DeviceSettings())
    assert planned is not None
    assert planned.payload["sense"] == sense


def test_privacy() -> None:
    """Privacy is command only."""
    planned = plan_change(PrivacyChange(active=True), STATE, DeviceSettings())
    assert planned is not None
    assert planned.group is SettingGroup.PRIVACY
    assert planned.desired_key is None
    assert planned.command == "config.privacyMode"
    assert planned.payload == {"active": True}
    assert planned.expected == {"privacy": True}


@pytest.mark.parametrize(
    "change",
    [
        FillLightChange(level=2),
        FillLightChange(auto=True),
        FillLightChange(night_vision=True),
        MotionChange(level=3),
        PrivacyChange(active=False),
    ],
)
def test_already_reported(change: object) -> None:
    """A change the camera already reports needs nothing."""
    assert plan_change(change, STATE, SETTINGS) is None


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"level": 1, "auto": True}, {"level": 4}, {"level": 0}],
    ids=["none", "two", "high", "zero"],
)
def test_fill_light_change_needs_one_valid_field(kwargs: dict[str, object]) -> None:
    """Exactly one field, and a level from 1 to 3."""
    with pytest.raises(ValueError, match="fill light"):
        FillLightChange(**kwargs)


def test_motion_change_levels() -> None:
    """The app offers levels 2 and 3."""
    with pytest.raises(ValueError, match="motion level"):
        MotionChange(level=1)


def test_group_of() -> None:
    """Each change type has one group."""
    assert group_of(FillLightChange(level=1)) is SettingGroup.FILL_LIGHT
    assert group_of(MotionChange(level=2)) is SettingGroup.MOTION
    assert group_of(PrivacyChange(active=True)) is SettingGroup.PRIVACY


def test_reports() -> None:
    """Every expected field must match."""
    assert reports(STATE, {"fill_light": 2, "privacy": False})
    assert not reports(STATE, {"fill_light": 3, "privacy": False})
    assert not reports(replace(STATE, privacy=None), {"privacy": False})
