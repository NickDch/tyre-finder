"""SuperGumi.bg - 100 000+ offers.

The shop's SEO landing pages (``/gumi/letni/235-50-18``) exist only for some
size/season combinations and answer HTTP 404 for the rest, so we use the URL
the site's own search form (``form#tires-form``, ``action="eshop/search"``)
submits.  Its ``season`` values are 1 = winter, 2 = summer, 3 = all-season.
"""

from __future__ import annotations

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.brands import display_brand, split_brand_model
from tyre_finder.data.parsing import clean_text, parse_price, parse_size_spec, season_from_text
from tyre_finder.models import SearchQuery, Season, TyreOffer

#: ``<select name="season">`` values of the site's ``#tires-form``.
_SEASON_ID = {Season.WINTER: 1, Season.SUMMER: 2, Season.ALL_SEASON: 3}
#: ``<select name="type">``: 1 = "Автомобили и Джипове".
_TYPE_CARS = 1


class SuperGumiScraper(TyreScraper):
    """Parses ``.products-list .card`` items."""

    name = "SuperGumi"
    home_url = "https://www.supergumi.bg/"

    def build_url(self, query: SearchQuery, page: int) -> str | None:
        s = query.size
        url = (
            f"https://www.supergumi.bg/eshop/search?type={_TYPE_CARS}"
            f"&width={s.width}&height={s.profile}&inch={s.rim}"
            f"&season={_SEASON_ID[query.season]}"
        )
        return url if page == 1 else f"{url}&page={page}"

    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        soup = self.soup(html)
        offers: list[TyreOffer] = []
        for card in soup.select(".products-list .card"):
            link = card.select_one(".pr-info h2 a")
            size_el = card.select_one(".pr-info .btn-l-red")
            price_el = card.select_one(".pr-actions big")
            if not (link and size_el and price_el):
                continue
            spec = parse_size_spec(size_el.get_text(" "))
            price = parse_price(price_el.get_text(" "))
            if spec is None or price is None:
                continue
            title = clean_text(link.get("title") or link.get_text(" "))
            brand_img = card.select_one(".pr-brand img")
            brand_alt = clean_text(brand_img.get("alt")) if brand_img else ""
            if brand_alt and title.upper().startswith(brand_alt.upper()):
                brand, model = brand_alt, title[len(brand_alt) :].strip()
            else:
                brand, model = split_brand_model(title)
            img = card.select_one("img.pr-thumb")
            season_el = card.select_one(".pr-season")
            offers.append(
                TyreOffer(
                    shop=self.name,
                    brand=display_brand(brand),
                    model=model,
                    size=spec.size,
                    season=season_from_text(season_el.get_text()) if season_el else None,
                    price=price,
                    currency="EUR",
                    url=self.absolute(link.get("href")),
                    image_url=self.absolute(img.get("src")) if img else None,
                    load_index=spec.load_index,
                    speed_index=spec.speed_index,
                    raw_title=title,
                )
            )
        return offers
