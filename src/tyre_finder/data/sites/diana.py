"""Гуми Диана (diana-ltd.com)."""

from __future__ import annotations

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.brands import display_brand
from tyre_finder.data.parsing import clean_text, parse_load_speed, parse_price, parse_size_spec
from tyre_finder.models import SearchQuery, Season, TyreOffer

_SEASON_CODE = {Season.SUMMER: "1", Season.WINTER: "2", Season.ALL_SEASON: "3"}
_CODE_SEASON = {v: k for k, v in _SEASON_CODE.items()}


class DianaScraper(TyreScraper):
    """Diana renders all results of a size on one page."""

    name = "Гуми Диана"
    home_url = "https://diana-ltd.com/"

    def build_url(self, query: SearchQuery, page: int) -> str | None:
        if page > 1:
            return None
        s = query.size
        return (
            "https://diana-ltd.com/tires?mv_type=1"
            f"&tire_type[]={_SEASON_CODE[query.season]}"
            f"&width={s.width}&aspect_ratio={s.profile}&diameter={s.rim}"
        )

    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        soup = self.soup(html)
        offers: list[TyreOffer] = []
        seen: set[str] = set()
        for box in soup.select("div.jq-tyresList[data-id]"):
            item_id = box["data-id"]
            if item_id in seen:
                continue
            seen.add(item_id)
            model_el = box.select_one(".g-model a")
            size_el = box.select_one(".g-num")
            price_el = box.select_one(".g-price-wrap .price")
            if not (model_el and size_el and price_el):
                continue
            spec = parse_size_spec(size_el.get_text(" "))
            price = parse_price(price_el.get_text("", strip=True).replace("€", ""))
            if spec is None or price is None:
                continue
            logo = box.select_one(".g-name img")
            brand = clean_text(logo.get("alt")) if logo else ""
            full = clean_text(model_el.get_text(" "))
            li, si = parse_load_speed(full)
            model = full
            if brand and model.upper().startswith(brand.upper()):
                model = model[len(brand) :].strip()
            if li and si and model.endswith(f"{li}{si}"):
                model = model[: -len(f"{li}{si}")].strip()
            img = box.select_one("figure img")
            offers.append(
                TyreOffer(
                    shop=self.name,
                    brand=display_brand(brand or model.split()[0]),
                    model=model,
                    size=spec.size,
                    season=_CODE_SEASON.get(box.get("data-tire-type", "")),
                    price=price,
                    currency="EUR",
                    url=self.absolute(model_el.get("href")),
                    image_url=self.absolute(img.get("src")) if img else None,
                    load_index=li,
                    speed_index=si,
                    raw_title=full,
                )
            )
        return offers
