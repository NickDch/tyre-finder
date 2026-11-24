"""Shop-site and aggregator promo sources against saved real pages."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from conftest import FakeHttp, load_fixture
from tyre_finder.data.promo.aggregators import (
    CuponeriaSource,
    DiscountsBgSource,
    KuponovoSource,
    shop_slug,
)
from tyre_finder.data.promo.base import LookupContext, ShopRef
from tyre_finder.data.promo.dates import Freshness
from tyre_finder.data.promo.service import filter_current
from tyre_finder.data.promo.shop_pages import MEDINA_PROMO_LIST, MedinaPromoSource, ShopPageSource
from tyre_finder.models import Confidence, PromoOrigin

NOW = datetime(2026, 11, 23, 12, 0)
MEDINA = ShopRef("medinamed", "Медина-Мед", "https://medina-med.com/")
TIRENDO = ShopRef("tirendo", "Tirendo", "https://www.tirendo.bg/")
EMAG = ShopRef("emag", "eMAG", "https://www.emag.bg/")
GUMI7 = ShopRef("gumi7", "Gumi7", "https://gumi7.com/bg/")
GUMI24 = ShopRef("gumi24", "24Gumi", "https://24gumi.bg/")


@pytest.fixture
def ctx() -> LookupContext:
    return LookupContext(http=None, today=NOW.date(), now=NOW)  # type: ignore[arg-type]


def test_shop_ref_names() -> None:
    assert GUMI7.domain == "gumi7.com"
    assert "gumi7" in GUMI7.names
    assert EMAG.general_store
    assert shop_slug(EMAG) == "emag"
    assert shop_slug(GUMI24) == "24gumi"


def test_medina_listing_links() -> None:
    links = MedinaPromoSource.parse_listing(load_fixture("promo/medina_promotsii.html"))
    assert "https://medina-med.com/promotsii/vzemi-6-otstapka-za-gumi-s-lidl-plus-2984/" in links
    assert all(link.startswith("https://medina-med.com/promotsii/") for link in links)


def test_medina_lidl_plus_6_percent(ctx) -> None:
    promo = MedinaPromoSource.parse_detail(
        load_fixture("promo/medina_lidl_plus_6.html"), "u", MEDINA, ctx
    )
    assert promo is not None
    assert promo.code is None and "Lidl Plus" in promo.code_note
    assert promo.discount_percent == 6.0
    assert promo.brands == ("NOKIAN", "YOKOHAMA", "SEMPERIT", "KLEBER", "TIGAR", "RADAR")
    assert promo.valid_from == date(2026, 11, 1)
    assert promo.valid_until == date(2026, 11, 30)
    assert promo.published_at == date(2026, 11, 1)
    assert promo.applies_to_tyres and promo.origin is PromoOrigin.SHOP


def test_medina_non_code_campaigns_ignored(ctx) -> None:
    for name in ("medina_services_30.html", "medina_pirelli_gift.html"):
        assert (
            MedinaPromoSource.parse_detail(load_fixture(f"promo/{name}"), "u", MEDINA, ctx) is None
        )


def test_medina_lookup_with_fake_http(ctx) -> None:
    lidl = "https://medina-med.com/promotsii/vzemi-6-otstapka-za-gumi-s-lidl-plus-2984/"
    http = FakeHttp(
        {
            MEDINA_PROMO_LIST: (200, load_fixture("promo/medina_promotsii.html")),
            lidl: (200, load_fixture("promo/medina_lidl_plus_6.html")),
        }
    )
    ctx.http = http  # type: ignore[assignment]
    out = MedinaPromoSource().lookup(MEDINA, ctx)
    assert [p.discount_percent for p in out.codes] == [6.0]
    assert any(not c.ok for c in out.checks)  # other detail pages 404 in the fake


def test_gumi24_card_payment_discount(ctx) -> None:
    codes = ShopPageSource().parse_page(load_fixture("promo/gumi24_payment.html"), "u", GUMI24, ctx)
    assert len(codes) == 1
    assert codes[0].code is None and codes[0].discount_percent == 2.0
    assert "карта" in codes[0].code_note


def test_shop_home_pages_without_codes(ctx) -> None:
    for name, shop in (("tirendo_home.html", TIRENDO), ("primex_home.html", MEDINA)):
        assert ShopPageSource().parse_page(load_fixture(f"promo/{name}"), "u", shop, ctx) == []


def test_kuponovo_tirendo(ctx) -> None:
    codes = KuponovoSource().parse(load_fixture("promo/kuponovo_tirendo.html"), "u", TIRENDO, ctx)
    # only the newsletter offer is a "code"; its placeholder "БЮЛЕТИН" is not a real code
    assert len(codes) == 1
    assert codes[0].code is None and "бюлетин" in codes[0].code_note
    assert codes[0].discount_percent == 10.0
    assert codes[0].published_at == date(2026, 4, 20)
    kept, dropped = filter_current(codes, NOW.date(), Freshness(30))
    assert kept == [] and "по-стар от 30 дни" in dropped[0][1]


def test_kuponovo_emag_codes_not_for_tyres(ctx) -> None:
    codes = KuponovoSource().parse(load_fixture("promo/kuponovo_emag.html"), "u", EMAG, ctx)
    by_code = {c.code: c for c in codes}
    assert {"MultiDeals1", "Electro3", "SmartGadgets", "GENIUSDEALS"} <= set(by_code)
    multi = by_code["MultiDeals1"]
    assert multi.valid_until == date(2026, 12, 2)
    assert multi.selected_products_only  # "до -20%"
    assert not multi.applies_to_tyres  # eMAG is a marketplace and the text names no tyres
    kept, dropped = filter_current(codes, NOW.date(), Freshness(30))
    assert kept == []
    assert {r for _, r in dropped} == {"не се отнася за гуми"}


def test_cuponeria_hidden_codes_only(ctx) -> None:
    assert (
        CuponeriaSource().parse(load_fixture("promo/cuponeria_tirendo.html"), "u", TIRENDO, ctx)
        == []
    )
    # the only CODE on the eMAG page is expired (Oral-B, 25.10.2026) -> skipped
    assert CuponeriaSource().parse(load_fixture("promo/cuponeria_emag.html"), "u", EMAG, ctx) == []


def test_discounts_bg_expired_code_dropped(ctx) -> None:
    codes = DiscountsBgSource().parse(
        load_fixture("promo/discounts_tirendo.html"), "u", TIRENDO, ctx
    )
    assert len(codes) == 1
    code = codes[0]
    assert code.code is None and "D10" in code.code_note
    assert code.discount_percent == 5.0
    assert code.valid_until == date(2026, 4, 19)
    assert code.confidence is Confidence.LOW
    kept, dropped = filter_current(codes, NOW.date(), Freshness(30))
    assert kept == [] and dropped[0][1] == "изтекъл на 19.04.2026"


def test_aggregator_404_and_redirect(ctx) -> None:
    http = FakeHttp(
        {
            "https://discounts.bg/magazin/gumi7.com/": (
                200,
                "<html></html>",
                "https://discount.ro/",
            ),
        }
    )
    ctx.http = http  # type: ignore[assignment]
    out = DiscountsBgSource().lookup(GUMI7, ctx)
    assert out.codes == [] and out.checks[0].outcome == "магазинът не е в сайта"
    out = KuponovoSource().lookup(GUMI7, ctx)
    assert out.codes == [] and out.checks[0].outcome == "магазинът не е в сайта"
