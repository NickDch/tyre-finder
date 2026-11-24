"""Gumi7.com - product tiles carry a JSON blob with all data."""

from __future__ import annotations

import json
import logging

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.brands import display_brand
from tyre_finder.data.parsing import parse_size_spec
from tyre_finder.models import SearchQuery, Season, TyreOffer

log = logging.getLogger(__name__)

_SEASON_PARAM = {Season.SUMMER: "summer", Season.WINTER: "winter", Season.ALL_SEASON: "all"}
_PARAM_SEASON = {
    "summer": Season.SUMMER,
    "winter": Season.WINTER,
    "all": Season.ALL_SEASON,
    "all_season": Season.ALL_SEASON,
    "allseason": Season.ALL_SEASON,
}


class Gumi7Scraper(TyreScraper):
    """Parses ``div.product-tile[data-product]`` JSON."""

    name = "Gumi7"
    home_url = "https://gumi7.com/bg/"
    #: Behind Cloudflare: visit the home page first like a normal visitor.
    warm_up = True

    def build_url(self, query: SearchQuery, page: int) -> str | None:
        s = query.size
        url = (
            "https://gumi7.com/bg/avtomobilni-gumi/"
            f"?width={s.width}&height={s.profile}&diameter={s.rim}"
            f"&tire_season={_SEASON_PARAM[query.season]}"
        )
        return url if page == 1 else f"{url}&page={page}"

    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        soup = self.soup(html)
        offers: list[TyreOffer] = []
        for tile in soup.select("div.product-tile[data-product]"):
            try:
                data = json.loads(tile["data-product"])
                price = float(data["price"])
            except (KeyError, ValueError, TypeError) as exc:
                log.debug("Gumi7: bad tile JSON: %s", exc)
                continue
            spec = parse_size_spec(str(data.get("dimensions", "")))
            if spec is None:
                continue
            offers.append(
                TyreOffer(
                    shop=self.name,
                    brand=display_brand(str(data.get("brand", ""))),
                    model=str(data.get("model", "")).strip(),
                    size=spec.size,
                    season=_PARAM_SEASON.get(str(data.get("season", ""))),
                    price=price,
                    currency="EUR",
                    url=str(data.get("url", "")),
                    image_url=data.get("image") or None,
                    load_index=spec.load_index,
                    speed_index=spec.speed_index,
                    raw_title=str(data.get("beauty_name", "")),
                    badges=tuple(
                        " ".join(r.get_text(" ").split()) for r in tile.select(".product-roundel")
                    ),
                )
            )
        return offers
