"""Tests for the integration metadata."""

from __future__ import annotations

import json
from pathlib import Path
import struct

import pytest

ROOT = Path(__file__).parent.parent
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_size(path: Path) -> tuple[int, int]:
    """Return the width and height from the header of a PNG file."""
    header = path.read_bytes()[:24]
    assert header[:8] == PNG_SIGNATURE
    return struct.unpack(">II", header[16:24])


def test_manifest() -> None:
    """The manifest declares a config flow with no extra requirements."""
    manifest = json.loads((ROOT / "custom_components/siipet/manifest.json").read_text())
    assert manifest["domain"] == "siipet"
    assert manifest["config_flow"] is True
    assert manifest["requirements"] == []
    assert manifest["dependencies"] == ["http", "media_source", "websocket_api"]
    assert manifest["after_dependencies"] == ["frontend"]
    assert manifest["version"] == "0.6.1"


def test_hacs_minimum_version() -> None:
    """`hacs.json` requires Home Assistant 2026.11.0 or later."""
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["homeassistant"] == "2026.11.0"


@pytest.mark.parametrize(("name", "size"), [("icon.png", 256), ("icon@2x.png", 512)])
def test_brand_icon(name: str, size: int) -> None:
    """The integration ships square PNG brand icons in the standard sizes."""
    icon = ROOT / "custom_components/siipet/brand" / name
    assert _png_size(icon) == (size, size)
