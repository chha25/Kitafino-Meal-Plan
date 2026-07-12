"""Kitafino source parser for Speiseplan."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re

from ..models import MealEntry
from .errors import KitafinoParseError

PARSER_VERSION = "kitafino-html-v1"
PRICE_PATTERN = re.compile(r"\b\d+[,.]\d{2}\s*(?:eur\b|€)", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")
WEEKDAY_ALIASES = {
    "monday": "monday",
    "montag": "monday",
    "tuesday": "tuesday",
    "dienstag": "tuesday",
    "wednesday": "wednesday",
    "mittwoch": "wednesday",
    "thursday": "thursday",
    "donnerstag": "thursday",
    "friday": "friday",
    "freitag": "friday",
}


@dataclass
class _ParsedSection:
    """Internal parsed meal section."""

    week_kind: str
    source_date: str | None
    weekday_parts: list[str]
    meal_parts: list[str]

    @property
    def weekday_text(self) -> str:
        """Return joined weekday text."""
        return _normalize_text(" ".join(self.weekday_parts))

    @property
    def meal_text(self) -> str:
        """Return joined meal text."""
        return _normalize_meal_text(" ".join(self.meal_parts))


@dataclass(frozen=True)
class _CaptureFrame:
    """Capture state for one opened HTML element."""

    tag: str
    target: str | None
    suppress: bool


class _KitafinoFixtureHtmlParser(HTMLParser):
    """Parse sanitized Kitafino-like fixture sections."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[_ParsedSection] = []
        self._current_section: _ParsedSection | None = None
        self._capture_stack: list[_CaptureFrame] = []
        self.structure_error = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Track supported fixture tags."""
        attrs_dict = _attrs_to_dict(attrs)
        if tag == "section":
            if self._current_section is not None:
                self.structure_error = True
                return

            week_kind = _normalize_text(attrs_dict.get("data-week", "")).lower()
            if week_kind not in {"current", "next"}:
                return

            self._current_section = _ParsedSection(
                week_kind=week_kind,
                source_date=attrs_dict.get("data-source-date"),
                weekday_parts=[],
                meal_parts=[],
            )
            return

        if self._current_section is None:
            return

        parent = self._capture_stack[-1] if self._capture_stack else None
        class_names = set(attrs_dict.get("class", "").split())
        target = parent.target if parent is not None else None
        suppress = parent.suppress if parent is not None else False

        if "price" in class_names:
            suppress = True
        elif "weekday" in class_names:
            target = "weekday"
        elif "meal" in class_names:
            target = "meal"

        if target is not None or suppress:
            self._capture_stack.append(
                _CaptureFrame(tag=tag, target=target, suppress=suppress)
            )

    def handle_endtag(self, tag: str) -> None:
        """Close supported fixture tags."""
        if tag == "section" and self._current_section is not None:
            self.sections.append(self._current_section)
            self._current_section = None
            self._capture_stack.clear()
            return

        if self._capture_stack and self._capture_stack[-1].tag == tag:
            self._capture_stack.pop()

    def handle_data(self, data: str) -> None:
        """Collect text for weekday and meal fields."""
        if self._current_section is None or not self._capture_stack:
            return

        frame = self._capture_stack[-1]
        if frame.suppress:
            return

        if frame.target == "weekday":
            self._current_section.weekday_parts.append(data)
        elif frame.target == "meal":
            self._current_section.meal_parts.append(data)


class KitafinoParser:
    """Parser for sanitized Kitafino source HTML."""

    parser_version = PARSER_VERSION

    def parse_current_week(
        self,
        source_html: str,
        *,
        fetched_at: str,
        iso_year: int,
        iso_week: int,
        child_key: str = "shared",
        shared_source: bool = True,
    ) -> list[MealEntry]:
        """Parse current-week meal entries from sanitized Kitafino source HTML."""
        parser = _KitafinoFixtureHtmlParser()
        try:
            parser.feed(source_html)
            parser.close()
        except Exception as err:
            raise KitafinoParseError() from err

        if parser.structure_error:
            raise KitafinoParseError()

        entries: list[MealEntry] = []
        for section in parser.sections:
            if section.week_kind != "current":
                continue

            weekday = _weekday_key(section.weekday_text)
            if weekday is None or not section.meal_text:
                raise KitafinoParseError()

            entries.append(
                MealEntry(
                    child_key=child_key,
                    week_kind="current",
                    iso_year=iso_year,
                    iso_week=iso_week,
                    weekday=weekday,
                    meal_text=section.meal_text,
                    source_date=section.source_date,
                    fetched_at=fetched_at,
                    stale=False,
                    shared_source=shared_source,
                )
            )

        if not entries:
            raise KitafinoParseError()

        return entries


def _attrs_to_dict(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    """Convert HTMLParser attrs to a dictionary."""
    return {key: value for key, value in attrs if value is not None}


def _weekday_key(value: str) -> str | None:
    """Map localized weekday text to the model weekday key."""
    return WEEKDAY_ALIASES.get(value.strip().lower())


def _normalize_text(value: str) -> str:
    """Collapse presentation whitespace."""
    return WHITESPACE_PATTERN.sub(" ", value).strip()


def _normalize_meal_text(value: str) -> str:
    """Normalize meal text and remove simple presentation-only price noise."""
    without_prices = PRICE_PATTERN.sub("", value)
    return _normalize_text(without_prices)
