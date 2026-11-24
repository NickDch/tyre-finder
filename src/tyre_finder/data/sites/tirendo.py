"""Tirendo.bg (Delticom group) - schema.org microdata in the result list."""

from __future__ import annotations

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.brands import display_brand
from tyre_finder.data.parsing import clean_text, parse_price, parse_size_spec, season_from_text
from tyre_finder.models import SearchQuery, Season, TyreOffer

_SEASON_PARAM = {Season.SUMMER: "so", Season.WINTER: "wi", Season.ALL_SEASON: "gan"}
_PER_PAGE = 28


class TirendoScraper(TyreScraper):
    """Parses ``.product-item[itemtype=Product]`` rows."""

    name = "Tirendo"
    home_url = "https://www.tirendo.bg/"

    def build_url(self, query: SearchQuery, page: int) -> str | None:
        s = query.size
        url = (
            f"https://www.tirendo.bg/search?width={s.width}&profile={s.profile}"
            f"&size={s.rim}&season={_SEASON_PARAM[query.season]}"
        )
        return url if page == 1 else f"{url}&pageNoFull={page}&itemsPerPage={_PER_PAGE}"

    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        soup = self.soup(html)
        offers: list[TyreOffer] = []
        for item in soup.select("div.product-item[itemtype$='schema.org/Product']"):
            title_box = item.select_one(".product-list-title")
            size_el = item.select_one(".result-list-prod-size")
            price_el = item.select_one("[itemprop=price][content]")
            link = title_box.select_one("a[href]") if title_box else None
            if not (title_box and size_el and price_el and link):
                continue
            spec = parse_size_spec(size_el.get_text(" "))
            price = parse_price(price_el["content"])
            if spec is None or price is None:
                continue
            brand_el = title_box.select_one("div span")
            brand = clean_text(brand_el.get_text()) if brand_el else ""
            model = clean_text(link.get_text(" "))
            img = item.select_one("meta[itemprop=image][content]")
            currency = item.select_one("meta[itemprop=priceCurrency]")
            season_icon = item.select_one(".product-details-container i.fa + span")
            season_text = season_icon.get_text() if season_icon else item.get_text(" ")[:3000]
            mpn = item.select_one("meta[itemprop=mpn]")
            offers.append(
                TyreOffer(
                    shop=self.name,
                    brand=display_brand(brand),
                    model=model,
                    size=spec.size,
                    season=season_from_text(season_text),
                    price=price,
                    currency=currency["content"] if currency else "EUR",
                    url=self.absolute(link["href"]),
                    image_url=img["content"] if img else None,
                    load_index=spec.load_index,
                    speed_index=spec.speed_index,
                    ean=None,
                    raw_title=f"{brand} {model} {mpn['content'] if mpn else ''}".strip(),
                )
            )
        return offers
