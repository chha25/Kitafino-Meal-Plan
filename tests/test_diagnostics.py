"""Tests for diagnostics scaffold and redaction guardrails."""

from __future__ import annotations

from pathlib import Path

from custom_components.speiseplan.const import FORBIDDEN_SECRET_MARKERS


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PATHS = [
    ROOT / "README.md",
    ROOT / "hacs.json",
    ROOT / "custom_components/speiseplan/manifest.json",
    ROOT / "tests/fixtures/README.md",
    ROOT / "tests/fixtures/kitafino_current_week.html",
    ROOT / "tests/fixtures/kitafino_parse_error.html",
]


def test_public_scaffold_contains_no_forbidden_secret_markers() -> None:
    public_text = "\n".join(path.read_text() for path in PUBLIC_PATHS)

    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in public_text
