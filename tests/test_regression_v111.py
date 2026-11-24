"""Regressions for v1.1.1: SuperGumi HTTP 404 and Gumi7 HTTP 403 (235/50 R18)."""

from __future__ import annotations

import httpx
import pytest

from conftest import FakeHttp, load_fixture
from tyre_finder.data.http import (
    USER_AGENT,
    BlockedError,
    Fetched,
    HttpClient,
    NotFoundError,
    error_for_status,
    is_challenge_page,
)
from tyre_finder.data.site_config import build_scraper, default_sites
from tyre_finder.logic.search import SearchOrchestrator
from tyre_finder.models import SearchQuery, Season, SiteStatusKind, TyreSize

SIZE = TyreSize(235, 50, 18)
SITES = {site.id: site for site in default_sites()}
SG_BASE = "https://www.supergumi.bg/eshop/search?type=1&width=235&height=50&inch=18"


@pytest.mark.parametrize(
    ("season", "season_id"),
    [(Season.WINTER, 1), (Season.SUMMER, 2), (Season.ALL_SEASON, 3)],
)
def test_supergumi_uses_search_form_url_for_every_season(season: Season, season_id: int) -> None:
    scraper = build_scraper(SITES["supergumi"])
    query = SearchQuery(SIZE, season)
    assert scraper.build_url(query, 1) == f"{SG_BASE}&season={season_id}"
    assert scraper.build_url(query, 2) == f"{SG_BASE}&season={season_id}&page=2"


def test_supergumi_parses_real_search_result_for_235_50_18() -> None:
    query = SearchQuery(SIZE, Season.SUMMER)
    scraper = build_scraper(SITES["supergumi"])
    offers = scraper.parse(load_fixture("supergumi_235_50_18_summer_search.html"), query)
    assert len(offers) == 24
    assert all(o.size == SIZE and o.season is Season.SUMMER and o.price > 0 for o in offers)


def test_supergumi_old_seo_404_is_reported_as_not_found() -> None:
    """The old /gumi/letni/235-50-18 URL is a real 404 page on the site."""
    fetched = Fetched(
        404,
        "https://www.supergumi.bg/gumi/letni/235-50-18",
        load_fixture("supergumi_235_50_18_letni_404.html"),
    )
    err = error_for_status(fetched, "www.supergumi.bg")
    assert isinstance(err, NotFoundError)
    assert "не е намерена" in err.short
    assert "сменил адресите" in str(err)


def test_page_two_failure_keeps_page_one_results() -> None:
    query = SearchQuery(SIZE, Season.SUMMER)
    http = FakeHttp(
        {f"{SG_BASE}&season=2": (200, load_fixture("supergumi_235_50_18_summer_search.html"))}
    )  # page 2 -> 404
    offers = build_scraper(SITES["supergumi"]).search(http, query)  # type: ignore[arg-type]
    assert len(offers) == 24
    assert http.requested[-1].endswith("&page=2")


def test_page_one_404_is_clear_error_in_orchestrator() -> None:
    query = SearchQuery(SIZE, Season.SUMMER)
    http = FakeHttp({})
    result = SearchOrchestrator._run_one(build_scraper(SITES["supergumi"]), http, query)  # type: ignore[arg-type]
    assert result.status is SiteStatusKind.ERROR
    assert result.message.startswith("Страницата не е намерена (HTTP 404)")
    assert "сменил адресите" in result.detail


def test_cloudflare_challenge_detected_from_real_page() -> None:
    html = load_fixture("cloudflare_challenge.html")
    assert is_challenge_page(403, html)
    assert is_challenge_page(200, "", {"cf-mitigated": "challenge"})
    assert not is_challenge_page(403, "<html>Forbidden</html>")
    assert not is_challenge_page(200, load_fixture("gumi7_205_55_16_summer.html"))


def test_gumi7_challenge_gives_blocked_message_and_warms_up() -> None:
    query = SearchQuery(SIZE, Season.SUMMER)
    scraper = build_scraper(SITES["gumi7"])
    url = scraper.build_url(query, 1)
    assert url is not None
    http = FakeHttp({url: (403, load_fixture("cloudflare_challenge.html"))})
    result = SearchOrchestrator._run_one(scraper, http, query)  # type: ignore[arg-type]
    assert http.warmed == ["https://gumi7.com/bg/"]
    assert http.referers[0] == "https://gumi7.com/bg/"
    assert result.status is SiteStatusKind.ERROR
    assert result.message == "Блокиран достъп: Cloudflare JavaScript проверка"
    assert "не заобикаля" in result.detail


def test_plain_403_and_captcha_are_blocked_errors() -> None:
    err = error_for_status(Fetched(403, "u", "<html>no</html>"), "gumi7.com")
    assert isinstance(err, BlockedError) and not err.challenge
    assert err.short == "Блокиран достъп (HTTP 403)"
    assert isinstance(error_for_status(Fetched(511, "u", ""), "x"), BlockedError)


def _mock_client(handler) -> HttpClient:
    client = HttpClient(min_interval_s=0.0)
    client._client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return client


def test_http_client_retries_plain_403_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(403 if len(calls) == 1 else 200, text="<html>ok</html>")

    client = _mock_client(handler)
    monkeypatch.setattr(client.cancel_event, "wait", lambda _t: False)
    assert (
        client.get_text("https://gumi7.com/x", referer="https://gumi7.com/bg/") == "<html>ok</html>"
    )
    assert len(calls) == 2
    assert calls[0].headers["Referer"] == "https://gumi7.com/bg/"


def test_http_client_does_not_retry_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[httpx.Request] = []
    body = load_fixture("cloudflare_challenge.html")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(403, text=body, headers={"cf-mitigated": "challenge"})

    client = _mock_client(handler)
    monkeypatch.setattr(client.cancel_event, "wait", lambda _t: False)
    with pytest.raises(BlockedError) as info:
        client.get_text("https://gumi7.com/x")
    assert info.value.challenge
    assert len(calls) == 1


def test_warm_up_happens_once_per_host() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="home", headers={"set-cookie": "ftssid=1; path=/"})

    client = _mock_client(handler)
    client.warm_up("https://gumi7.com/bg/")
    client.warm_up("https://gumi7.com/bg/")
    assert calls == ["https://gumi7.com/bg/"]


def test_user_agent_is_a_plain_browser_identity() -> None:
    assert "TyreFinder" not in USER_AGENT
    assert USER_AGENT.startswith("Mozilla/5.0")
