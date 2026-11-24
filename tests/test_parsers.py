"""Parser tests against real HTML saved from each shop (205/55 R16, summer, Nov 2026)."""

from __future__ import annotations

import pytest

from conftest import load_fixture
from tyre_finder.data.site_config import build_scraper, default_sites
from tyre_finder.data.sites.gumi7 import Gumi7Scraper
from tyre_finder.models import Season, TyreSize

# site id -> (fixture, minimum parsed offers, expected first brand, expected first model)
CASES: dict[str, tuple[str, int, str, str]] = {
    "emag": ("emag_205_55_16_summer.html", 40, "Goodride", "SW608"),
    "diana": ("diana_205_55_16_summer.html", 40, "Continental", "PREMIUM CONTACT 7"),
    "gumi7": ("gumi7_205_55_16_summer.html", 20, "Cooper", "COOPER SUMMER"),
    "primex": ("primex_205_55_16_summer.html", 15, "RoadX", "RXMOTION H12"),
    "progumi": ("progumi_205_55_16_summer.html", 20, "Landspider", "EUROTRAXX H/P"),
    "bggumi": ("bggumi_205_55_16_summer.html", 20, "Landspider", "EUROTRAXX H/P"),
    "supergumi": ("supergumi_205_55_16_summer.html", 20, "Landspider", "EUROTRAXX H/P"),
    "gumivarna": ("gumivarna_205_55_16_summer.html", 20, "Landspider", "EUROTRAXX H/P"),
    "tirendo": ("tirendo_205_55_16_summer.html", 20, "Star Performer", "Orbit"),
    "gumi24": ("gumi24_205_55_16_summer.html", 10, "Onyx", "NY-806"),
    "medinamed": ("medinamed_205_55_16_summer.html", 20, "Radar", "DMAX SPRINT"),
}
SITES = {s.id: s for s in default_sites()}


@pytest.mark.parametrize("site_id", sorted(CASES))
def test_parser_extracts_offers(site_id: str, summer_query) -> None:
    fixture, minimum, brand, model = CASES[site_id]
    scraper = build_scraper(SITES[site_id])
    offers = scraper.parse(load_fixture(fixture), summer_query)
    assert len(offers) >= minimum
    first = offers[0]
    assert first.brand == brand
    assert first.model == model
    # eMAG's text search is fuzzy (also returns other sizes); filter_matching handles it.
    checked = scraper.filter_matching(offers, summer_query) if site_id == "emag" else offers
    assert checked
    for offer in checked:
        assert offer.size == TyreSize(205, 55, 16)
        assert offer.price > 10
        assert offer.currency == "EUR"
        assert offer.url.startswith("https://")
        assert offer.brand
        assert offer.image_url is None or offer.image_url.startswith("https://")
    with_index = [o for o in offers if o.load_index and o.speed_index]
    assert len(with_index) >= len(offers) * 0.8


@pytest.mark.parametrize("site_id", sorted(CASES))
def test_filter_matching_keeps_requested_season(site_id: str, summer_query) -> None:
    fixture, *_ = CASES[site_id]
    scraper = build_scraper(SITES[site_id])
    kept = scraper.filter_matching(scraper.parse(load_fixture(fixture), summer_query), summer_query)
    assert kept
    assert all(o.season in (None, Season.SUMMER) for o in kept)


def test_emag_mixed_seasons_are_filtered(summer_query) -> None:
    scraper = build_scraper(SITES["emag"])
    offers = scraper.parse(load_fixture("emag_205_55_16_summer.html"), summer_query)
    seasons = {o.season for o in offers}
    assert Season.WINTER in seasons  # eMAG text search also returns winter tyres
    kept = scraper.filter_matching(offers, summer_query)
    assert {o.season for o in kept} <= {Season.SUMMER, None}


def test_supergumi_specific_values(summer_query) -> None:
    scraper = build_scraper(SITES["supergumi"])
    first = scraper.parse(load_fixture("supergumi_205_55_16_summer.html"), summer_query)[0]
    assert first.price == 38.50
    assert first.load_index == "91"
    assert first.speed_index == "V"
    assert first.url == "https://www.supergumi.bg/eshop/productinfo/1/3007013345192384"
    assert first.image_url == (
        "https://www.supergumi.bg/uploads/products/thumb_50818_eurotraxxh_p.jpg"
    )


def test_medina_and_gumi24_values(summer_query) -> None:
    medina = build_scraper(SITES["medinamed"]).parse(
        load_fixture("medinamed_205_55_16_summer.html"), summer_query
    )[0]
    assert (medina.price, medina.load_index, medina.speed_index) == (49.70, "94", "W")
    g24 = build_scraper(SITES["gumi24"]).parse(
        load_fixture("gumi24_205_55_16_summer.html"), summer_query
    )[0]
    assert (g24.price, g24.load_index, g24.speed_index) == (40.38, "91", "V")


def test_build_urls(summer_query) -> None:
    urls = {sid: build_scraper(site).build_url(summer_query, 1) for sid, site in SITES.items()}
    assert urls["supergumi"] == (
        "https://www.supergumi.bg/eshop/search?type=1&width=205&height=55&inch=16&season=2"
    )
    assert urls["bggumi"] == (
        "https://www.bggumi.com/eshop/search?type=1&width=205&height=55&inch=16&season=2&sortby=1"
    )
    assert "season[summer]=1" in urls["primex"]
    assert "tire-season=summer" in urls["progumi"]
    assert "season=so" in urls["tirendo"]
    assert urls["medinamed"].startswith("https://medina-med.com/katalog-gumi/?season_id=summer")
    assert build_scraper(SITES["primex"]).build_url(summer_query, 2) is None


def test_gumi7_badges_kept(summer_query) -> None:
    offers = Gumi7Scraper().parse(load_fixture("gumi7_205_55_16_summer.html"), summer_query)
    assert any("- 5% с финансиране IUTE" in o.badges for o in offers)
    synthetic = load_fixture("promo/synthetic_gumi7_code_badge.html")
    coded = [
        o for o in Gumi7Scraper().parse(synthetic, summer_query) if "-3% с код: SUM26" in o.badges
    ]
    assert len(coded) == 1
