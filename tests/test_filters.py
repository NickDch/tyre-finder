from __future__ import annotations

from tyre_finder.logic.filters import FilterCriteria, SortOrder, apply_filters, brand_counts
from tyre_finder.logic.grouping import group_offers
from tyre_finder.models import Season, TyreOffer, TyreSize


def _offer(shop: str, brand: str, model: str, price: float, currency: str = "EUR") -> TyreOffer:
    return TyreOffer(
        shop=shop,
        brand=brand,
        model=model,
        size=TyreSize(205, 55, 16),
        season=Season.SUMMER,
        price=price,
        currency=currency,
        url=f"https://{shop}/{model}",
        load_index="91",
        speed_index="V",
    )


GROUPS = group_offers(
    [
        _offer("a", "Michelin", "Primacy 4", 110.0),
        _offer("b", "Michelin", "Primacy 4", 99.0),
        _offer("a", "Hankook", "Kinergy Eco 2", 60.0),
        _offer("c", "Sava", "Intensa HP 2", 50.0),
        _offer("c", "Goodyear", "EfficientGrip", 156.47, currency="BGN"),  # 80.00 EUR
    ]
)


def test_price_filter_uses_best_price() -> None:
    result = apply_filters(GROUPS, FilterCriteria(min_price=95, max_price=100))
    assert [g.brand for g in result] == ["Michelin"]


def test_bgn_prices_are_converted() -> None:
    result = apply_filters(GROUPS, FilterCriteria(min_price=79, max_price=81))
    assert [g.brand for g in result] == ["Goodyear"]


def test_brand_filter_multi_select_and_aliases() -> None:
    result = apply_filters(GROUPS, FilterCriteria(brands={"SAVA", "hankook"}))
    assert {g.brand for g in result} == {"Sava", "Hankook"}
    assert apply_filters(GROUPS, FilterCriteria(brands=set())) == []
    assert len(apply_filters(GROUPS, FilterCriteria(brands=None))) == 4


def test_sorting() -> None:
    asc = apply_filters(GROUPS, FilterCriteria(sort=SortOrder.PRICE_ASC))
    assert [g.best_price for g in asc] == sorted(g.best_price for g in GROUPS)
    desc = apply_filters(GROUPS, FilterCriteria(sort=SortOrder.PRICE_DESC))
    assert desc[0].brand == "Michelin"
    shops = apply_filters(GROUPS, FilterCriteria(sort=SortOrder.SHOPS_DESC))
    assert shops[0].shop_count == 2


def test_multi_shop_only() -> None:
    result = apply_filters(GROUPS, FilterCriteria(multi_shop_only=True))
    assert [g.brand for g in result] == ["Michelin"]


def test_brand_counts_sorted() -> None:
    assert brand_counts(GROUPS) == [("Goodyear", 1), ("Hankook", 1), ("Michelin", 1), ("Sava", 1)]
