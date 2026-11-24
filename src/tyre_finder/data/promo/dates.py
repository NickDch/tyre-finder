"""Date extraction for promo pages (Bulgarian formats, meta tags, JSON-LD)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BG_MONTHS: dict[str, int] = {
    "януари": 1,
    "февруари": 2,
    "март": 3,
    "април": 4,
    "май": 5,
    "юни": 6,
    "юли": 7,
    "август": 8,
    "септември": 9,
    "октомври": 10,
    "ноември": 11,
    "декември": 12,
    "яну": 1,
    "фев": 2,
    "апр": 4,
    "авг": 8,
    "сеп": 9,
    "окт": 10,
    "ное": 11,
    "дек": 12,
}
_MONTH_ALT = "|".join(sorted(BG_MONTHS, key=len, reverse=True))

_NUMERIC = r"(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>\d{4}|\d{2})(?!\d)"
_WORDS = rf"(?P<wd>\d{{1,2}})\s+(?P<wm>{_MONTH_ALT})\.?\s+(?P<wy>\d{{4}})"
_ISO = r"(?P<iy>\d{4})-(?P<im>\d{2})-(?P<id>\d{2})"
_DATE = rf"(?:{_NUMERIC}|{_WORDS}|{_ISO})"
_DATE_RE = re.compile(_DATE, re.IGNORECASE)

_PERIOD_RE = re.compile(
    rf"(?:от\s+)?(?P<start>{_DATE.replace('?P<', '?P<s_')})\s*(?:г\.?)?\s*(?:[-–—]|до)\s*"
    rf"(?P<end>{_DATE.replace('?P<', '?P<e_')})",
    re.IGNORECASE,
)
_EXPIRES_LABEL_RE = re.compile(
    rf"(?:валид\w*\s+до|важи\s+до|изтича(?:\s+на)?:?|изтек\w*(?:\s+на)?|изтече(?:\s+на)?"
    rf"|срок\s+до|до)\s*:?\s*(?P<date>{_DATE})",
    re.IGNORECASE,
)


class DateKind(StrEnum):
    """Meaning of a date found in a text."""

    UNTIL = "until"
    PERIOD_START = "start"
    PUBLISHED = "published"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class FoundDate:
    """A date and what it means."""

    value: date
    kind: DateKind
    position: int = 0


def _make_date(year: int, month: int, day: int) -> date | None:
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _from_match(groups: dict[str, str | None], prefix: str = "") -> date | None:
    def g(name: str) -> str | None:
        return groups.get(prefix + name)

    if g("d"):
        return _make_date(int(g("y") or 0), int(g("m") or 0), int(g("d") or 0))
    if g("wd"):
        month = BG_MONTHS.get((g("wm") or "").lower())
        return _make_date(int(g("wy") or 0), month or 0, int(g("wd") or 0))
    if g("id"):
        return _make_date(int(g("iy") or 0), int(g("im") or 0), int(g("id") or 0))
    return None


def parse_date(text: str) -> date | None:
    """Parse the first date in *text* ('30.11.2026', '30 ноември 2026', '2026-11-30')."""
    m = _DATE_RE.search(text)
    return _from_match(m.groupdict()) if m else None


def parse_iso_datetime(value: str) -> date | None:
    """Parse an ISO 8601 date/datetime (with or without zone) to a date in its own zone."""
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return parse_date(value)


def find_dates(text: str) -> list[FoundDate]:
    """All dates in *text*, classified as 'until' / 'period start' / other."""
    found: list[FoundDate] = []
    taken: list[tuple[int, int]] = []
    for m in _PERIOD_RE.finditer(text):
        start = _from_match(m.groupdict(), "s_")
        end = _from_match(m.groupdict(), "e_")
        if start and end and start <= end:
            found.append(FoundDate(start, DateKind.PERIOD_START, m.start()))
            found.append(FoundDate(end, DateKind.UNTIL, m.start("end")))
            taken.append(m.span())
    for m in _EXPIRES_LABEL_RE.finditer(text):
        if any(a <= m.start("date") < b for a, b in taken):
            continue
        d = parse_date(m.group("date"))
        if d:
            found.append(FoundDate(d, DateKind.UNTIL, m.start("date")))
            taken.append(m.span())
    for m in _DATE_RE.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        d = _from_match(m.groupdict())
        if d:
            found.append(FoundDate(d, DateKind.OTHER, m.start()))
    return sorted(found, key=lambda f: f.position)


def page_published_date(soup: BeautifulSoup) -> date | None:
    """Publish date from meta tags, JSON-LD or ``<time datetime>``."""
    for attr, name in (
        ("property", "article:published_time"),
        ("property", "og:published_time"),
        ("name", "date"),
        ("itemprop", "datePublished"),
        ("property", "article:modified_time"),
    ):
        tag = soup.find("meta", attrs={attr: name})
        if tag and tag.get("content"):
            d = parse_iso_datetime(str(tag["content"]))
            if d:
                return d
    for script in soup.find_all("script", type="application/ld+json"):
        d = _jsonld_date(script.string or "")
        if d:
            return d
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag is not None:
        return parse_iso_datetime(str(time_tag["datetime"]))
    return None


def _jsonld_date(raw: str) -> date | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    stack: list[object] = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key in ("datePublished", "dateCreated", "uploadDate", "dateModified"):
                value = item.get(key)
                if isinstance(value, str):
                    d = parse_iso_datetime(value)
                    if d:
                        return d
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return None


@dataclass(frozen=True, slots=True)
class Freshness:
    """Rules for keeping only current codes."""

    window_days: int = 30

    def is_current(
        self,
        today: date,
        valid_until: date | None,
        published_at: date | None,
        valid_from: date | None = None,
    ) -> bool:
        """Keep a code if it has not expired; with no expiry, only if published recently."""
        if valid_until is not None:
            return valid_until >= today and (valid_from is None or valid_from <= today)
        if published_at is not None:
            return (
                today - timedelta(days=self.window_days)
                <= published_at
                <= today + timedelta(days=1)
            )
        return False
