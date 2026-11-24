"""Медина-Мед (medina-med.com)."""

from __future__ import annotations

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.brands import display_brand
from tyre_finder.data.parsing import clean_text, parse_price, parse_size_spec, season_from_text
from tyre_finder.models import SearchQuery, Season, TyreOffer

_SEASON_PARAM = {Season.SUMMER: "summer", Season.WINTER: "winter", Season.ALL_SEASON: "allseason"}


class MedinaMedScraper(TyreScraper):
    """Parses ``.med-result-col-item-h`` / ``-v`` cards."""

    name = "Медина-Мед"
    home_url = "https://medina-med.com/"

    def build_url(self, query: SearchQuery, page: int) -> str | None:
        s = query.size
        url = (
            f"https://medina-med.com/katalog-gumi/?season_id={_SEASON_PARAM[query.season]}"
            f"&width={s.width}&height={s.profile}&rim={s.rim}"
        )
        return url if page == 1 else f"{url}&p={page}"

    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        soup = self.soup(html)
        offers: list[TyreOffer] = []
        for card in soup.select("div.med-result-col-item-h, div.med-result-col-item-v"):
            link = card.select_one("a[href] h6")
            info = card.select_one(".med-result-col-item-desc-info")
            price_el = card.select_one(".med-result-col-item-price-total .Price[data-price]")
            if not (link and info and price_el):
                continue
            title = clean_text(link.get_text(" "))
            spec = parse_size_spec(title)
            price = parse_price(price_el["data-price"])
            if spec is None or price is None:
                continue
            brand, _, model = clean_text(info.get_text(" ")).partition("|")
            img = card.select_one("a.product-image-wrapper img")
            size_el = card.select_one(".med-result-col-item-desc-size")
            offers.append(
                TyreOffer(
                    shop=self.name,
                    brand=display_brand(brand.strip()),
                    model=model.strip(),
                    size=spec.size,
                    season=season_from_text(size_el.get_text()) if size_el else None,
                    price=price,
                    currency="EUR",
                    url=self.absolute(link.parent.get("href")),
                    image_url=self.absolute(img.get("src")) if img else None,
                    load_index=spec.load_index,
                    speed_index=spec.speed_index,
                    raw_title=title,
                )
            )
        return offers
