"""Errors raised by the SiiPet API client."""

from __future__ import annotations

from typing import Literal


class SiiPetError(Exception):
    """Base class for SiiPet API errors."""


class SiiPetConnectionError(SiiPetError):
    """The request timed out or the connection failed."""


class SiiPetApiError(SiiPetError):
    """The API returned a non-zero code."""

    def __init__(self, code: int, msg: str) -> None:
        """Keep the code and the message from the response envelope."""
        super().__init__(f"SiiPet API error {code}: {msg}")
        self.code = code
        self.msg = msg


class SiiPetAuthError(SiiPetError):
    """The API rejected the session token."""


type ShadowWriteReason = Literal["rejected", "not_ready"]

_SHADOW_WRITE_TEXT: dict[str, str] = {
    "rejected": "AWS IoT rejected the shadow write",
    "not_ready": "The shadow connection is not ready",
}


class ShadowWriteError(SiiPetError):
    """A `desired` write did not reach AWS IoT, or AWS IoT rejected it."""

    def __init__(self, reason: ShadowWriteReason) -> None:
        """Keep the reason. The text names no camera or topic."""
        super().__init__(_SHADOW_WRITE_TEXT[reason])
        self.reason = reason


class LrtmError(SiiPetError):
    """The realtime command lane failed."""


class LrtmTransportError(LrtmError):
    """The realtime server could not be reached, did not answer, or closed."""


class LrtmUnconfirmedError(LrtmTransportError):
    """The command went out, but the realtime server did not confirm it.

    The camera may still apply the command.
    """

    def __init__(self) -> None:
        """Use a fixed text."""
        super().__init__("The realtime server did not confirm the command")


class LrtmServerError(LrtmError):
    """The realtime server answered a command with an error code."""

    def __init__(self, code: int | None) -> None:
        """Keep only the code. The server's message can name the channel."""
        super().__init__(f"The realtime server answered with error {code}")
        self.code = code


class SettingUnavailableError(SiiPetError):
    """The camera has not reported a field that a change needs."""

    def __init__(self, field: str) -> None:
        """`field` is a DeviceState field name."""
        super().__init__(f"The camera has not reported {field}")
        self.field = field
