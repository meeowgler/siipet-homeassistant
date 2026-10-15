"""Device command payloads for the realtime control lane."""

from __future__ import annotations

from .api import DeviceState

# The command that sets the night-light fields.
FILL_LIGHT_COMMAND = "config.fillLight"

# The brightness the app sends for each night-light level (1 low, 2 medium, 3 high).
FILL_LIGHT_BRIGHTNESS = {1: 40, 2: 70, 3: 120}
# The levels the integration offers, and their option names.
FILL_LIGHT_LEVELS = {1: "low", 2: "medium", 3: "high"}
FILL_LIGHT_OPTIONS = {name: level for level, name in FILL_LIGHT_LEVELS.items()}
DEFAULT_LEVEL = 2


def fill_light_payload(
    state: DeviceState,
    *,
    level: int | None = None,
    auto: bool | None = None,
    low: bool | None = None,
) -> dict[str, object]:
    """Build a `config.fillLight` payload, changing one field and keeping the rest.

    The camera takes all four fields together, so the current values fill in
    whatever is not being changed.
    """
    use_level = level if level is not None else (state.fill_light or DEFAULT_LEVEL)
    if level is not None:
        brightness = FILL_LIGHT_BRIGHTNESS.get(
            level, FILL_LIGHT_BRIGHTNESS[DEFAULT_LEVEL]
        )
    elif state.fill_light_brightness is not None:
        brightness = state.fill_light_brightness
    else:
        brightness = FILL_LIGHT_BRIGHTNESS.get(
            use_level, FILL_LIGHT_BRIGHTNESS[DEFAULT_LEVEL]
        )
    return {
        "autoLight": auto if auto is not None else _default(state.fill_light_auto),
        "brightness2": brightness,
        "level": use_level,
        "lowLight": low if low is not None else _default(state.fill_light_low),
    }


def _default(value: bool | None) -> bool:
    """A missing switch field defaults to on, which is the camera's own default."""
    return True if value is None else value
