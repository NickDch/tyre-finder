"""Generic, user-configurable CSS-selector scraper."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import Tag
from bs4.exceptions import ParserRejectedMarkup
from soupsieve import SelectorSyntaxError

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.brands import display_brand, split_brand_model
from tyre_finder.data.parsing import (
    ParseError,
    clean_text,
    detect_currency,
    parse_price,
    parse_size_spec,
    season_from_text,
)
from tyre_finder.models import SearchQuery, Season, TyreOffer

PLACEHOLDERS: tuple[str, ...] = ("{width}", "{profile}", "{rim}", "{season}")
_ALLOWED_FIELDS = {"width", "profile", "rim", "season", "page"}


class GenericConfigError(ValueError):
    """Raised for an invalid generic scraper configuration."""


@dataclass(slots=True)
class GenericSelectors:
    """CSS selectors. ``selector@attr`` reads an attribute instead of the text."""

    item: str = ""
    title: str = ""
    price: str = ""
    link: str = "a@href"
    image: str = "img@src"
    brand: str = ""
    size: str = ""


@dataclass(slots=True)
class GenericSiteSpec:
    """Everything needed to scrape a site without writing code."""

    search_url: str = ""
    page_suffix: str = ""
    season_values: dict[str, str] = field(
        default_factory=lambda: {s.value: s.value for s in Season}
    )
    selectors: GenericSelectors = field(default_factory=GenericSelectors)

    def validate(self) -> list[str]:
        """Return a list of human readable (Bulgarian) problems; empty if valid."""
        errors: list[str] = []
        if not self.search_url.startswith(("http://", "https://")):
            errors.append("URL за търсене трябва да започва с http:// или https://")
        missing = [p for p in PLACEHOLDERS[:3] if p not in self.search_url]
        if missing:
            errors.append("URL за търсене трябва да съдържа " + ", ".join(missing))
        unknown = set(re.findall(r"{(\w+)}", self.search_url + self.page_suffix)) - _ALLOWED_FIELDS
        if unknown:
            errors.append("Непознати полета в URL: " + ", ".join(sorted(unknown)))
        if self.page_suffix and "{page}" not in self.page_suffix:
            errors.append("Суфиксът за страници трябва да съдържа {page}")
        if "{season}" in self.search_url:
            for season in Season:
                if not self.season_values.get(season.value, "").strip():
                    errors.append(f"Липсва стойност за сезон „{season.label_bg}“")
        for name in ("item", "title", "price", "link"):
            if not getattr(self.selectors, name).strip():
                errors.append(f"Селекторът „{name}“ е задължителен")
        return errors


def _select_value(scope: Tag, spec: str) -> str:
    """Evaluate ``css`` or ``css@attr`` (``@attr`` alone reads from *scope*)."""
    if not spec:
        return ""
    css, _, attr = spec.partition("@")
    el = scope.select_one(css.strip()) if css.strip() else scope
    if el is None:
        return ""
    if attr:
        value = el.get(attr.strip(), "")
        return " ".join(value) if isinstance(value, list) else str(value)
    return clean_text(el.get_text(" "))


class GenericScraper(TyreScraper):
    """Scraper driven entirely by a :class:`GenericSiteSpec`."""

    def __init__(self, name: str, base_url: str, spec: GenericSiteSpec, max_pages: int = 2) -> None:
        super().__init__(max_pages=max_pages if spec.page_suffix else 1)
        errors = spec.validate()
        if errors:
            raise GenericConfigError("; ".join(errors))
        self.name = name
        self.home_url = base_url.rstrip("/") + "/"
        self.spec = spec

    def build_url(self, query: SearchQuery, page: int) -> str | None:
        if page > 1 and not self.spec.page_suffix:
            return None
        values = {
            "width": query.size.width,
            "profile": query.size.profile,
            "rim": query.size.rim,
            "season": self.spec.season_values.get(query.season.value, query.season.value),
            "page": page,
        }
        url = self.spec.search_url.format(**values)
        if page > 1:
            url += self.spec.page_suffix.format(**values)
        return url

    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        sel = self.spec.selectors
        try:
            items = self.soup(html).select(sel.item)
        except (SelectorSyntaxError, ParserRejectedMarkup) as exc:
            raise ParseError(f"Невалиден селектор: {exc}") from exc
        offers: list[TyreOffer] = []
        for item in items:
            try:
                title = _select_value(item, sel.title)
                price_text = _select_value(item, sel.price)
                href = _select_value(item, sel.link)
                size_text = _select_value(item, sel.size) if sel.size else title
                brand_text = _select_value(item, sel.brand) if sel.brand else ""
                image = _select_value(item, sel.image) if sel.image else ""
            except SelectorSyntaxError as exc:
                raise ParseError(f"Невалиден селектор: {exc}") from exc
            spec = parse_size_spec(size_text) or parse_size_spec(title)
            price = parse_price(price_text)
            if not title or not href or spec is None or price is None:
                continue
            if brand_text:
                brand = brand_text
                model = (
                    title[len(brand) :].strip()
                    if title.upper().startswith(brand.upper())
                    else title
                )
            else:
                brand, model = split_brand_model(title)
            model = model.split(f"{spec.size.width}/")[0].strip() or model
            offers.append(
                TyreOffer(
                    shop=self.name,
                    brand=display_brand(brand),
                    model=model,
                    size=spec.size,
                    season=season_from_text(item.get_text(" ")[:2000]),
                    price=price,
                    currency=detect_currency(price_text),
                    url=self.absolute(href),
                    image_url=self.absolute(image) if image else None,
                    load_index=spec.load_index,
                    speed_index=spec.speed_index,
                    raw_title=title,
                )
            )
        return offers
