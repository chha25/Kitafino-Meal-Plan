"""Kitafino source parser for Speiseplan."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re

from ..models import MealEntry
from .errors import KitafinoParseError

PARSER_VERSION = "kitafino-html-v2"
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


@dataclass
class _ProductionChoice:
    """Buffered text and selection state for one production meal choice."""

    text_parts: list[str]
    selected: bool = False


@dataclass
class _ProductionDay:
    """Buffered fields for one production day block."""

    weekday_parts: list[str]
    selected_meals: list[str]
    weekday_headers: int = 0


@dataclass(frozen=True)
class _ProductionFrame:
    """Open production element and its inherited parsing state."""

    tag: str
    classes: frozenset[str]
    suppress: bool
    weekday_capture: bool


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


_SUPPRESSED_PRODUCTION_TAGS = {"input", "script", "style"}
_VOID_HTML_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_SUPPRESSED_PRODUCTION_CLASSES = {
    "deadline_note",
    "fristen_info",
    "frist_info_trenner",
    "has-tip",
    "icon",
    "info_balken",
    "info_order_button",
    "kauf_info_no",
    "menu_nr",
    "order_button_action",
    "order_status",
    "preis",
    "preis_button",
    "preis_info_zu_men",
    "price",
}


class _KitafinoProductionHtmlParser(HTMLParser):
    """Parse the generic, privacy-safe structure of the production meal page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.days: list[_ProductionDay] = []
        self.production_boundary_seen = False
        self.structure_error = False
        self._stack: list[_ProductionFrame] = []
        self._current_day: _ProductionDay | None = None
        self._current_choice: _ProductionChoice | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Open a production element and update day/choice capture state."""
        classes = frozenset(_attrs_to_dict(attrs).get("class", "").split())
        parent = self._stack[-1] if self._stack else None
        inside_week = self._inside_class("wochen_wrapper") and self._inside_class(
            "order_woche_wrapper"
        )

        if "order_table" in classes and inside_week:
            self.production_boundary_seen = True
            if self._current_day is not None:
                self.structure_error = True
            else:
                self._current_day = _ProductionDay([], [])

        if (
            self._current_day is not None
            and "order_button_wrapper" in classes
            and parent is not None
            and "order_table" in parent.classes
        ):
            if self._current_choice is not None:
                self.structure_error = True
            else:
                self._current_choice = _ProductionChoice([])

        if (
            self._current_choice is not None
            and tag == "button"
            and "order_button_bestellt" in classes
        ):
            self._current_choice.selected = True

        inherited_suppression = parent.suppress if parent is not None else False
        suppress = inherited_suppression or _production_element_is_suppressed(
            tag, classes
        )
        weekday_capture = False
        if (
            self._current_day is not None
            and tag == "strong"
            and "left" in classes
            and parent is not None
            and "order_info_wrapper" in parent.classes
        ):
            weekday_capture = True
            self._current_day.weekday_headers += 1
            if self._current_day.weekday_headers > 1:
                self.structure_error = True
        elif parent is not None:
            weekday_capture = parent.weekday_capture

        self._stack.append(
            _ProductionFrame(tag, classes, suppress, weekday_capture)
        )
        if tag in _VOID_HTML_TAGS:
            self._stack.pop()

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Process a self-closing production element."""
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_HTML_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        """Finalize production choices and day blocks at their boundaries."""
        matching_index = next(
            (
                index
                for index in range(len(self._stack) - 1, -1, -1)
                if self._stack[index].tag == tag
            ),
            None,
        )
        if matching_index is None:
            return
        skipped_frames = self._stack[matching_index + 1 :]
        if any(
            "order_button_wrapper" in skipped.classes
            or "order_table" in skipped.classes
            for skipped in skipped_frames
        ):
            self.structure_error = True
        del self._stack[matching_index + 1 :]

        frame = self._stack[-1]
        if "order_button_wrapper" in frame.classes:
            self._finalize_choice()
        if "order_table" in frame.classes:
            self._finalize_day()
        self._stack.pop()

    def handle_data(self, data: str) -> None:
        """Buffer only weekday and candidate meal text."""
        if self._current_day is None or not self._stack:
            return
        frame = self._stack[-1]
        if frame.weekday_capture:
            self._current_day.weekday_parts.append(data)
        elif not frame.suppress and self._current_choice is not None:
            self._current_choice.text_parts.append(data)

    def close(self) -> None:
        """Reject incomplete production boundaries after parsing."""
        super().close()
        if self._current_choice is not None or self._current_day is not None:
            self.structure_error = True

    def _inside_class(self, class_name: str) -> bool:
        return any(class_name in frame.classes for frame in self._stack)

    def _finalize_choice(self) -> None:
        choice = self._current_choice
        if choice is None:
            self.structure_error = True
            return
        if choice.selected:
            meal_text = _normalize_meal_text(" ".join(choice.text_parts))
            if not meal_text or self._current_day is None:
                self.structure_error = True
            else:
                self._current_day.selected_meals.append(meal_text)
        self._current_choice = None

    def _finalize_day(self) -> None:
        day = self._current_day
        if day is None or self._current_choice is not None:
            self.structure_error = True
            return
        if len(day.selected_meals) > 1:
            self.structure_error = True
        self.days.append(day)
        self._current_day = None


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
        production_parser = _KitafinoProductionHtmlParser()
        try:
            production_parser.feed(source_html)
            production_parser.close()
        except Exception as err:
            raise KitafinoParseError() from err

        if production_parser.production_boundary_seen:
            if production_parser.structure_error:
                raise KitafinoParseError()
            return _production_entries(
                production_parser.days,
                fetched_at=fetched_at,
                iso_year=iso_year,
                iso_week=iso_week,
                child_key=child_key,
                shared_source=shared_source,
            )

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
    match = re.match(r"^\W*([^\W\d_]+)", value, re.UNICODE)
    if match is None:
        return None
    return WEEKDAY_ALIASES.get(match.group(1).lower())


def _normalize_text(value: str) -> str:
    """Collapse presentation whitespace."""
    return WHITESPACE_PATTERN.sub(" ", value).strip()


def _normalize_meal_text(value: str) -> str:
    """Normalize meal text and remove simple presentation-only price noise."""
    without_prices = PRICE_PATTERN.sub("", value)
    return _normalize_text(without_prices)


def _production_element_is_suppressed(
    tag: str, classes: frozenset[str]
) -> bool:
    """Return whether a production subtree contains presentation/action noise."""
    if tag in _SUPPRESSED_PRODUCTION_TAGS:
        return True
    lowered_classes = {class_name.lower() for class_name in classes}
    return bool(lowered_classes & _SUPPRESSED_PRODUCTION_CLASSES) or any(
        class_name.startswith("fi-") for class_name in lowered_classes
    )


def _production_entries(
    days: list[_ProductionDay],
    *,
    fetched_at: str,
    iso_year: int,
    iso_week: int,
    child_key: str,
    shared_source: bool,
) -> list[MealEntry]:
    """Build strict shared-current-week entries from production day buffers."""
    entries: list[MealEntry] = []
    seen_weekdays: set[str] = set()
    for day in days:
        weekday = _weekday_key(_normalize_text(" ".join(day.weekday_parts)))
        if weekday is None or not day.selected_meals:
            continue
        if len(day.selected_meals) != 1 or weekday in seen_weekdays:
            raise KitafinoParseError()
        seen_weekdays.add(weekday)
        entries.append(
            MealEntry(
                child_key=child_key,
                week_kind="current",
                iso_year=iso_year,
                iso_week=iso_week,
                weekday=weekday,
                meal_text=day.selected_meals[0],
                source_date=None,
                fetched_at=fetched_at,
                stale=False,
                shared_source=shared_source,
            )
        )
    if not entries:
        raise KitafinoParseError()
    return entries
