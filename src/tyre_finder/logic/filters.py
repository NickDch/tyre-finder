"""Filtering and sorting of grouped results (price uses the best offer of a group)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from tyre_finder.data.brands import normalize_brand
from tyre_finder.models import TyreGroup


class SortOrder(Enum):
    """Result ordering."""

    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    SHOPS_DESC = "shops_desc"
    BRAND = "brand"


@dataclass(slots=True)
class FilterCriteria:
    """User selected filters. ``brands=None`` means all brands."""

    min_price: float | None = None
    max_price: float | None = None
    brands: set[str] | None = None
    multi_shop_only: bool = False
    sort: SortOrder = SortOrder.PRICE_ASC
    shops: set[str] | None = field(default=None)


def brand_counts(groups: list[TyreGroup]) -> list[tuple[str, int]]:
    """Brands present in *groups* with the number of tyres each, sorted A-Z."""
    names: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for g in groups:
        key = normalize_brand(g.brand)
        names.setdefault(key, g.brand)
        counts[key] += 1
    return sorted(((names[k], c) for k, c in counts.items()), key=lambda x: x[0].upper())


def apply_filters(groups: list[TyreGroup], criteria: FilterCriteria) -> list[TyreGroup]:
    """Return the filtered and sorted groups."""
    brand_keys = (
        {normalize_brand(b) for b in criteria.brands} if criteria.brands is not None else None
    )
    result: list[TyreGroup] = []
    for g in groups:
        price = g.best_price
        if criteria.min_price is not None and price < criteria.min_price:
            continue
        if criteria.max_price is not None and price > criteria.max_price:
            continue
        if brand_keys is not None and normalize_brand(g.brand) not in brand_keys:
            continue
        if criteria.multi_shop_only and g.shop_count < 2:
            continue
        if criteria.shops is not None and not any(o.shop in criteria.shops for o in g.offers):
            continue
        result.append(g)

    if criteria.sort is SortOrder.PRICE_ASC:
        result.sort(key=lambda g: (g.best_price, g.brand.upper(), g.model.upper()))
    elif criteria.sort is SortOrder.PRICE_DESC:
        result.sort(key=lambda g: (-g.best_price, g.brand.upper(), g.model.upper()))
    elif criteria.sort is SortOrder.SHOPS_DESC:
        result.sort(key=lambda g: (-g.shop_count, g.best_price))
    else:
        result.sort(key=lambda g: (g.brand.upper(), g.model.upper(), g.best_price))
    return result
