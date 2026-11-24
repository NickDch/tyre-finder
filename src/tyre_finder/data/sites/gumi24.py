"""24Gumi.bg."""

from __future__ import annotations

import re

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.brands import display_brand
from tyre_finder.data.parsing import clean_text, parse_price, parse_size_spec, season_from_text
from tyre_finder.models import SearchQuery, Season, TyreOffer

_SEASON_SLUG = {Season.SUMMER: "letni", Season.WINTER: "zimni", Season.ALL_SEASON: "vsesezonni"}
_SPEED_RE = re.compile(r"Скоростен индекс:\s*([A-Z])")
_LOAD_RE = re.compile(r"Товарен индекс:\s*(\d{2,3})")


class Gumi24Scraper(TyreScraper):
    """Parses ``#tirepage .box`` cards."""

    name = "24Gumi"
    home_url = "https://24gumi.bg/"

    def build_url(self, query: SearchQuery, page: int) -> str | None:
        s = query.size
        url = f"https://24gumi.bg/gumi/{_SEASON_SLUG[query.season]}/{s.width}-{s.profile}-{s.rim}/all/"
        return url if page == 1 else f"{url}{page}/"

    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        soup = self.soup(html)
        offers: list[TyreOffer] = []
        for box in soup.select("#tirepage div.box"):
            link = box.select_one("a.full[href]")
            title_el = box.select_one(".title")
            price_el = box.select_one(".price")
            if not (link and title_el and price_el):
                continue
            size_el = title_el.select_one("b")
            spec = parse_size_spec(size_el.get_text() if size_el else link.get("title", ""))
            eur = price_el.get("data-unit-eur")
            price = round(float(eur), 2) if eur else parse_price(price_el.get_text(" "))
            if spec is None or price is None:
                continue
            brand_el = title_el.select_one(".card-brand")
            brand = clean_text(brand_el.get_text()) if brand_el else ""
            # Model is the bare text node between the brand div and the size <b>.
            model_parts = [
                clean_text(str(node))
                for node in title_el.children
                if isinstance(node, str) and clean_text(str(node))
            ]
            model = model_parts[0] if model_parts else ""
            details = title_el.get_text(" ")
            speed = _SPEED_RE.search(details)
            load = _LOAD_RE.search(details)
            img = box.select_one(".image img")
            season_el = box.select_one(".season")
            offers.append(
                TyreOffer(
                    shop=self.name,
                    brand=display_brand(brand),
                    model=model,
                    size=spec.size,
                    season=season_from_text(season_el.get_text()) if season_el else None,
                    price=price,
                    currency="EUR",
                    url=link["href"],
                    image_url=img.get("src") if img else None,
                    load_index=load.group(1) if load else spec.load_index,
                    speed_index=speed.group(1) if speed else spec.speed_index,
                    raw_title=clean_text(link.get("title")),
                )
            )
        return offers
