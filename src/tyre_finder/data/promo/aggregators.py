"""Bulgarian coupon aggregators.

Verified on 23.11.2026 (HTTP 200 only for eMAG, Tirendo and Gumi7; other shops 404):

* kuponovo.bg/magazin/<slug>  - Next.js; coupons as JSON in the RSC payload, codes in clear
* cuponeria.bg/magazin/<slug>/ - Next.js; coupons as JSON, codes hidden (only a hint)
* discounts.bg/magazin/<domain>/ - server HTML ``div.voucher``; codes encrypted (hint only)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from urllib.parse import urlsplit

from tyre_finder.data.http import FetchError
from tyre_finder.data.parsing import clean_text
from tyre_finder.data.promo.base import (
    LookupContext,
    PromoSource,
    ShopRef,
    SourceCheck,
    SourceOutput,
)
from tyre_finder.data.promo.dates import parse_date, parse_iso_datetime
from tyre_finder.data.promo.extract import looks_like_code, parse_terms
from tyre_finder.models import BGN_PER_EUR, Confidence, PromoCode, PromoOrigin

log = logging.getLogger(__name__)

# Aggregator slug per shop domain where it differs from the first domain label.
SLUG_OVERRIDES: dict[str, str] = {"emag.bg": "emag", "24gumi.bg": "24gumi"}

_NEXT_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def shop_slug(shop: ShopRef) -> str:
    """Aggregator slug, e.g. 'tirendo' for tirendo.bg."""
    return SLUG_OVERRIDES.get(shop.domain, shop.domain.split(".")[0])


def next_payload(html: str) -> str:
    """Concatenated React Server Component payload of a Next.js page."""
    parts: list[str] = []
    for raw in _NEXT_PUSH_RE.findall(html):
        try:
            parts.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return "".join(parts)


def _json_objects(text: str, start_pattern: str) -> list[dict[str, object]]:
    decoder = json.JSONDecoder()
    found: dict[str, dict[str, object]] = {}
    for m in re.finditer(start_pattern, text):
        try:
            pos = m.end() - 1 if m.group(0).endswith("{") else m.start()
            obj, _ = decoder.raw_decode(text, pos)
        except ValueError:
            continue
        if isinstance(obj, dict) and "id" in obj:
            found.setdefault(str(obj["id"]), obj)
    return list(found.values())


def _local_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return parse_iso_datetime(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone()  # user's zone
    return dt.date()


def _discount(label: str) -> tuple[float | None, float | None]:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", label)
    if m:
        return float(m.group(1).replace(",", ".")), None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(€|лв)", label)
    if m:
        value = float(m.group(1).replace(",", "."))
        return None, value if m.group(2) == "€" else round(value / BGN_PER_EUR, 2)
    return None, None


class AggregatorSource(PromoSource):
    """Common fetch logic: one page per shop, 404 = shop not listed."""

    host = ""

    def applies_to(self, shop: ShopRef) -> bool:
        return True

    def url_for(self, shop: ShopRef) -> str:
        """Store page URL."""
        raise NotImplementedError

    def lookup(self, shop: ShopRef, ctx: LookupContext) -> SourceOutput:
        out = SourceOutput()
        url = self.url_for(shop)
        try:
            res = ctx.http.fetch(url)
        except FetchError as exc:
            out.checks.append(SourceCheck(self.label, url, str(exc), ok=False))
            return out
        final_host = urlsplit(res.url).netloc.removeprefix("www.")
        if res.status == 404 or final_host != self.host:
            out.checks.append(SourceCheck(self.label, url, "магазинът не е в сайта"))
            return out
        if res.status >= 400:
            out.checks.append(SourceCheck(self.label, url, f"HTTP {res.status}", ok=False))
            return out
        codes = self.parse(res.text, url, shop, ctx)
        out.codes.extend(codes)
        listed = sum(1 for c in codes if c.code or c.code_note)
        out.checks.append(SourceCheck(self.label, url, f"{listed} кода/оферти с код"))
        return out

    def parse(self, html: str, url: str, shop: ShopRef, ctx: LookupContext) -> list[PromoCode]:
        """Codes on the store page (expired ones are dropped later by the service)."""
        raise NotImplementedError


class KuponovoSource(AggregatorSource):
    """kuponovo.bg - codes in clear text in the page JSON."""

    label = "kuponovo.bg"
    host = "kuponovo.bg"

    def url_for(self, shop: ShopRef) -> str:
        return f"https://kuponovo.bg/magazin/{shop_slug(shop)}"

    def parse(self, html: str, url: str, shop: ShopRef, ctx: LookupContext) -> list[PromoCode]:
        payload = next_payload(html)
        codes: list[PromoCode] = []
        for obj in _json_objects(payload, r'\{"id":"\d+","slug"'):
            if obj.get("type") != "code" or obj.get("status") != "active":
                continue
            title = clean_text(str(obj.get("title", "")))
            description = clean_text(str(obj.get("description", "")))
            text = f"{title}. {description}"
            terms = parse_terms(text, general_store=shop.general_store)
            raw_code = str(obj.get("code") or "").strip()
            code = raw_code if looks_like_code(raw_code) else None
            percent, amount = _discount(str(obj.get("discount") or ""))
            note = ""
            if code is None:
                if not terms.newsletter:
                    continue
                note = "кодът се изпраща по имейл след абонамент за бюлетина"
            codes.append(
                PromoCode(
                    shop=shop.name,
                    code=code,
                    title=title,
                    origin=PromoOrigin.AGGREGATOR,
                    source_url=url,
                    fetched_at=ctx.now,
                    discount_percent=percent if percent is not None else terms.percent,
                    discount_amount_eur=amount if amount is not None else terms.amount_eur,
                    min_order_eur=terms.min_order_eur,
                    min_quantity=terms.min_quantity,
                    brands=terms.brands,
                    conditions=description or title,
                    code_note=note,
                    valid_from=_local_date(obj.get("startsAt")),
                    valid_until=_local_date(obj.get("expiresAt")),
                    published_at=_local_date(obj.get("lastUpdated")),
                    confidence=Confidence.HIGH,
                    score=0.8,
                    applies_to_tyres=terms.applies_to_tyres,
                    selected_products_only=terms.selected_only or "избрани" in text.lower(),
                )
            )
        return codes


class CuponeriaSource(AggregatorSource):
    """cuponeria.bg - code types only; the code itself is revealed on click (hint only)."""

    label = "cuponeria.bg"
    host = "cuponeria.bg"

    def url_for(self, shop: ShopRef) -> str:
        return f"https://cuponeria.bg/magazin/{shop_slug(shop)}/"

    def parse(self, html: str, url: str, shop: ShopRef, ctx: LookupContext) -> list[PromoCode]:
        payload = next_payload(html)
        codes: list[PromoCode] = []
        for obj in _json_objects(payload, r'"coupon":\{'):
            if obj.get("type") != "CODE" or not obj.get("hasCode") or obj.get("isExpired"):
                continue
            title = clean_text(str(obj.get("title", "")))
            terms_text = clean_text(str(obj.get("terms") or obj.get("description") or ""))
            terms = parse_terms(f"{title}. {terms_text}", general_store=shop.general_store)
            value = obj.get("discountValue")
            kind = obj.get("discountKind")
            percent = float(value) if kind == "percent" and isinstance(value, int | float) else None
            hint = str(obj.get("codeHint") or "")
            codes.append(
                PromoCode(
                    shop=shop.name,
                    code=None,
                    title=title,
                    origin=PromoOrigin.AGGREGATOR,
                    source_url=url,
                    fetched_at=ctx.now,
                    discount_percent=percent if percent is not None else terms.percent,
                    discount_amount_eur=terms.amount_eur,
                    min_order_eur=terms.min_order_eur,
                    min_quantity=terms.min_quantity,
                    brands=terms.brands,
                    conditions=terms_text or title,
                    code_note=f"кодът е скрит в cuponeria.bg ({hint}) — отворете източника",
                    valid_until=_local_date(obj.get("expiresAt")),
                    published_at=_local_date(obj.get("verifiedAt")),
                    confidence=Confidence.LOW,
                    score=0.6,
                    applies_to_tyres=terms.applies_to_tyres,
                    selected_products_only=terms.selected_only,
                )
            )
        return codes


class DiscountsBgSource(AggregatorSource):
    """discounts.bg - server-rendered vouchers; codes are encrypted (hint only)."""

    label = "discounts.bg"
    host = "discounts.bg"

    def url_for(self, shop: ShopRef) -> str:
        return f"https://discounts.bg/magazin/{shop.domain}/"

    def parse(self, html: str, url: str, shop: ShopRef, ctx: LookupContext) -> list[PromoCode]:
        soup = self.soup(html)
        codes: list[PromoCode] = []
        for card in soup.select("div.voucher.offer"):
            status = card.select_one(".status b")
            if status is None or clean_text(status.get_text()) != "Код":
                continue
            title_tag = card.select_one("b.title-voucher")
            title = clean_text(title_tag.get_text(" ")) if title_tag else ""
            valid_until = None
            details: list[str] = []
            for li in card.select(".more-details li"):
                text = clean_text(li.get_text(" "))
                if text.startswith("Изтича"):
                    valid_until = parse_date(text)
                elif text:
                    details.append(text)
            button = card.select_one("button.btn-getcode")
            hint = ""
            if button is not None:
                hint = clean_text(button.get_text(" ")).replace("Показване на КОД", "").strip()
            description = " ".join(details)
            terms = parse_terms(f"{title}. {description}", general_store=shop.general_store)
            codes.append(
                PromoCode(
                    shop=shop.name,
                    code=None,
                    title=title,
                    origin=PromoOrigin.AGGREGATOR,
                    source_url=url,
                    fetched_at=ctx.now,
                    discount_percent=terms.percent,
                    discount_amount_eur=terms.amount_eur,
                    min_order_eur=terms.min_order_eur,
                    min_quantity=terms.min_quantity,
                    brands=terms.brands,
                    conditions=description or title,
                    code_note=f"кодът е скрит в discounts.bg ({hint}) — отворете източника",
                    valid_until=valid_until,
                    confidence=Confidence.LOW,
                    score=0.5,
                    applies_to_tyres=terms.applies_to_tyres,
                    selected_products_only=terms.selected_only,
                )
            )
        return codes
