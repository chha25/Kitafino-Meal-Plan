"""Tests for parser scaffold and fixture policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.speiseplan.const import FORBIDDEN_SECRET_MARKERS
from custom_components.speiseplan.kitafino.errors import KitafinoParseError
from custom_components.speiseplan.kitafino.parser import KitafinoParser


ROOT = Path(__file__).resolve().parents[1]
FETCHED_AT = "2026-07-12T06:00:00+02:00"


def test_parser_scaffold_imports() -> None:
    assert KitafinoParser.__name__ == "KitafinoParser"


def test_fixture_policy_exists() -> None:
    policy = (ROOT / "tests/fixtures/README.md").read_text()

    assert "Never commit" in policy
    assert "synthetic" in policy.lower()


def test_parser_extracts_current_week_meal_entries_from_fixture() -> None:
    source = (ROOT / "tests/fixtures/kitafino_current_week.html").read_text()

    entries = KitafinoParser().parse_current_week(
        source,
        fetched_at=FETCHED_AT,
        iso_year=2026,
        iso_week=29,
    )

    assert [entry.weekday for entry in entries] == ["monday", "tuesday"]
    assert all(entry.child_key == "shared" for entry in entries)
    assert all(entry.week_kind == "current" for entry in entries)
    assert all(entry.shared_source is True for entry in entries)
    assert all(entry.fetched_at == FETCHED_AT for entry in entries)
    assert all(entry.iso_year == 2026 for entry in entries)
    assert all(entry.iso_week == 29 for entry in entries)


def test_parser_normalizes_meal_text_and_source_date() -> None:
    source = (ROOT / "tests/fixtures/kitafino_current_week.html").read_text()

    entries = KitafinoParser().parse_current_week(
        source,
        fetched_at=FETCHED_AT,
        iso_year=2026,
        iso_week=29,
    )

    assert entries[0].meal_text == "Synthetic meal text"
    assert entries[0].source_date is None
    assert entries[1].meal_text == "Rice with vegetables"
    assert entries[1].source_date == "2026-07-14"


def test_parser_ignores_next_week_evidence_for_mvp() -> None:
    source = (ROOT / "tests/fixtures/kitafino_current_week.html").read_text()

    entries = KitafinoParser().parse_current_week(
        source,
        fetched_at=FETCHED_AT,
        iso_year=2026,
        iso_week=29,
    )

    assert all(entry.week_kind == "current" for entry in entries)
    assert "Future meal" not in json.dumps(
        [entry.to_dict() for entry in entries],
        sort_keys=True,
    )


def test_parser_raises_parse_error_for_missing_required_structure() -> None:
    source = (ROOT / "tests/fixtures/kitafino_parse_error.html").read_text()

    with pytest.raises(KitafinoParseError) as err:
        KitafinoParser().parse_current_week(
            source,
            fetched_at=FETCHED_AT,
            iso_year=2026,
            iso_week=29,
        )

    assert "<html" not in str(err.value).lower()


def test_parser_entries_are_secret_safe() -> None:
    source = (ROOT / "tests/fixtures/kitafino_current_week.html").read_text()

    entries = KitafinoParser().parse_current_week(
        source,
        fetched_at=FETCHED_AT,
        iso_year=2026,
        iso_week=29,
    )
    serialized = json.dumps([entry.to_dict() for entry in entries], sort_keys=True)

    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in serialized
    assert "username" not in serialized.lower()
    assert "password" not in serialized.lower()
    assert "cookie" not in serialized.lower()
    assert "raw_html" not in serialized.lower()
    assert "account_id" not in serialized.lower()


def test_parser_rejects_malformed_current_week_sections() -> None:
    source = """
    <html>
      <body>
        <section data-week="current">
          <div class="weekday">Monday</div>
          <div class="meal">Meal</div>
        </section>
        <section data-week="current">
          <div class="weekday">Tuesday</div>
        </section>
      </body>
    </html>
    """

    with pytest.raises(KitafinoParseError):
        KitafinoParser().parse_current_week(
            source,
            fetched_at=FETCHED_AT,
            iso_year=2026,
            iso_week=29,
        )


def test_parser_does_not_default_unrelated_sections_to_current_week() -> None:
    source = """
    <html>
      <body>
        <section>
          <div class="weekday">Monday</div>
          <div class="meal">Unrelated meal-shaped content</div>
        </section>
      </body>
    </html>
    """

    with pytest.raises(KitafinoParseError):
        KitafinoParser().parse_current_week(
            source,
            fetched_at=FETCHED_AT,
            iso_year=2026,
            iso_week=29,
        )


def test_parser_handles_nested_markup_and_price_spans() -> None:
    source = """
    <html>
      <body>
        <section data-week=" Current ">
          <div class="weekday"><span>Monday</span></div>
          <div class="meal">
            Pasta <span>with tomato</span>
            <span class="meal price"><strong>4,20 EUR</strong></span>
            sauce 3,50 €
          </div>
        </section>
      </body>
    </html>
    """

    entries = KitafinoParser().parse_current_week(
        source,
        fetched_at=FETCHED_AT,
        iso_year=2026,
        iso_week=29,
    )

    assert entries[0].meal_text == "Pasta with tomato sauce"
