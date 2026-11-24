"""Promo codes published on the shops' own websites."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from tyre_finder.data.http import CancelledError, FetchError
from tyre_finder.data.parsing import clean_text
from tyre_finder.data.promo.base import (
    LookupContext,
    PromoSource,
    ShopRef,
    SourceCheck,
    SourceOutput,
)
from tyre_finder.data.promo.dates import parse_date
from tyre_finder.data.promo.extract import find_code_candidates, parse_terms
from tyre_finder.models import Confidence, PromoCode, PromoOrigin

log = logging.getLogger(__name__)

# Extra pages per shop domain that publish promotions (verified 23.11.2026).
SHOP_PROMO_PAGES: dict[str, tuple[str, ...]] = {
    "diana-ltd.com": ("https://diana-ltd.com/promo",),
    "primex-bg.com": ("https://primex-bg.com/vsichki-oferti.html",),
    "supergumi.bg": ("https://www.supergumi.bg/promocii-na-gumi",),
    "24gumi.bg": ("https://24gumi.bg/pages/15-%D0%BF%D0%BB%D0%B0%D1%89%D0%B0%D0%BD%D0%B5",),
}
MEDINA_PROMO_LIST = "https://medina-med.com/promotsii/"

# "При плащане с карта получавате 2% отстъпка от стойността на гумите" (24gumi.bg)
_CARD_DISCOUNT_RE = re.compile(
    r"(?:при\s+)?плащане\s+с\s+(?:банкова\s+|кредитна\s+|дебитна\s+)?карта[^.]{0,60}?"
    r"(?P<p>\d{1,2}(?:[.,]\d)?)\s?%\s+отстъпка[^.]{0,120}",
    re.IGNORECASE,
)


def _visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    return clean_text(soup.get_text(" "))


class ShopPageSource(PromoSource):
    """Scans the shop's home page and known promo pages for codes."""

    label = "Сайт на магазина"

    def applies_to(self, shop: ShopRef) -> bool:
        return shop.domain != "medina-med.com"  # handled by MedinaPromoSource

    def pages_for(self, shop: ShopRef) -> list[str]:
        """Home page + known promo pages."""
        return [shop.base_url, *SHOP_PROMO_PAGES.get(shop.domain, ())]

    def lookup(self, shop: ShopRef, ctx: LookupContext) -> SourceOutput:
        out = SourceOutput()
        for url in self.pages_for(shop):
            try:
                html = ctx.http.get_text(url)
            except FetchError as exc:
                out.checks.append(SourceCheck(self.label, url, str(exc), ok=False))
                continue
            codes = self.parse_page(html, url, shop, ctx)
            out.codes.extend(codes)
            out.checks.append(SourceCheck(self.label, url, _outcome(codes)))
        return out

    def parse_page(self, html: str, url: str, shop: ShopRef, ctx: LookupContext) -> list[PromoCode]:
        """Codes on one shop page."""
        text = _visible_text(self.soup(html))
        codes: list[PromoCode] = []
        for m in _CARD_DISCOUNT_RE.finditer(text):
            sentence = m.group(0).strip()
            codes.append(
                PromoCode(
                    shop=shop.name,
                    code=None,
                    title=f"{m.group('p')}% отстъпка при плащане с карта",
                    origin=PromoOrigin.SHOP,
                    source_url=url,
                    fetched_at=ctx.now,
                    discount_percent=float(m.group("p").replace(",", ".")),
                    conditions=sentence,
                    code_note="без код · автоматично при плащане с карта",
                )
            )
        for cand in find_code_candidates(text):
            if not cand.strong:
                continue
            terms = parse_terms(cand.window, general_store=shop.general_store)
            if terms.valid_until is not None and terms.valid_until < ctx.today:
                log.info("%s: skipping expired code %s on %s", shop.name, cand.code, url)
                continue
            has_discount = terms.percent is not None or terms.amount_eur is not None
            codes.append(
                PromoCode(
                    shop=shop.name,
                    code=cand.code,
                    title=f"Код {cand.code}",
                    origin=PromoOrigin.SHOP,
                    source_url=url,
                    fetched_at=ctx.now,
                    discount_percent=terms.percent,
                    discount_amount_eur=terms.amount_eur,
                    min_order_eur=terms.min_order_eur,
                    min_quantity=terms.min_quantity,
                    brands=terms.brands,
                    conditions=cand.window,
                    valid_from=terms.valid_from,
                    valid_until=terms.valid_until,
                    confidence=Confidence.HIGH if has_discount else Confidence.LOW,
                    score=0.9 if has_discount else 0.5,
                    applies_to_tyres=terms.applies_to_tyres,
                    selected_products_only=terms.selected_only,
                )
            )
        return codes


def _outcome(codes: list[PromoCode]) -> str:
    if not codes:
        return "няма публикуван код"
    return f"{len(codes)} намерени"


class MedinaPromoSource(PromoSource):
    """medina-med.com/promotsii/: campaign pages ("Промо код" field, Lidl Plus codes)."""

    label = "Медина-Мед промоции"
    max_details = 6

    def applies_to(self, shop: ShopRef) -> bool:
        return shop.domain == "medina-med.com"

    def lookup(self, shop: ShopRef, ctx: LookupContext) -> SourceOutput:
        out = SourceOutput()
        try:
            listing = ctx.http.get_text(MEDINA_PROMO_LIST)
        except FetchError as exc:
            out.checks.append(SourceCheck(self.label, MEDINA_PROMO_LIST, str(exc), ok=False))
            return out
        links = self.parse_listing(listing)
        out.checks.append(
            SourceCheck(self.label, MEDINA_PROMO_LIST, f"{len(links)} промоции с отстъпка")
        )
        for url in links[: self.max_details]:
            try:
                html = ctx.http.get_text(url)
            except CancelledError:
                raise
            except FetchError as exc:
                out.checks.append(SourceCheck(self.label, url, str(exc), ok=False))
                continue
            promo = self.parse_detail(html, url, shop, ctx)
            out.checks.append(
                SourceCheck(self.label, url, promo.title if promo else "не е промокод за гуми")
            )
            if promo is not None:
                out.codes.append(promo)
        return out

    @staticmethod
    def parse_listing(html: str) -> list[str]:
        """Detail URLs of campaigns that mention a discount."""
        soup = PromoSource.soup(html)
        urls: list[str] = []
        for item in soup.select("a.med-promo-content-item[href]"):
            text = clean_text(item.get_text(" "))
            if re.search(r"%|отстъпк|промо\s*код|код", text, re.IGNORECASE):
                urls.append(urljoin(MEDINA_PROMO_LIST, str(item["href"])))
        return urls

    @staticmethod
    def parse_detail(html: str, url: str, shop: ShopRef, ctx: LookupContext) -> PromoCode | None:
        """A PromoCode when the campaign is redeemed with a code online on tyres."""
        soup = PromoSource.soup(html)
        title_tag = soup.select_one("h1.med-news-view-title")
        body = soup.select_one("div.med-news-view-content")
        if title_tag is None or body is None:
            return None
        title = clean_text(title_tag.get_text(" "))
        date_tag = soup.select_one("div.med-news-view-date")
        published = parse_date(date_tag.get_text(" ")) if date_tag else None
        text = clean_text(body.get_text(" "))
        if not re.search(r"промо\s*код|код\s+за\s+отстъпка|своя\s+код", text, re.IGNORECASE):
            return None  # gifts, cashback, warranties ... are not codes
        if re.search(r"услуг|монтаж|баланс", title, re.IGNORECASE):
            return None  # fitting services, not tyres
        terms = parse_terms(f"{title}. {text}")
        if terms.percent is None and terms.amount_eur is None:
            return None
        online = bool(re.search(r"онлайн\s+магазин|Промо\s+код", text, re.IGNORECASE))
        note = "личен код от Lidl Plus („Партньори“)" if terms.personal_code else ""
        conditions = " ".join(
            clean_text(li.get_text(" ")) for li in body.select("li") if li.get_text(strip=True)
        )
        return PromoCode(
            shop=shop.name,
            code=None,
            title=title,
            origin=PromoOrigin.SHOP,
            source_url=url,
            fetched_at=ctx.now,
            discount_percent=terms.percent,
            discount_amount_eur=terms.amount_eur,
            min_order_eur=terms.min_order_eur,
            min_quantity=terms.min_quantity,
            brands=terms.brands,
            conditions=(conditions or text)[:600]
            + ("" if online else " (само в сервизите, не онлайн)"),
            code_note=note,
            valid_from=terms.valid_from,
            valid_until=terms.valid_until,
            published_at=published,
            applies_to_tyres=online,
            selected_products_only=terms.selected_only,
        )
