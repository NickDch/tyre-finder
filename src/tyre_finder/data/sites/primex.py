"""Примекс (primex-bg.com) - importer with a national service network."""

from __future__ import annotations

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.brands import display_brand
from tyre_finder.data.parsing import clean_text, parse_price, parse_size_spec
from tyre_finder.models import SearchQuery, Season, TyreOffer

_SEASON_PARAM = {Season.SUMMER: "summer", Season.WINTER: "winter", Season.ALL_SEASON: "all-season"}
_CLASS_SEASON = {v: k for k, v in _SEASON_PARAM.items()}


class PrimexScraper(TyreScraper):
    """Primex lists all results of the size on a single page."""

    name = "Примекс"
    home_url = "https://primex-bg.com/"

    def build_url(self, query: SearchQuery, page: int) -> str | None:
        if page > 1:
            return None
        s = query.size
        return (
            "https://primex-bg.com/spisak-produkti.html"
            f"?width={s.width}&ratio={s.profile}&rim={s.rim}&breadcrumb=search"
            f"&order=suggest&season[{_SEASON_PARAM[query.season]}]=1"
        )

    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        soup = self.soup(html)
        offers: list[TyreOffer] = []
        for art in soup.select("article[data-id][data-price]"):
            spec = parse_size_spec(art.get("data-variant", ""))
            price = parse_price(art.get("data-price", ""))
            if spec is None or price is None:
                continue
            season = None
            for a in art.select("p.attribute a[class]"):
                for cls in a.get("class", []):
                    season = season or _CLASS_SEASON.get(cls)
            img = art.select_one("a.img img")
            offers.append(
                TyreOffer(
                    shop=self.name,
                    brand=display_brand(art.get("data-brand", "")),
                    model=clean_text(art.get("data-name")),
                    size=spec.size,
                    season=season,
                    price=price,
                    currency="EUR",
                    url=art.get("data-url", ""),
                    image_url=self.absolute(img.get("src")) if img else None,
                    load_index=spec.load_index,
                    speed_index=spec.speed_index,
                    raw_title=f"{art.get('data-brand', '')} {art.get('data-name', '')}",
                )
            )
        return offers
