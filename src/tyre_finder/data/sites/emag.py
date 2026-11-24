"""eMAG.bg - the largest Bulgarian marketplace (tyre category, text search)."""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.brands import display_brand, split_brand_model
from tyre_finder.data.parsing import clean_text, parse_size_spec, season_from_text
from tyre_finder.models import SearchQuery, Season, TyreOffer

log = logging.getLogger(__name__)

_SEASON_WORD = {Season.SUMMER: "лятна", Season.WINTER: "зимна", Season.ALL_SEASON: "всесезонна"}
_PREFIX_RE = re.compile(r"^(?:лятна|зимна|всесезонна|автомобилна)?\s*гума\s+", re.IGNORECASE)


_SIZE_RE = re.compile(r"\d{3}\s*/\s*\d{2}\s*,?\s*Z?R\s*\d{2}C?", re.IGNORECASE)
_TAIL_INDEX_RE = re.compile(r"\b(\d{2,3})(?:/\d{2,3})?\s*(?:XL\s*)?([A-HJ-NP-Z])\b")


def _split_title(title: str) -> tuple[str, str, str | None, str | None]:
    """Split eMAG titles into brand, model, load and speed index.

    Handles both "Лятна гума ROADX RXMOTION-DU71 205/55R16 91Y" and
    "Всесезонна гума 205/55 R16 Westlake Z401 94 XL V".
    """
    text = _PREFIX_RE.sub("", title).replace(",", " ")
    match = _SIZE_RE.search(text)
    head, tail = (text[: match.start()], text[match.end() :]) if match else (text, "")
    li = si = None
    index = _TAIL_INDEX_RE.search(tail)
    if index:
        li, si = index.group(1), index.group(2).upper()
    if not head.strip():
        head = tail[: index.start()] if index else tail
    brand, model = split_brand_model(clean_text(head))
    return brand, clean_text(model), li, si


class EmagScraper(TyreScraper):
    """Parses eMAG search result cards (data-* attributes + JSON)."""

    name = "eMAG"
    home_url = "https://www.emag.bg/"

    def build_url(self, query: SearchQuery, page: int) -> str | None:
        text = quote_plus(
            f"{_SEASON_WORD[query.season]} {query.size.width}/"
            f"{query.size.profile} R{query.size.rim}"
        )
        suffix = "c" if page == 1 else f"p{page}/c"
        return f"https://www.emag.bg/search/avtomobilni-gumi/{text}/{suffix}"

    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        soup = self.soup(html)
        offers: list[TyreOffer] = []
        for card in soup.select("div.card-item.js-product-data[data-product-id]"):
            title = clean_text(card.get("data-name"))
            url = card.get("data-url") or ""
            spec = parse_size_spec(title)
            if not title or not url or spec is None:
                continue
            price: float | None = None
            currency = "EUR"
            fav = card.select_one("button.add-to-favorites[data-product]")
            if fav is not None:
                try:
                    data = json.loads(fav["data-product"])
                    price = float(data["price"])
                    currency = str(data.get("currency", "EUR"))
                except (KeyError, ValueError, TypeError) as exc:
                    log.debug("eMAG: bad data-product JSON: %s", exc)
            if price is None:
                continue
            img = card.select_one("img")
            brand, model, li, si = _split_title(title)
            li = li or spec.load_index
            si = si or spec.speed_index
            offers.append(
                TyreOffer(
                    shop=self.name,
                    brand=display_brand(brand),
                    model=model,
                    size=spec.size,
                    season=season_from_text(title),
                    price=price,
                    currency=currency,
                    url=url,
                    image_url=img.get("src") if img else None,
                    load_index=li,
                    speed_index=si,
                    raw_title=title,
                )
            )
        return offers
