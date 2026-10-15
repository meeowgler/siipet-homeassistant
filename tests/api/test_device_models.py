"""Tests for the models of the AWS IoT credentials and the device shadows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from custom_components.siipet.api import (
    Camera,
    CameraShadows,
    DeviceState,
    IotCredentials,
)
from custom_components.siipet.api.models import (
    CONFIG_SHADOW,
    SYSTEM_SHADOW,
    parse_shadow,
)

from ..common import load_data, load_fixture


def test_iot_credentials_from_api() -> None:
    """The endpoint loses its scheme, and the region comes from the host."""
    credentials = IotCredentials.from_api(load_data("aws_auth.json"))
    assert credentials.endpoint == "example-ats.iot.us-east-1.amazonaws.com"
    assert credentials.region == "us-east-1"
    assert credentials.access_key_id == "AKIDEXAMPLE"
    assert credentials.identity_id == "us-east-1:identity-0001"
    assert credentials.expires == datetime(2026, 9, 26, 22, 0, tzinfo=UTC)
    text = repr(credentials)
    for private in ("example-ats", "AKIDEXAMPLE", "EXAMPLEKEY", "token+part"):
        assert private not in text
    assert "identity-0001" not in text


def test_iot_credentials_bare_host() -> None:
    """An endpoint without a scheme is a host already."""
    data = load_data("aws_auth.json")
    data["IotCore"]["Endpoint"] = "example-ats.iot.eu-west-1.amazonaws.com"
    assert IotCredentials.from_api(data).region == "eu-west-1"


@pytest.mark.parametrize(
    "endpoint",
    ["https://example.com", "https://iot.amazonaws.com", "", "https://"],
)
def test_iot_credentials_bad_endpoint(endpoint: str) -> None:
    """An endpoint that is not an AWS IoT data host is refused."""
    data = load_data("aws_auth.json")
    data["IotCore"]["Endpoint"] = endpoint
    with pytest.raises(ValueError, match="IoT endpoint"):
        IotCredentials.from_api(data)


def test_camera_shadows() -> None:
    """A camera keeps its shadow names, and its repr hides them."""
    camera = Camera.from_api(load_data("device_sync.json")["List"][0])
    assert camera.shadows == CameraShadows(
        config="fake_configInfo", system="fake_systemInfo"
    )
    assert camera.shadows.name(CONFIG_SHADOW) == "fake_configInfo"
    assert camera.shadows.name(SYSTEM_SHADOW) == "fake_systemInfo"
    assert "prod_" not in repr(camera)


@pytest.mark.parametrize(
    "topic",
    [
        None,
        {},
        {"Shadow": None},
        {"Shadow": {"configInfo": "fake_configInfo"}},
        {"Shadow": {"configInfo": "", "systemInfo": "fake_systemInfo"}},
        {"Shadow": {"configInfo": 1, "systemInfo": "fake_systemInfo"}},
    ],
)
def test_camera_without_shadows(topic: Any) -> None:
    """A camera without both shadow names has no shadows."""
    camera = Camera.from_api({"SN": "SN0099", "Topic": topic})
    assert camera.shadows is None


def test_parse_config_shadow() -> None:
    """The config shadow gives battery and settings, from `state.reported` only."""
    part = parse_shadow(CONFIG_SHADOW, load_fixture("shadow_config_accepted.json"))
    assert part is not None
    assert part.values == {
        "battery": 72,
        "charging": False,
        "privacy": False,
        "fill_light": 2,
        "fill_light_auto": True,
        "fill_light_low": True,
        "fill_light_brightness": 70,
        "motion_level": 3,
        "update_mode": 0,
        "cloud_storage": True,
    }
    assert part.reported_at == datetime(2026, 9, 26, 11, 50, tzinfo=UTC)
    assert part.version == 12


def test_parse_system_shadow() -> None:
    """The system shadow gives online, firmware, and signal, and no network names."""
    part = parse_shadow(SYSTEM_SHADOW, load_fixture("shadow_system_accepted.json"))
    assert part is not None
    assert part.values == {"online": True, "firmware": "1.2.3", "rssi": -61}
    assert part.reported_at == datetime(2026, 9, 26, 11, 55, tzinfo=UTC)
    assert part.version == 40


def test_parse_update_document() -> None:
    """An update message is read from `current`."""
    part = parse_shadow(CONFIG_SHADOW, load_fixture("shadow_config_update.json"))
    assert part is not None
    assert part.values["battery"] == 81
    assert part.values["charging"] is True
    assert part.values["privacy"] is True
    assert part.values["fill_light"] is None
    assert part.reported_at == datetime(2026, 9, 26, 12, 1, tzinfo=UTC)
    assert part.version == 13


@pytest.mark.parametrize(
    "message",
    [None, [], "text", {}, {"state": {}}, {"state": {"reported": 5}}, {"current": 5}],
)
def test_parse_shadow_other_shapes(message: Any) -> None:
    """A message without a `state.reported` object gives no part."""
    assert parse_shadow(CONFIG_SHADOW, message) is None


@pytest.mark.parametrize(
    ("reported", "field", "value"),
    [
        ({"battery": {"SOC": True}}, "battery", None),
        ({"battery": {"SOC": "72"}}, "battery", None),
        ({"battery": {"SOC": float("nan")}}, "battery", None),
        ({"battery": {"SOC": 72.5}}, "battery", 73),
        ({"battery": {"SOC": 100}}, "battery", 100),
        ({"battery": {"charging": 1}}, "charging", None),
        ({"fillLight": {"level": 2.0}}, "fill_light", None),
        ({"fillLight": {"level": True}}, "fill_light", None),
        ({"privacyMode": "on"}, "privacy", None),
    ],
)
def test_parse_shadow_wrong_types(reported: Any, field: str, value: Any) -> None:
    """A value of the wrong type becomes None."""
    part = parse_shadow(CONFIG_SHADOW, {"state": {"reported": reported}})
    assert part is not None
    assert part.values[field] == value


def test_device_state_from_parts() -> None:
    """Both parts merge, and the newest report time wins."""
    config = parse_shadow(CONFIG_SHADOW, load_fixture("shadow_config_accepted.json"))
    system = parse_shadow(SYSTEM_SHADOW, load_fixture("shadow_system_accepted.json"))
    state = DeviceState.from_parts(config, system)
    assert state == DeviceState(
        battery=72,
        charging=False,
        privacy=False,
        fill_light=2,
        fill_light_auto=True,
        fill_light_low=True,
        fill_light_brightness=70,
        motion_level=3,
        update_mode=0,
        cloud_storage=True,
        online=True,
        firmware="1.2.3",
        rssi=-61,
        reported_at=datetime(2026, 9, 26, 11, 55, tzinfo=UTC),
    )


def test_device_state_from_one_part() -> None:
    """A missing part leaves its fields None."""
    system = parse_shadow(SYSTEM_SHADOW, load_fixture("shadow_system_accepted.json"))
    state = DeviceState.from_parts(None, system)
    assert state.battery is None
    assert state.online is True
