"""Web search engines and the candidate extractor."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from conftest import FakeHttp, load_fixture
from tyre_finder.data.promo.base import LookupContext, ShopRef
from tyre_finder.data.promo.dates import Freshness
from tyre_finder.data.promo.service import build_engines, filter_current
from tyre_finder.data.promo.settings import EngineChoice, PromoSettings
from tyre_finder.data.promo.websearch import (
    BingHtmlEngine,
    BraveEngine,
    DuckDuckGoHtmlEngine,
    EngineBlockedError,
    EngineError,
    GoogleCseEngine,
    SearchEngine,
    SearchHit,
    WebSearchSource,
    shop_queries,
)
from tyre_finder.models import Confidence

NOW = datetime(2026, 11, 23, 12, 0)
GUMI7 = ShopRef("gumi7", "Gumi7", "https://gumi7.com/bg/")


@pytest.fixture
def ctx() -> LookupContext:
    return LookupContext(http=None, today=NOW.date(), now=NOW, freshness=Freshness(30))  # type: ignore[arg-type]


def test_google_cse_parse() -> None:
    hits = GoogleCseEngine.parse(200, load_fixture("promo/synthetic_google_cse.json"))
    assert hits[0].url == "https://blog.example.bg/gumi7-promokod"
    assert hits[0].published == date(2026, 11, 10)
    assert hits[1].published is None
    with pytest.raises(EngineError, match="403"):
        GoogleCseEngine.parse(403, load_fixture("promo/synthetic_google_cse_error.json"))


def test_google_request_uses_date_restrict() -> None:
    seen: dict[str, object] = {}

    class Http(FakeHttp):
        def fetch(self, url, **kwargs):
            seen.update(kwargs.get("params") or {})
            return super().fetch(url)

    http = Http({GoogleCseEngine.endpoint: (200, '{"items": []}')})
    assert GoogleCseEngine("k", "cx").search(http, "q", 30) == []  # type: ignore[arg-type]
    assert seen["dateRestrict"] == "m1" and seen["cx"] == "cx" and seen["gl"] == "bg"


def test_brave_parse() -> None:
    hits = BraveEngine.parse(200, load_fixture("promo/synthetic_brave.json"))
    assert hits[0].snippet == "Ползвах промокод TIR5OFF в tirendo.bg за -5%"
    assert hits[0].published == date(2026, 11, 20)
    with pytest.raises(EngineError):
        BraveEngine.parse(401, "{}")


def test_keyless_engines_detect_blocking() -> None:
    with pytest.raises(EngineBlockedError):
        DuckDuckGoHtmlEngine.parse(202, load_fixture("promo/ddg_bot_challenge.html"))
    with pytest.raises(EngineBlockedError):
        BingHtmlEngine.parse(200, load_fixture("promo/bing_no_results.html"))


def test_keyless_engines_parse_results() -> None:
    ddg = DuckDuckGoHtmlEngine.parse(200, load_fixture("promo/synthetic_ddg_results.html"))
    assert ddg == [
        SearchHit(
            "Промокод Gumi7",
            "https://blog.example.bg/gumi7-promokod",
            "Gumi7 промокод: GUMI7WIN10 за 10% отстъпка",
        )
    ]
    bing = BingHtmlEngine.parse(200, load_fixture("promo/synthetic_bing_results.html"))
    assert bing[0].url == "https://blog.example.bg/gumi7-promokod"


def test_engine_order() -> None:
    names = [e.name for e in build_engines(PromoSettings())]
    assert names == ["Bing (без ключ)", "DuckDuckGo (без ключ)"]
    s = PromoSettings(google_api_key="k", google_cx="c", brave_api_key="b")
    assert [type(e).__name__ for e in build_engines(s)][:2] == ["GoogleCseEngine", "BraveEngine"]
    assert build_engines(PromoSettings(engine=EngineChoice.GOOGLE)) == []  # no key -> nothing
    assert build_engines(PromoSettings(engine=EngineChoice.OFF)) == []


def test_queries_mention_shop() -> None:
    qs = shop_queries(GUMI7)
    assert len(qs) == 2 and all("gumi7.com" in q for q in qs)
    assert "промокод" in qs[0]


def test_extract_page_scores_and_dates(ctx) -> None:
    src = WebSearchSource([])
    codes = src.extract_page(
        load_fixture("promo/synthetic_blog_page.html"),
        "https://blog.example.bg/x",
        GUMI7,
        ctx,
        None,
    )
    by_code = {c.code: c for c in codes}
    win = by_code["GUMI7WIN10"]
    assert win.discount_percent == 10.0
    assert win.valid_until == date(2026, 12, 15)
    assert win.published_at == date(2026, 11, 10)
    assert win.confidence is Confidence.HIGH and win.score >= 0.85
    kept, dropped = filter_current(codes, ctx.today, ctx.freshness)
    assert [c.code for c in kept] == ["GUMI7WIN10"]
    assert any("изтекъл" in reason for _, reason in dropped)  # SUMMER15 (31.08.2026)


def test_extract_old_page_without_expiry_dropped(ctx) -> None:
    codes = WebSearchSource([]).extract_page(
        load_fixture("promo/synthetic_blog_old.html"), "u", GUMI7, ctx, None
    )
    assert [c.code for c in codes] == ["OLDCODE7"]
    kept, dropped = filter_current(codes, ctx.today, ctx.freshness)
    assert kept == [] and "01.03.2026" in dropped[0][1]


def test_snippet_without_date_is_low_confidence(ctx) -> None:
    codes = WebSearchSource([]).extract(
        "Gumi7 промокод: ABC123", "u", GUMI7, ctx, date(2026, 11, 20)
    )
    assert codes[0].confidence is Confidence.LOW  # no discount -> score below threshold


class _Blocked(SearchEngine):
    name = "blocked"

    def search(self, http, query, fresh_days):
        raise EngineBlockedError("challenge")


class _Static(SearchEngine):
    name = "static"

    def search(self, http, query, fresh_days):
        return [SearchHit("Промокод Gumi7", "https://blog.example.bg/gumi7-promokod", "x")]


def test_lookup_falls_back_and_fetches_pages(ctx) -> None:
    http = FakeHttp(
        {
            "https://blog.example.bg/gumi7-promokod": (
                200,
                load_fixture("promo/synthetic_blog_page.html"),
            )
        }
    )
    ctx.http = http  # type: ignore[assignment]
    out = WebSearchSource([_Blocked(), _Static()]).lookup(GUMI7, ctx)
    assert "GUMI7WIN10" in {c.code for c in out.codes}
    assert any("блокирано" in c.outcome for c in out.checks)
    assert http.requested.count("https://blog.example.bg/gumi7-promokod") == 1


def test_all_engines_blocked_reported(ctx) -> None:
    ctx.http = FakeHttp({})  # type: ignore[assignment]
    out = WebSearchSource([_Blocked()]).lookup(GUMI7, ctx)
    assert out.codes == []
    assert any("Google API ключ" in c.outcome for c in out.checks)
