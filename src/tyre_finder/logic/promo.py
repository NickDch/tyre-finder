"""Apply promo codes to offers: effective (promo) price only when unambiguous."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from tyre_finder.data.brands import normalize_brand
from tyre_finder.models import Confidence, PromoCode, PromoOrigin, PromoPrice, TyreOffer

SET_SIZE = 4

# Gumi7 product badge, e.g. "-3% с код: SUM26"
_BADGE_RE = re.compile(
    r"-\s?(?P<p>\d{1,2}(?:[.,]\d{1,2})?)\s?%\s+с\s+код\s*:?\s*(?P<code>[A-Za-z0-9][A-Za-z0-9_-]{2,23})",
    re.IGNORECASE,
)


class Applicability(Enum):
    """Whether/how a promo applies to an offer."""

    COMPUTED = "computed"  # effective price computed
    NOT_COMPUTABLE = "not_computable"  # applies, but the discount cannot be computed safely
    NOT_FOR_OFFER = "not_for_offer"  # e.g. different brand, order too small


@dataclass(frozen=True, slots=True)
class PromoEvaluation:
    """Result of checking one promo against one offer."""

    promo: PromoCode
    applicability: Applicability
    price: PromoPrice | None = None
    reason: str = ""


def badge_promos(offer: TyreOffer, now: datetime) -> list[PromoCode]:
    """Codes printed on the product's own badges (e.g. Gumi7 roundels)."""
    promos: list[PromoCode] = []
    for badge in offer.badges:
        m = _BADGE_RE.search(badge)
        if m is None:
            continue
        promos.append(
            PromoCode(
                shop=offer.shop,
                code=m.group("code"),
                title=badge.strip(),
                origin=PromoOrigin.BADGE,
                source_url=offer.url,
                fetched_at=now,
                discount_percent=float(m.group("p").replace(",", ".")),
                conditions=f"Етикет на продукта: „{badge.strip()}“",
            )
        )
    return promos


def evaluate(offer: TyreOffer, promo: PromoCode) -> PromoEvaluation:
    """Compute the promo price for *offer* when the terms are unambiguous."""
    if promo.brands and normalize_brand(offer.brand) not in promo.brands:
        return PromoEvaluation(promo, Applicability.NOT_FOR_OFFER, reason="друга марка")
    if promo.selected_products_only or not promo.applies_to_tyres:
        return PromoEvaluation(
            promo, Applicability.NOT_COMPUTABLE, reason="само за избрани продукти"
        )
    price = offer.price_eur
    unit: float | None = None
    total4: float | None = None
    notes: list[str] = []
    if promo.discount_percent is not None:
        factor = 1 - promo.discount_percent / 100
        unit = round(price * factor, 2)
        total4 = round(price * SET_SIZE * factor, 2)
    elif promo.discount_amount_eur is not None:
        # a fixed amount is taken off the order, not off each tyre
        total4 = round(max(price * SET_SIZE - promo.discount_amount_eur, 0.0), 2)
        notes.append("отстъпката е за цялата поръчка")
    else:
        return PromoEvaluation(promo, Applicability.NOT_COMPUTABLE, reason="неясна отстъпка")
    if promo.min_quantity is not None:
        if promo.min_quantity > SET_SIZE:
            return PromoEvaluation(
                promo, Applicability.NOT_COMPUTABLE, reason=f"при поне {promo.min_quantity} бр."
            )
        unit = None if promo.min_quantity > 1 else unit
        notes.append(f"при поне {promo.min_quantity} бр.")
    if promo.min_order_eur is not None:
        if price >= promo.min_order_eur:
            pass
        elif price * SET_SIZE >= promo.min_order_eur:
            unit = None
            notes.append(f"мин. поръчка {promo.min_order_eur:.2f} € — важи при 4 бр.")
        else:
            return PromoEvaluation(
                promo,
                Applicability.NOT_FOR_OFFER,
                reason=f"мин. поръчка {promo.min_order_eur:.2f} €",
            )
    return PromoEvaluation(
        promo,
        Applicability.COMPUTED,
        PromoPrice(promo, unit, total4, "; ".join(notes)),
    )


def apply_promos(
    offers: list[TyreOffer],
    promos_by_shop: dict[str, list[PromoCode]],
    *,
    enabled: bool = True,
    apply_possible: bool = False,
    now: datetime | None = None,
) -> int:
    """Set ``offer.promo`` to the best computable promo; returns how many offers got one.

    Low-confidence codes are only applied when *apply_possible* is True.
    """
    now = now or datetime.now()
    count = 0
    for offer in offers:
        offer.promo = None
        if not enabled:
            continue
        best: PromoPrice | None = None
        for promo in [*badge_promos(offer, now), *promos_by_shop.get(offer.shop, [])]:
            if promo.confidence is Confidence.LOW and not apply_possible:
                continue
            ev = evaluate(offer, promo)
            if ev.price is None or ev.price.compare_price_eur is None:
                continue
            if best is None or ev.price.compare_price_eur < (best.compare_price_eur or 1e12):
                best = ev.price
        if best is not None and (best.compare_price_eur or 0) < offer.price_eur:
            offer.promo = best
            count += 1
    return count


def promos_for_offer(offer: TyreOffer, promos: list[PromoCode]) -> list[PromoEvaluation]:
    """All promos relevant to the offer's shop that are not ruled out for this offer."""
    out: list[PromoEvaluation] = []
    for promo in [*badge_promos(offer, datetime.now()), *promos]:
        ev = evaluate(offer, promo)
        if ev.applicability is not Applicability.NOT_FOR_OFFER:
            out.append(ev)
    return out
