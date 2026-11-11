"""Tests for the error texts of the control lane."""

from __future__ import annotations

import pytest

from custom_components.siipet.api import (
    LrtmError,
    LrtmServerError,
    LrtmTransportError,
    SettingUnavailableError,
    ShadowWriteError,
    SiiPetError,
)


def test_shadow_write_rejected() -> None:
    """A rejected write keeps its reason and says only that AWS IoT rejected it."""
    err = ShadowWriteError("rejected")
    assert err.reason == "rejected"
    assert str(err) == "AWS IoT rejected the shadow write"


def test_shadow_write_not_ready() -> None:
    """A write without a connection says so."""
    err = ShadowWriteError("not_ready")
    assert err.reason == "not_ready"
    assert str(err) == "The shadow connection is not ready"


def test_server_error_keeps_only_the_code() -> None:
    """The server's message can name the channel, so only the code is kept."""
    err = LrtmServerError(103)
    assert err.code == 103
    assert str(err) == "The realtime server answered with error 103"
    assert str(LrtmServerError(None)) == "The realtime server answered with error None"


def test_setting_unavailable_names_the_field() -> None:
    """The missing field is a DeviceState field name."""
    err = SettingUnavailableError("fill_light_auto")
    assert err.field == "fill_light_auto"
    assert str(err) == "The camera has not reported fill_light_auto"


@pytest.mark.parametrize(
    "err",
    [
        ShadowWriteError("rejected"),
        LrtmTransportError("Could not reach the realtime server"),
        LrtmServerError(103),
        SettingUnavailableError("privacy"),
    ],
)
def test_control_errors_are_siipet_errors(err: Exception) -> None:
    """Callers catch every control error as a SiiPetError."""
    assert isinstance(err, SiiPetError)


def test_realtime_errors_share_a_base() -> None:
    """Transport and server errors are both LrtmError."""
    assert issubclass(LrtmTransportError, LrtmError)
    assert issubclass(LrtmServerError, LrtmError)
