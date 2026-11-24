from __future__ import annotations

from conftest import load_fixture
from tyre_finder.data.site_config import build_scraper, default_sites
from tyre_finder.logic.grouping import group_offers
from tyre_finder.logic.normalize import (
    clean_model,
    keys_compatible,
    model_compact_key,
    model_token_key,
)
from tyre_finder.models import Season, TyreOffer, TyreSize

SIZE = TyreSize(205, 55, 16)


def offer(  # noqa: PLR0917
    shop: str,
    brand: str,
    model: str,
    price: float,
    li: str = "91",
    si: str = "V",
    ean: str | None = None,
    title: str = "",
) -> TyreOffer:
    return TyreOffer(
        shop=shop,
        brand=brand,
        model=model,
        size=SIZE,
        season=Season.SUMMER,
        price=price,
        currency="EUR",
        url=f"https://{shop}/{model}",
        load_index=li,
        speed_index=si,
        ean=ean,
        raw_title=title,
    )


def test_compact_key_ignores_spacing_and_case() -> None:
    assert model_compact_key("PremiumContact 7") == model_compact_key("PREMIUM CONTACT  7")


def test_token_key_ignores_word_order() -> None:
    assert model_token_key("Ventus Prime4 K135") == model_token_key("K135 Ventus Prime 4")


def test_clean_model_removes_noise() -> None:
    assert clean_model("SP702 94W XL FR ZR") == "SP702"
    assert clean_model("Snowproof 2 M+S 3PMSF DOT2025") == "SNOWPROOF 2"
    assert clean_model("GitiSynergy H2+", "Giti") == "SYNERGY H2 PLUS"
    assert clean_model("MZ01XL") == "MZ01"


def test_keys_compatible() -> None:
    assert keys_compatible("Z107", "ZUPERECOZ107")
    assert keys_compatible("PRIMACY5", "PRIMACY5ENERGY")
    assert not keys_compatible("GT", "GTOK41")  # too short / no digit
    assert not keys_compatible("ECOCONTACT6", "PREMIUMCONTACT7")


def test_same_tyre_across_shops_is_grouped() -> None:
    groups = group_offers(
        [
            offer("a", "Continental", "PremiumContact 7", 95.0),
            offer("b", "CONTINENTAL", "PREMIUM CONTACT 7", 94.25),
            offer("c", "Continental", "EcoContact 6", 80.0),
        ]
    )
    assert len(groups) == 2
    premium = next(g for g in groups if g.shop_count == 2)
    assert premium.best_offer.shop == "b"
    assert premium.best_price == 94.25
    assert round(premium.price_spread, 2) == 0.75


def test_different_load_index_or_runflat_not_grouped() -> None:
    groups = group_offers(
        [
            offer("a", "Bridgestone", "T005", 90.0, "91", "W"),
            offer("b", "Bridgestone", "T005 RFT", 120.0, "91", "W"),
            offer("c", "Bridgestone", "T005", 92.0, "94", "W"),
        ]
    )
    assert len(groups) == 3


def test_brand_alias_and_ean_grouping() -> None:
    groups = group_offers(
        [
            offer("a", "BF Goodrich", "Advantage", 70.0),
            offer("b", "BFGoodrich", "ADVANTAGE", 72.0),
            offer("c", "Michelin", "Primacy 4+", 100.0, ean="3528704476325"),
            offer("d", "Michelin", "Primacy4 Plus", 101.0, ean="3528704476325"),
        ]
    )
    assert sorted(g.shop_count for g in groups) == [2, 2]


def test_offer_without_index_joins_matching_group() -> None:
    groups = group_offers(
        [
            offer("a", "Hankook", "Ventus Prime 4", 80.0),
            offer("b", "Hankook", "Ventus Prime4", 79.0, li="", si=""),
        ]
    )
    assert len(groups) == 1


def test_real_fixtures_produce_multi_shop_groups(summer_query) -> None:
    fixtures = {
        "supergumi": "supergumi_205_55_16_summer.html",
        "bggumi": "bggumi_205_55_16_summer.html",
        "progumi": "progumi_205_55_16_summer.html",
        "gumi7": "gumi7_205_55_16_summer.html",
        "primex": "primex_205_55_16_summer.html",
        "gumi24": "gumi24_205_55_16_summer.html",
        "tirendo": "tirendo_205_55_16_summer.html",
        "diana": "diana_205_55_16_summer.html",
    }
    sites = {s.id: s for s in default_sites()}
    offers: list[TyreOffer] = []
    for sid, name in fixtures.items():
        scraper = build_scraper(sites[sid])
        offers += scraper.filter_matching(
            scraper.parse(load_fixture(name), summer_query), summer_query
        )
    groups = group_offers(offers)
    multi = [g for g in groups if g.shop_count > 1]
    assert len(multi) >= 25
    roadx = [g for g in groups if g.brand == "RoadX" and "H12" in g.model.upper()]
    assert len(roadx) == 1
    assert {"Примекс", "24Gumi", "ProGumi"} <= {o.shop for o in roadx[0].offers}
