"""Tests for Speiseplan config-flow metadata."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_declares_config_flow() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/speiseplan/manifest.json").read_text()
    )

    assert manifest["domain"] == "speiseplan"
    assert manifest["config_flow"] is True
    assert "homeassistant" not in manifest


def test_hacs_declares_minimum_home_assistant_version() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())

    assert hacs["homeassistant"] == "2026.6.4"
