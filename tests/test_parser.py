"""Tests for parser scaffold and fixture policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.speiseplan.const import FORBIDDEN_SECRET_MARKERS
from custom_components.speiseplan.kitafino.errors import KitafinoParseError
from custom_components.speiseplan.kitafino.parser import KitafinoParser
from custom_components.speiseplan.kitafino.parser import PARSER_VERSION


ROOT = Path(__file__).resolve().parents[1]
FETCHED_AT = "2026-07-12T06:00:00+02:00"


def _parse(source: str):
    return KitafinoParser().parse_current_week(
        source,
        fetched_at=FETCHED_AT,
        iso_year=2026,
        iso_week=29,
    )


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


def test_parser_extracts_only_selected_production_meals() -> None:
    source = (ROOT / "tests/fixtures/kitafino_production_current_week.html").read_text()

    entries = _parse(source)

    assert [entry.weekday for entry in entries] == ["monday", "tuesday"]
    assert [entry.meal_text for entry in entries] == [
        "Invented selected noodles",
        "Invented selected soup with herbs",
    ]
    assert all(entry.source_date is None for entry in entries)
    assert all(entry.child_key == "shared" for entry in entries)
    assert all(entry.week_kind == "current" for entry in entries)
    assert all(entry.iso_year == 2026 for entry in entries)
    assert all(entry.iso_week == 29 for entry in entries)
    assert all(entry.fetched_at == FETCHED_AT for entry in entries)
    assert all(entry.stale is False for entry in entries)
    assert all(entry.shared_source is True for entry in entries)


def test_production_parser_suppresses_presentation_and_action_noise() -> None:
    source = (ROOT / "tests/fixtures/kitafino_production_current_week.html").read_text()

    serialized = json.dumps([entry.to_dict() for entry in _parse(source)])

    for noise in ("Menu", "EUR", "deadline", "status", "Ordered", "Choose"):
        assert noise not in serialized
    assert "unselected" not in serialized


def test_production_selected_marker_may_follow_description() -> None:
    source = """
    <div class="wochen_wrapper"><div class="order_woche_wrapper">
      <div class="order_table">
        <div class="order_info_wrapper"><strong class="left">Freitag 24.07.</strong></div>
        <div class="order_button_wrapper">
          Buffered invented meal <form><button class="order_button_bestellt"><span class="order_button_action">Selected</span></button></form>
        </div>
      </div>
    </div></div>
    """

    entries = _parse(source)

    assert [(entry.weekday, entry.meal_text) for entry in entries] == [
        ("friday", "Buffered invented meal")
    ]


@pytest.mark.parametrize(
    ("heading", "weekday"),
    [
        ("Montag, synthetic date", "monday"),
        ("Tuesday synthetic date", "tuesday"),
        ("Mittwoch – synthetic date", "wednesday"),
        ("Thursday: synthetic date", "thursday"),
        ("Freitag synthetic date", "friday"),
    ],
)
def test_production_parser_recognizes_leading_weekday_variants(
    heading: str, weekday: str
) -> None:
    source = f"""
    <div class="wochen_wrapper"><div class="order_woche_wrapper">
      <div class="order_table">
        <div class="order_info_wrapper"><strong class="left">{heading}</strong></div>
        <div class="order_button_wrapper">Invented meal<button class="order_button_bestellt">Selected</button></div>
      </div>
    </div></div>
    """

    assert _parse(source)[0].weekday == weekday


def test_production_parser_ignores_unselected_and_unknown_days() -> None:
    source = (ROOT / "tests/fixtures/kitafino_production_current_week.html").read_text()

    assert [entry.weekday for entry in _parse(source)] == ["monday", "tuesday"]


@pytest.mark.parametrize(
    "day_body",
    [
        """
        <div class="order_button_wrapper">First<button class="order_button_bestellt">Selected</button></div>
        <div class="order_button_wrapper">Second<button class="order_button_bestellt">Selected</button></div>
        """,
        """<div class="order_button_wrapper"><span class="price">4,00 EUR</span><button class="order_button_bestellt"><span class="order_button_action">Selected</span></button></div>""",
    ],
)
def test_production_parser_rejects_ambiguous_or_empty_selected_meal(
    day_body: str,
) -> None:
    source = f"""
    <div class="wochen_wrapper"><div class="order_woche_wrapper">
      <div class="order_table">
        <div class="order_info_wrapper"><strong class="left">Monday</strong></div>
        {day_body}
      </div>
    </div></div>
    """

    with pytest.raises(KitafinoParseError) as err:
        _parse(source)
    assert "First" not in str(err.value)
    assert "4,00" not in str(err.value)


def test_production_parser_rejects_duplicate_weekday() -> None:
    day = """
      <div class="order_table">
        <div class="order_info_wrapper"><strong class="left">Monday</strong></div>
        <div class="order_button_wrapper">Invented meal<button class="order_button_bestellt">Selected</button></div>
      </div>
    """
    source = f'<div class="wochen_wrapper"><div class="order_woche_wrapper">{day}{day}</div></div>'

    with pytest.raises(KitafinoParseError):
        _parse(source)


def test_production_boundary_takes_precedence_over_legacy_fallback() -> None:
    source = """
    <div class="wochen_wrapper"><div class="order_woche_wrapper">
      <div class="order_table">
        <div class="order_info_wrapper"><strong class="left">Monday</strong></div>
        <div class="order_button_wrapper">Not selected</div>
      </div>
    </div></div>
    <section data-week="current"><div class="weekday">Tuesday</div><div class="meal">Legacy meal</div></section>
    """

    with pytest.raises(KitafinoParseError):
        _parse(source)


def test_production_day_outside_week_scope_is_not_parsed() -> None:
    source = """
    <div class="order_table">
      <div class="order_info_wrapper"><strong class="left">Monday</strong></div>
      <div class="order_button_wrapper">Invented meal<button class="order_button_bestellt">Selected</button></div>
    </div>
    """

    with pytest.raises(KitafinoParseError):
        _parse(source)


def test_production_parser_rejects_unclosed_day_structure() -> None:
    source = """
    <div class="wochen_wrapper"><div class="order_woche_wrapper">
      <div class="order_table">
        <div class="order_info_wrapper"><strong class="left">Monday</strong></div>
        <div class="order_button_wrapper">
          Invented meal
          <button class="order_button_bestellt">
            <span class="order_button_action">Selected</span>
    """

    with pytest.raises(KitafinoParseError):
        _parse(source)


def test_production_parser_requires_selected_marker_on_button() -> None:
    source = """
    <div class="wochen_wrapper"><div class="order_woche_wrapper">
      <div class="order_table">
        <div class="order_info_wrapper"><strong class="left">Monday</strong></div>
        <div class="order_button_wrapper">
          Invented meal <span class="order_button_bestellt">Not a button</span>
        </div>
      </div>
    </div></div>
    """

    with pytest.raises(KitafinoParseError):
        _parse(source)


def test_production_parser_rejects_multiple_weekday_headers() -> None:
    source = """
    <div class="wochen_wrapper"><div class="order_woche_wrapper">
      <div class="order_table">
        <div class="order_info_wrapper"><strong class="left">Monday</strong></div>
        <div class="order_info_wrapper"><strong class="left">Tuesday</strong></div>
        <div class="order_button_wrapper">
          Invented meal <button class="order_button_bestellt"></button>
        </div>
      </div>
    </div></div>
    """

    with pytest.raises(KitafinoParseError):
        _parse(source)


def test_production_parser_preserves_non_noise_class_substrings() -> None:
    source = """
    <div class="wochen_wrapper"><div class="order_woche_wrapper">
      <div class="order_table">
        <div class="order_info_wrapper"><strong class="left">Monday</strong></div>
        <div class="order_button_wrapper">
          <button class="order_button_bestellt">
            <span class="actionable-description">Invented icon-shaped pasta</span>
          </button>
        </div>
      </div>
    </div></div>
    """

    assert _parse(source)[0].meal_text == "Invented icon-shaped pasta"


def test_parser_reports_v2_strategy() -> None:
    assert PARSER_VERSION == "kitafino-html-v2"
    assert KitafinoParser.parser_version == PARSER_VERSION


def test_production_fixture_and_results_are_secret_safe() -> None:
    source = (ROOT / "tests/fixtures/kitafino_production_current_week.html").read_text()
    serialized = json.dumps([entry.to_dict() for entry in _parse(source)])

    for marker in FORBIDDEN_SECRET_MARKERS:
        assert marker not in source
        assert marker not in serialized
    for marker in ("password", "cookie", "account_id", "raw_html"):
        assert marker not in source.lower()
        assert marker not in serialized.lower()
    for form_value_marker in (" value=", " name=", " action="):
        assert form_value_marker not in source.lower()
