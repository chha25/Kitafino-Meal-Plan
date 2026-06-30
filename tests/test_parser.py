"""Tests for parser scaffold and fixture policy."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_parser_scaffold_imports() -> None:
    from custom_components.speiseplan.kitafino.parser import KitafinoParser

    assert KitafinoParser.__name__ == "KitafinoParser"


def test_fixture_policy_exists() -> None:
    policy = (ROOT / "tests/fixtures/README.md").read_text()

    assert "Never commit" in policy
    assert "synthetic" in policy.lower()
