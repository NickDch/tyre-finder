"""Effective (promo) prices."""

from __future__ import annotations

from datetime import datetime

from tyre_finder.logic.grouping import group_offers
from tyre_finder.logic.promo import Applicability, apply_promos, badge_promos, evaluate
from tyre_finder.models import (
    Confidence,
    PromoCode,
    PromoOrigin,
    Season,
    TyreOffer,
    TyreSize,
)

NOW = datetime(2026, 11, 23, 12)


def offer(
    shop: str, price: float, brand: str = "Nokian", badges: tuple[str, ...] = ()
) -> TyreOffer:
    return TyreOffer(
        shop,
        brand,
        "Hakkapeliitta R5",
        TyreSize(205, 55, 16),
        Season.WINTER,
        price,
        "EUR",
        f"https://{shop}.bg/p",
        load_index="94",
        speed_index="R",
        badges=badges,
    )


def promo(**kw: object) -> PromoCode:
    base: dict[str, object] = {
        "shop": "A",
        "code": "X10",
        "title": "t",
        "origin": PromoOrigin.MANUAL,
        "source_url": "u",
        "fetched_at": NOW,
    }
    base.update(kw)
    return PromoCode(**base)  # type: ignore[arg-type]


def test_percent_unit_and_set_of_four() -> None:
    ev = evaluate(offer("A", 100.0), promo(discount_percent=6))
    assert ev.applicability is Applicability.COMPUTED
    assert ev.price is not None
    assert ev.price.unit_price_eur == 94.0
    assert ev.price.set4_total_eur == 376.0
    assert ev.price.compare_price_eur == 94.0


def test_fixed_amount_is_per_order() -> None:
    ev = evaluate(offer("A", 100.0), promo(discount_amount_eur=20))
    assert ev.price is not None
    assert ev.price.unit_price_eur is None
    assert ev.price.set4_total_eur == 380.0
    assert ev.price.compare_price_eur == 95.0
    assert "цялата поръчка" in ev.price.note


def test_min_order_respected() -> None:
    ev = evaluate(offer("A", 60.0), promo(discount_percent=10, min_order_eur=200))
    assert ev.price is not None and ev.price.unit_price_eur is None
    assert ev.price.set4_total_eur == 216.0  # 4 x 60 = 240 >= 200
    ev = evaluate(offer("A", 40.0), promo(discount_percent=10, min_order_eur=200))
    assert ev.applicability is Applicability.NOT_FOR_OFFER
    ev = evaluate(offer("A", 250.0), promo(discount_percent=10, min_order_eur=200))
    assert ev.price is not None and ev.price.unit_price_eur == 225.0


def test_min_quantity_and_brand_restriction() -> None:
    ev = evaluate(offer("A", 100.0), promo(discount_percent=10, min_quantity=4))
    assert ev.price is not None and ev.price.unit_price_eur is None
    assert ev.price.compare_price_eur == 90.0
    ev = evaluate(
        offer("A", 100.0, brand="Michelin"), promo(discount_percent=6, brands=("NOKIAN",))
    )
    assert ev.applicability is Applicability.NOT_FOR_OFFER


def test_ambiguous_terms_not_computed() -> None:
    assert evaluate(offer("A", 100.0), promo()).applicability is Applicability.NOT_COMPUTABLE
    ev = evaluate(offer("A", 100.0), promo(discount_percent=20, selected_products_only=True))
    assert ev.applicability is Applicability.NOT_COMPUTABLE and ev.price is None


def test_apply_promos_changes_best_offer() -> None:
    offers = [offer("A", 100.0), offer("B", 97.0)]
    groups = group_offers(offers)
    assert groups[0].best_offer.shop == "B"
    n = apply_promos(offers, {"A": [promo(discount_percent=6)]})
    assert n == 1
    assert groups[0].best_offer.shop == "A"
    assert groups[0].best_price == 94.0
    apply_promos(offers, {"A": [promo(discount_percent=6)]}, enabled=False)
    assert groups[0].best_offer.shop == "B"
    assert all(o.promo is None for o in offers)


def test_low_confidence_needs_opt_in() -> None:
    offers = [offer("A", 100.0)]
    low = promo(discount_percent=10, confidence=Confidence.LOW, origin=PromoOrigin.WEB)
    assert apply_promos(offers, {"A": [low]}) == 0
    assert apply_promos(offers, {"A": [low]}, apply_possible=True) == 1
    assert offers[0].effective_price_eur == 90.0


def test_best_of_several_promos() -> None:
    offers = [offer("A", 100.0)]
    apply_promos(
        offers, {"A": [promo(discount_percent=5), promo(code="Y", discount_amount_eur=40)]}
    )
    assert offers[0].promo is not None and offers[0].promo.promo.code == "Y"
    assert offers[0].effective_price_eur == 90.0


def test_gumi7_badge_code() -> None:
    o = offer("Gumi7", 80.0, badges=("Ново", "-3% с код: SUM26", "- 5% с финансиране IUTE"))
    promos = badge_promos(o, NOW)
    assert [(p.code, p.discount_percent) for p in promos] == [("SUM26", 3.0)]
    apply_promos([o], {})
    assert o.promo is not None and o.effective_price_eur == 77.6
