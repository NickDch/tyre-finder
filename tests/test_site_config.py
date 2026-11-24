from __future__ import annotations

import json

import pytest

from tyre_finder.data.site_config import (
    SiteConfig,
    SiteConfigError,
    SiteKind,
    SiteStore,
    build_scraper,
    default_sites,
)
from tyre_finder.data.sites.generic import GenericSelectors, GenericSiteSpec
from tyre_finder.data.sites.nk_platform import NkPlatformScraper


def test_defaults_are_twelve_valid_sites() -> None:
    sites = default_sites()
    assert len(sites) == 12
    assert {"bggumi", "medinamed", "emag"} <= {s.id for s in sites}
    for site in sites:
        assert site.validate() == []
        assert build_scraper(site).name == site.name


def test_missing_file_gives_defaults(tmp_path) -> None:
    store = SiteStore(tmp_path / "sites.json")
    assert [s.id for s in store.load()] == [s.id for s in default_sites()]


def test_corrupt_file_gives_defaults(tmp_path) -> None:
    path = tmp_path / "sites.json"
    path.write_text("{not json", encoding="utf-8")
    assert len(SiteStore(path).load()) == 12


def test_roundtrip_with_custom_sites(tmp_path) -> None:
    store = SiteStore(tmp_path / "cfg" / "sites.json")
    sites = default_sites()
    sites[0].enabled = False
    sites = [s for s in sites if s.id != "gumi3"]
    sites.append(SiteConfig("gumi3b", "Gumi3 копие", SiteKind.NK, "https://www.gumi3.com/"))
    sites.append(
        SiteConfig(
            "my",
            "Моят магазин",
            SiteKind.GENERIC,
            "https://shop.example.bg/",
            generic=GenericSiteSpec(
                search_url="https://shop.example.bg/s?w={width}&h={profile}&r={rim}&s={season}",
                season_values={"summer": "1", "winter": "2", "all_season": "3"},
                selectors=GenericSelectors(item="div.p", title="h2", price=".price", link="a@href"),
            ),
        )
    )
    store.save(sites)
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    loaded = store.load()
    assert [s.id for s in loaded] == [s.id for s in sites]
    assert loaded[0].enabled is False
    assert loaded[-1].generic == sites[-1].generic
    assert isinstance(build_scraper(loaded[-2]), NkPlatformScraper)


def test_save_rejects_invalid_and_duplicates(tmp_path) -> None:
    store = SiteStore(tmp_path / "sites.json")
    bad = SiteConfig("x", "", SiteKind.NK, "not-a-url")
    with pytest.raises(SiteConfigError):
        store.save([bad])
    dup = default_sites()[:2]
    dup[1].id = dup[0].id
    with pytest.raises(SiteConfigError):
        store.save(dup)
    assert not store.path.exists()


def test_reset_restores_defaults(tmp_path) -> None:
    store = SiteStore(tmp_path / "sites.json")
    store.save(default_sites()[:3])
    assert len(store.load()) == 3
    assert len(store.reset()) == 12
    assert len(store.load()) == 12


def test_validation_messages() -> None:
    site = SiteConfig(
        "g",
        "G",
        SiteKind.GENERIC,
        "https://g.bg/",
        generic=GenericSiteSpec(search_url="https://g.bg/?w={width}"),
    )
    errors = " ".join(site.validate())
    assert "{profile}" in errors and "{rim}" in errors
    assert "item" in errors
