from __future__ import annotations

import pytest

from tyre_finder.data.brands import normalize_brand, split_brand_model
from tyre_finder.data.parsing import parse_price, parse_size_spec, season_from_text
from tyre_finder.models import Season, TyreSize


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("38.50 €", 38.50),
        ("94,25 €", 94.25),
        ("€40.38", 40.38),
        ("1 234,56 лв.", 1234.56),
        ("44", 44.0),
        ("само 42, 99 €", 42.0),
    ],
)
def test_parse_price(text: str, expected: float) -> None:
    assert parse_price(text) == expected


def test_parse_price_none() -> None:
    assert parse_price("няма цена") is None


@pytest.mark.parametrize(
    ("text", "li", "si"),
    [
        ("205/55 R16 91V", "91", "V"),
        ("205 / 55 R16 91V", "91", "V"),
        ("205/55R16 91 W", "91", "W"),
        ("RADAR 205/55R16 94W XL DMAX SPRINT", "94", "W"),
        ("LEAO 205/55R16 NOVA-FORCE HP100 91V LA", "91", "V"),
        ("205/55 ZR16 94W XL", "94", "W"),
        ("205/55 R16", None, None),
    ],
)
def test_parse_size_spec(text: str, li: str | None, si: str | None) -> None:
    spec = parse_size_spec(text)
    assert spec is not None
    assert spec.size == TyreSize(205, 55, 16)
    assert (spec.load_index, spec.speed_index) == (li, si)


def test_season_from_text() -> None:
    assert season_from_text("Летни гуми") is Season.SUMMER
    assert season_from_text("Лятна гума") is Season.SUMMER
    assert season_from_text("Зимна гума") is Season.WINTER
    assert season_from_text("Целогодишни гуми") is Season.ALL_SEASON
    assert season_from_text("Всесезонна") is Season.ALL_SEASON
    assert season_from_text("гума") is None


def test_split_brand_model_multiword() -> None:
    assert split_brand_model("BF GOODRICH ADVANTAGE 2") == ("BFGoodrich", "ADVANTAGE 2")
    assert split_brand_model("Star Performer Orbit") == ("Star Performer", "Orbit")
    assert split_brand_model("UNKNOWNBRAND X1") == ("UNKNOWNBRAND", "X1")


def test_normalize_brand_aliases() -> None:
    assert normalize_brand("BF Goodrich") == normalize_brand("BFGoodrich")
    assert normalize_brand("Good Year") == normalize_brand("GOODYEAR")
    assert normalize_brand("Nokian Tyres") == normalize_brand("Nokian")
