"""Small helpers shared by the HTML parsers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from tyre_finder.models import Season, TyreSize


class ParseError(Exception):
    """Raised when a page does not look like the expected result list."""


_PRICE_RE = re.compile(r"(\d{1,3}(?:[ \u00a0.]\d{3})*|\d+)(?:[.,](\d{1,2}))?")


def parse_price(text: str) -> float | None:
    """Parse prices like '38.50 €', '94,25 €', '€40.38', '1 234,56 лв.'."""
    cleaned = text.replace("\u00a0", " ").strip()
    match = _PRICE_RE.search(cleaned)
    if not match:
        return None
    whole = re.sub(r"[ .\u00a0]", "", match.group(1))
    decimals = match.group(2) or "0"
    try:
        return float(f"{whole}.{decimals}")
    except ValueError:
        return None


def detect_currency(text: str, default: str = "EUR") -> str:
    """Return 'EUR' or 'BGN' depending on the symbols found in *text*."""
    lowered = text.lower()
    if "€" in text or "eur" in lowered:
        return "EUR"
    if "лв" in lowered or "bgn" in lowered:
        return "BGN"
    return default


_SIZE_RE = re.compile(
    r"(?P<w>\d{3})\s*/\s*(?P<p>\d{2})\s*(?:Z?R|R|-)\s*F?\s*(?P<r>\d{2})(?:C\b)?"
    r"(?:\s*(?P<li>\d{2,3})(?:/\d{2,3})?\s*(?P<si>[A-HJ-NP-Z])\b)?",
    re.IGNORECASE,
)
_LISI_RE = re.compile(r"\b(?P<li>\d{2,3})(?:/\d{2,3})?\s?(?P<si>[A-HJ-NP-Z])\b")


@dataclass(frozen=True, slots=True)
class SizeSpec:
    """Size plus optional load and speed index parsed from text."""

    size: TyreSize
    load_index: str | None
    speed_index: str | None


def parse_size_spec(text: str) -> SizeSpec | None:
    """Parse '205/55 R16 91V', '205 / 55 R16 91V', '205/55R16 91 W' etc."""
    match = _SIZE_RE.search(text)
    if not match:
        return None
    size = TyreSize(int(match["w"]), int(match["p"]), int(match["r"]))
    li, si = match["li"], match["si"]
    if li is None:
        tail = _LISI_RE.search(text[match.end() :])
        if tail:
            li, si = tail["li"], tail["si"]
    return SizeSpec(size, li, si.upper() if si else None)


def parse_load_speed(text: str) -> tuple[str | None, str | None]:
    """Find a load/speed index such as '91V' or '94 W' in *text*."""
    match = _LISI_RE.search(text)
    if not match:
        return None, None
    return match["li"], match["si"].upper()


_SEASON_WORDS: tuple[tuple[str, Season], ...] = (
    ("всесезон", Season.ALL_SEASON),
    ("целогодиш", Season.ALL_SEASON),
    ("all-season", Season.ALL_SEASON),
    ("allseason", Season.ALL_SEASON),
    ("all season", Season.ALL_SEASON),
    ("all_season", Season.ALL_SEASON),
    ("4 сезона", Season.ALL_SEASON),
    ("летн", Season.SUMMER),
    ("лятн", Season.SUMMER),
    ("summer", Season.SUMMER),
    ("зимн", Season.WINTER),
    ("winter", Season.WINTER),
)


def season_from_text(text: str) -> Season | None:
    """Detect the season from Bulgarian or English text."""
    lowered = text.lower()
    for word, season in _SEASON_WORDS:
        if word in lowered:
            return season
    return None


def clean_text(text: str | None) -> str:
    """Collapse whitespace."""
    return " ".join((text or "").split())
