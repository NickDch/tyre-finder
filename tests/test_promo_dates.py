"""Date parsing and the 'only current codes' rules."""

from __future__ import annotations

from datetime import date

from bs4 import BeautifulSoup

from conftest import load_fixture
from tyre_finder.data.promo.dates import (
    DateKind,
    Freshness,
    find_dates,
    page_published_date,
    parse_date,
    parse_iso_datetime,
)

TODAY = date(2026, 11, 23)


def test_parse_bg_formats() -> None:
    assert parse_date("до 30.11.2026 г.") == date(2026, 11, 30)
    assert parse_date("30/11/26") == date(2026, 11, 30)
    assert parse_date("5 декември 2026") == date(2026, 12, 5)
    assert parse_date("01 ное 2026") == date(2026, 11, 1)
    assert parse_date("2026-04-19 18:18:23") == date(2026, 4, 19)
    assert parse_date("31.02.2026") is None
    assert parse_date("без дата") is None


def test_iso_datetime_with_zone() -> None:
    assert parse_iso_datetime("2026-12-02T21:59:00.000Z") == date(2026, 12, 2)
    assert parse_iso_datetime("2026-11-10T08:00:00+02:00") == date(2026, 11, 10)
    assert parse_iso_datetime("") is None


def test_period_and_until_classification() -> None:
    found = find_dates("Период на кампанията: 01.11.2026 г. – 30.11.2026 г.")
    assert [(f.value, f.kind) for f in found] == [
        (date(2026, 11, 1), DateKind.PERIOD_START),
        (date(2026, 11, 30), DateKind.UNTIL),
    ]
    found = find_dates("Кодът е валиден до 15.12.2026, публикувано 10.11.2026")
    kinds = {f.value: f.kind for f in found}
    assert kinds[date(2026, 12, 15)] is DateKind.UNTIL
    assert kinds[date(2026, 11, 10)] is DateKind.OTHER
    assert find_dates("Изтича: 2026-04-19")[0].kind is DateKind.UNTIL


def test_page_published_meta_and_jsonld() -> None:
    soup = BeautifulSoup(load_fixture("promo/synthetic_blog_page.html"), "lxml")
    assert page_published_date(soup) == date(2026, 11, 10)
    soup = BeautifulSoup(load_fixture("promo/synthetic_blog_old.html"), "lxml")
    assert page_published_date(soup) == date(2026, 3, 1)
    assert page_published_date(BeautifulSoup("<p>x</p>", "lxml")) is None


def test_freshness_rules() -> None:
    f = Freshness(window_days=30)
    assert f.is_current(TODAY, date(2026, 11, 30), None)
    assert f.is_current(TODAY, TODAY, None)  # last day still valid
    assert not f.is_current(TODAY, date(2026, 11, 22), None)
    assert not f.is_current(TODAY, date(2026, 12, 30), None, valid_from=date(2026, 12, 1))
    # no expiry: keep only when published in the last 30 days
    assert f.is_current(TODAY, None, date(2026, 11, 1))
    assert not f.is_current(TODAY, None, date(2026, 10, 1))
    assert not f.is_current(TODAY, None, None)
    assert Freshness(window_days=60).is_current(TODAY, None, date(2026, 10, 1))
