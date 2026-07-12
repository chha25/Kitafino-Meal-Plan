"""Tests for diagnostics scaffold and redaction guardrails."""

from __future__ import annotations

from pathlib import Path
import asyncio
from types import SimpleNamespace

from custom_components.speiseplan.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    FORBIDDEN_SECRET_MARKERS,
    OPTION_CHILDREN,
    OPTION_SHARED_SOURCE,
)
from custom_components.speiseplan.diagnostics import async_get_config_entry_diagnostics


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


def test_readme_documents_child_specific_sensors_as_deferred() -> None:
    readme = (ROOT / "README.md").read_text()

    assert "Child labels are metadata" in readme
    assert "Child-specific meal sensors are deferred" in readme


def test_readme_documents_next_week_as_deferred() -> None:
    readme = (ROOT / "README.md").read_text()

    assert "Next Week support is deferred" in readme
    assert "Current Week sensors do not depend on Next Week data" in readme


def test_diagnostics_redact_config_entry_credentials() -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_USERNAME: "parent@example.test",
            CONF_PASSWORD: "super-secret",
        },
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(None, entry))

    assert diagnostics["username_configured"] is True
    assert diagnostics["password_configured"] is True
    assert "parent@example.test" not in str(diagnostics)
    assert "super-secret" not in str(diagnostics)


def test_diagnostics_remain_redacted_after_credential_update() -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_USERNAME: "updated@example.test",
            CONF_PASSWORD: "new-secret",
        },
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(None, entry))

    assert diagnostics["username_configured"] is True
    assert diagnostics["password_configured"] is True
    assert "updated@example.test" not in str(diagnostics)
    assert "new-secret" not in str(diagnostics)


def test_diagnostics_report_child_count_and_shared_source_without_labels() -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        data={
            CONF_USERNAME: "parent@example.test",
            CONF_PASSWORD: "super-secret",
        },
        options={
            OPTION_CHILDREN: [
                {"name": "Lena", "slug": "lena"},
                {"name": "Max", "slug": "max"},
            ],
            OPTION_SHARED_SOURCE: True,
        },
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(None, entry))
    serialized = str(diagnostics)

    assert diagnostics["configured_child_count"] == 2
    assert diagnostics["shared_source"] is True
    assert "Lena" not in serialized
    assert "Max" not in serialized
    assert "lena" not in serialized
    assert "max" not in serialized
    assert "parent@example.test" not in serialized
    assert "super-secret" not in serialized
