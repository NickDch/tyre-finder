from __future__ import annotations

import pytest

from conftest import load_fixture
from tyre_finder.data.sites.generic import (
    GenericConfigError,
    GenericScraper,
    GenericSelectors,
    GenericSiteSpec,
)
from tyre_finder.models import SearchQuery, Season, TyreSize


def bggumi_spec() -> GenericSiteSpec:
    return GenericSiteSpec(
        search_url=(
            "https://www.bggumi.com/eshop/search?type=1&width={width}&height={profile}"
            "&inch={rim}&season={season}"
        ),
        page_suffix="&page={page}",
        season_values={"summer": "2", "winter": "1", "all_season": "3"},
        selectors=GenericSelectors(
            item="div.list div.product",
            title="h2 a",
            price=".price",
            link="h2 a@href",
            image="a.thumb img@src",
            size=".sizes",
        ),
    )


def test_generic_build_url() -> None:
    scraper = GenericScraper("BG", "https://www.bggumi.com/", bggumi_spec())
    q = SearchQuery(TyreSize(225, 45, 17), Season.WINTER)
    assert scraper.build_url(q, 1) == (
        "https://www.bggumi.com/eshop/search?type=1&width=225&height=45&inch=17&season=1"
    )
    assert scraper.build_url(q, 2).endswith("&season=1&page=2")


def test_generic_parses_real_page(summer_query) -> None:
    scraper = GenericScraper("BG", "https://www.bggumi.com/", bggumi_spec())
    offers = scraper.parse(load_fixture("bggumi_205_55_16_summer.html"), summer_query)
    assert len(offers) == 25
    first = offers[0]
    assert (first.brand, first.model, first.price) == ("Landspider", "EUROTRAXX H/P", 38.5)
    assert first.url == "https://www.bggumi.com/eshop/productinfo/1/3007013345192384/"
    assert first.image_url.endswith("thumb_50818_eurotraxxh_p.jpg")
    assert first.season is Season.SUMMER
    assert first.currency == "EUR"


def test_generic_without_pagination_has_one_page(summer_query) -> None:
    spec = bggumi_spec()
    spec.page_suffix = ""
    scraper = GenericScraper("BG", "https://www.bggumi.com/", spec, max_pages=5)
    assert scraper.max_pages == 1
    assert scraper.build_url(summer_query, 2) is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: setattr(s, "search_url", "ftp://x/{width}{profile}{rim}"),
        lambda s: setattr(s, "search_url", "https://x/?w={width}"),
        lambda s: setattr(s, "page_suffix", "&p=2"),
        lambda s: s.season_values.update(winter=""),
        lambda s: setattr(s.selectors, "item", ""),
        lambda s: setattr(s, "search_url", "https://x/{width}/{profile}/{rim}/{foo}"),
    ],
)
def test_generic_validation(mutate) -> None:
    spec = bggumi_spec()
    mutate(spec)
    assert spec.validate()
    with pytest.raises(GenericConfigError):
        GenericScraper("X", "https://x.bg/", spec)
