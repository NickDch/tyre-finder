"""Shared "NK Software" e-shop platform (bggumi.com, gumi3.com, gumi-varna.com, ...).

All shops on this platform accept the same ``eshop/search`` URL and render the same
``div.product`` markup, so a new shop only needs its base URL.
"""

from __future__ import annotations

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.brands import display_brand, split_brand_model
from tyre_finder.data.parsing import clean_text, parse_price, parse_size_spec, season_from_text
from tyre_finder.models import SearchQuery, Season, TyreOffer

_SEASON_CODE = {Season.WINTER: "1", Season.SUMMER: "2", Season.ALL_SEASON: "3"}


class NkPlatformScraper(TyreScraper):
    """Scraper for shops built on the NK Software platform (base URL only)."""

    def __init__(self, name: str, base_url: str, max_pages: int = 1) -> None:
        super().__init__(max_pages=max_pages)
        self.name = name
        self.home_url = base_url.rstrip("/") + "/"

    def build_url(self, query: SearchQuery, page: int) -> str | None:
        if page > 1:  # the platform loads further results via JS; first page = cheapest
            return None
        s = query.size
        return (
            f"{self.home_url}eshop/search?type=1&width={s.width}&height={s.profile}"
            f"&inch={s.rim}&season={_SEASON_CODE[query.season]}&sortby=1"
        )

    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        soup = self.soup(html)
        base = soup.select_one("base[href]")
        base_url = base["href"] if base else self.home_url
        offers: list[TyreOffer] = []
        for prod in soup.select("div.list div.product"):
            link = prod.select_one("h2 a")
            sizes = prod.select_one(".sizes")
            price_el = prod.select_one(".price")
            if not (link and sizes and price_el):
                continue
            spec = parse_size_spec(sizes.get_text(" "))
            price = parse_price(price_el.get_text(" "))
            if spec is None or price is None:
                continue
            title = clean_text(link.get_text(" "))
            brand, model = split_brand_model(title)
            img = prod.select_one("a img") or prod.select_one(".thumb img")
            season_el = prod.select_one(".season")
            href = link.get("href", "")
            offers.append(
                TyreOffer(
                    shop=self.name,
                    brand=display_brand(brand),
                    model=model,
                    size=spec.size,
                    season=season_from_text(season_el.get_text()) if season_el else None,
                    price=price,
                    currency="EUR",
                    url=href if href.startswith("http") else base_url + href.lstrip("/"),
                    image_url=(base_url + img["src"].lstrip("/"))
                    if img and img.get("src")
                    else None,
                    load_index=spec.load_index,
                    speed_index=spec.speed_index,
                    raw_title=title,
                )
            )
        return offers
