"""PromoService: parallel lookup, freshness filter, cache, manual codes, settings."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from tyre_finder.data.promo.base import (
    LookupContext,
    PromoSource,
    ShopRef,
    SourceCheck,
    SourceOutput,
)
from tyre_finder.data.promo.service import PromoService, ShopPromoRequest
from tyre_finder.data.promo.settings import EngineChoice, PromoSettings, PromoSettingsStore
from tyre_finder.data.promo.store import ManualPromo, PromoCache, promo_from_dict, promo_to_dict
from tyre_finder.data.site_config import SiteStore, default_sites
from tyre_finder.models import Confidence, PromoCode, PromoOrigin

NOW = datetime(2026, 11, 23, 12)
SHOP = ShopRef("a", "A", "https://a.bg/")


class CountingSource(PromoSource):
    label = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def applies_to(self, shop: ShopRef) -> bool:
        return True

    def lookup(self, shop: ShopRef, ctx: LookupContext) -> SourceOutput:
        self.calls += 1
        mk = lambda code, **kw: PromoCode(  # noqa: E731
            shop.name, code, code, PromoOrigin.AGGREGATOR, "u", ctx.now, discount_percent=5, **kw
        )
        return SourceOutput(
            [
                mk("FRESH", valid_until=date(2026, 12, 1)),
                mk("OLD", valid_until=date(2026, 10, 1)),
                mk("NODATE"),
                mk("RECENT", published_at=date(2026, 11, 15)),
                mk("FRESH", valid_until=date(2026, 12, 1), confidence=Confidence.LOW),
            ],
            [SourceCheck("fake", "u", "ok")],
        )


class _NoHttp:
    def close(self) -> None:
        pass


def service(tmp_path, source: PromoSource) -> PromoService:
    return PromoService(
        PromoSettings(),
        cache=PromoCache(tmp_path / "c.json", ttl=timedelta(hours=6)),
        sources=[source],
        http_factory=lambda _ev: _NoHttp(),  # type: ignore[arg-type, return-value]
    )


def test_filter_and_dedupe(tmp_path) -> None:
    src = CountingSource()
    res = service(tmp_path, src).lookup([ShopPromoRequest(SHOP)], now=NOW)["A"]
    assert sorted(c.code for c in res.codes) == ["FRESH", "RECENT"]
    assert next(c for c in res.codes if c.code == "FRESH").confidence is Confidence.HIGH
    assert {c.code for c, _ in res.dropped} == {"OLD", "NODATE"}


def test_cache_hit_and_expiry(tmp_path) -> None:
    src = CountingSource()
    svc = service(tmp_path, src)
    svc.lookup([ShopPromoRequest(SHOP)], now=NOW)
    res = svc.lookup([ShopPromoRequest(SHOP)], now=NOW + timedelta(hours=2))["A"]
    assert src.calls == 1 and res.from_cache
    svc.lookup([ShopPromoRequest(SHOP)], now=NOW + timedelta(hours=7))
    assert src.calls == 2
    svc.lookup([ShopPromoRequest(SHOP)], now=NOW + timedelta(hours=7), use_cache=False)
    assert src.calls == 3


def test_manual_codes_added_and_expired_ones_dropped(tmp_path) -> None:
    manual = [
        ManualPromo(code="MINE10", discount_percent=10),
        ManualPromo(code="GONE", discount_percent=5, valid_until="2026-11-01"),
        ManualPromo(code="OFF", discount_percent=5, enabled=False),
    ]
    res = service(tmp_path, CountingSource()).lookup([ShopPromoRequest(SHOP, manual)], now=NOW)["A"]
    assert "MINE10" in {c.code for c in res.codes}
    assert "GONE" in {c.code for c, _ in res.dropped}
    assert "OFF" not in {c.code for c in res.codes}


def test_promo_roundtrip() -> None:
    p = PromoCode(
        "A",
        "X",
        "t",
        PromoOrigin.WEB,
        "u",
        NOW,
        discount_percent=5.0,
        brands=("NOKIAN",),
        valid_until=date(2026, 12, 1),
        confidence=Confidence.LOW,
        score=0.4,
    )
    assert promo_from_dict(json.loads(json.dumps(promo_to_dict(p)))) == p


def test_settings_store_roundtrip_and_tolerance(tmp_path) -> None:
    store = PromoSettingsStore(tmp_path / "p.json")
    assert store.load() == PromoSettings()
    s = PromoSettings(engine=EngineChoice.GOOGLE, google_api_key="k", google_cx="c", window_days=14)
    store.save(s)
    assert store.load() == s
    assert (tmp_path / "p.json").stat().st_mode & 0o077 == 0
    (tmp_path / "p.json").write_text('{"engine": "nope", "window_days": "x", "extra": 1}')
    assert store.load() == PromoSettings()
    assert "k" not in PromoSettings(google_api_key="k", google_cx="c").signature()


def test_manual_promos_persist_with_sites(tmp_path) -> None:
    store = SiteStore(tmp_path / "sites.json")
    sites = default_sites()
    sites[0].manual_promos = [ManualPromo(code="EMAG5", discount_percent=5, brands=["Nokian"])]
    store.save(sites)
    loaded = store.load()
    assert loaded[0].manual_promos == sites[0].manual_promos
    assert loaded[1].manual_promos == []
    bad = default_sites()
    bad[0].manual_promos = [ManualPromo(code="", discount_percent=150)]
    assert bad[0].validate()
