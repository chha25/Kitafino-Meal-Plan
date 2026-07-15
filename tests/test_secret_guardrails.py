"""Secret-leak guardrails for public Speiseplan surfaces."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from custom_components.speiseplan.const import FORBIDDEN_SECRET_MARKERS
from custom_components.speiseplan.models import Child, HealthStatus, MealEntry, MealPlanSnapshot
from custom_components.speiseplan.mqtt import build_snapshot_payload
from custom_components.speiseplan.storage import SnapshotStore


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PUBLIC_SCAN_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "_bmad-output",
}
INCLUDED_TEST_PUBLIC_PATHS = {
    Path("tests/test_coordinator.py"),
    Path("tests/test_config_flow.py"),
    Path("tests/test_diagnostics.py"),
    Path("tests/test_kitafino_client.py"),
    Path("tests/test_models.py"),
    Path("tests/test_mqtt.py"),
    Path("tests/test_operational_logging.py"),
    Path("tests/test_runtime_setup.py"),
    Path("tests/test_secret_guardrails.py"),
    Path("tests/test_services.py"),
    Path("custom_components/speiseplan/const.py"),
}
PUBLIC_SCAN_SUFFIXES = {
    ".json",
    ".md",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
    ".html",
}
SECRET_WORDS = (
    "parent@example.test",
    "super-secret",
    "REAL_KITAFINO_PASSWORD_VALUE",
    "REAL_SESSION_COOKIE_VALUE",
    "RAW_KITAFINO_HTML_CAPTURE",
    "REAL_ACCOUNT_ID_VALUE",
)


def test_public_repository_surfaces_contain_no_secret_markers() -> None:
    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _public_scan_paths()
    )

    for secret in SECRET_WORDS:
        assert secret not in public_text


def test_fixture_policy_documents_sanitization_guardrails() -> None:
    policy = (ROOT / "tests/fixtures/README.md").read_text()

    for expected in (
        "synthetic or sanitized",
        "Never commit",
        "real Kitafino credentials",
        "cookies or tokens",
        "raw household HTML captures",
        "account IDs",
        "request bodies",
        "response bodies",
        "Home Assistant secrets",
    ):
        assert expected in policy


def test_mqtt_payload_guardrail_redacts_known_secret_markers() -> None:
    health = HealthStatus(
        state="stale",
        last_error="network_error",
        fetched_at="RAW_KITAFINO_HTML_CAPTURE",
        last_successful_update="REAL_SESSION_COOKIE_VALUE",
    )
    object.__setattr__(health, "last_error", "REAL_ACCOUNT_ID_VALUE")
    snapshot = MealPlanSnapshot(
        health=health,
        children=[
            Child(
                child_key="REAL_ACCOUNT_ID_VALUE",
                display_name="Private Child",
            )
        ],
        entries=[
            MealEntry(
                child_key="REAL_ACCOUNT_ID_VALUE",
                week_kind="current",
                iso_year=2026,
                iso_week=29,
                weekday="monday",
                meal_text="RAW_KITAFINO_HTML_CAPTURE",
                source_date="REAL_ACCOUNT_ID_VALUE",
                fetched_at="REAL_SESSION_COOKIE_VALUE",
                stale=True,
                shared_source=True,
            )
        ],
        fetched_at="RAW_KITAFINO_HTML_CAPTURE",
        last_successful_update="REAL_SESSION_COOKIE_VALUE",
        shared_source=True,
        parser_version="RAW_KITAFINO_HTML_CAPTURE",
    )

    serialized = json.dumps(build_snapshot_payload(snapshot), sort_keys=True)

    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in serialized
    assert "Private Child" not in serialized


def test_persisted_snapshot_guardrail_excludes_child_metadata() -> None:
    store = SnapshotStore()
    snapshot = MealPlanSnapshot(
        health=HealthStatus(state="ok"),
        children=[
            Child(
                child_key="family_private_slug",
                display_name="Private Child",
            )
        ],
    )

    asyncio.run(store.async_save(snapshot))
    serialized = json.dumps(store.raw_data, sort_keys=True)

    assert "Private Child" not in serialized
    assert "family_private_slug" not in serialized


def _public_scan_paths() -> list[Path]:
    """Return text-like repository files that may become public."""
    paths: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if relative in INCLUDED_TEST_PUBLIC_PATHS:
            continue
        if any(part in EXCLUDED_PUBLIC_SCAN_DIRS for part in relative.parts):
            continue
        if path.suffix.lower() in PUBLIC_SCAN_SUFFIXES:
            paths.append(path)
    return paths
