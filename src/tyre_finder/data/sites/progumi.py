"""ProGumi.bg."""

from __future__ import annotations

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.brands import display_brand, split_brand_model
from tyre_finder.data.parsing import clean_text, parse_price, parse_size_spec, season_from_text
from tyre_finder.models import SearchQuery, Season, TyreOffer

_SEASON_PARAM = {Season.SUMMER: "summer", Season.WINTER: "winter", Season.ALL_SEASON: "all-season"}


class ProGumiScraper(TyreScraper):
    """Parses ``.catalog-products__item`` cards."""

    name = "ProGumi"
    home_url = "https://progumi.bg/"

    def build_url(self, query: SearchQuery, page: int) -> str | None:
        s = query.size
        url = (
            "https://progumi.bg/bg/avtomobilni-gumi"
            f"?tire-season={_SEASON_PARAM[query.season]}"
            f"&tire-width={s.width}&tire-height={s.profile}&tire-diameter={s.rim}"
        )
        return url if page == 1 else f"{url}&page={page}"

    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        soup = self.soup(html)
        offers: list[TyreOffer] = []
        for card in soup.select(".catalog-products__item .pw-card"):
            link = card.select_one(".pw-product-title a")
            desc = card.select_one(".pw-product-description")
            price_el = card.select_one(".pw-product-price .price")
            if not (link and desc and price_el):
                continue
            spec = parse_size_spec(desc.get_text(" "))
            price = parse_price(price_el.get_text("", strip=True).replace("EUR", ""))
            if spec is None or price is None:
                continue
            title = clean_text(link.get("title") or link.get_text(" "))
            brand, model = split_brand_model(title)
            img = card.select_one(".pw-cover img")
            image = img.get("data-src") or img.get("src") if img else None
            icon = card.select_one(".pw-product-icon span")
            offers.append(
                TyreOffer(
                    shop=self.name,
                    brand=display_brand(brand),
                    model=model,
                    size=spec.size,
                    season=season_from_text(icon.get_text()) if icon else None,
                    price=price,
                    currency="EUR",
                    url=self.absolute(link.get("href")),
                    image_url=self.absolute(image) if image else None,
                    load_index=spec.load_index,
                    speed_index=spec.speed_index,
                    raw_title=title,
                )
            )
        return offers
