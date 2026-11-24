from __future__ import annotations

import threading

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.http import FetchError, HttpClient
from tyre_finder.logic.search import SearchOrchestrator
from tyre_finder.models import SearchQuery, Season, SiteStatusKind, TyreOffer, TyreSize


class FakeScraper(TyreScraper):
    def __init__(
        self, name: str, offers: list[TyreOffer] | None = None, error: Exception | None = None
    ) -> None:
        super().__init__()
        self.name = name
        self._offers = offers or []
        self._error = error

    def build_url(self, query, page):
        return None

    def parse(self, html, query):
        return []

    def search(self, client: HttpClient, query: SearchQuery) -> list[TyreOffer]:
        if self._error:
            raise self._error
        return self._offers


def test_one_failing_site_does_not_break_others(summer_query) -> None:
    good = TyreOffer(
        "ok", "Sava", "Intensa", TyreSize(205, 55, 16), Season.SUMMER, 50.0, "EUR", "https://ok/1"
    )
    scrapers = [
        FakeScraper("ok", [good]),
        FakeScraper("net", error=FetchError("HTTP 511")),
        FakeScraper("bug", error=ValueError("boom")),
        FakeScraper("empty"),
    ]
    seen: list[str] = []
    results = SearchOrchestrator(scrapers).run(summer_query, lambda r: seen.append(r.shop))
    by_shop = {r.shop: r for r in results}
    assert by_shop["ok"].status is SiteStatusKind.OK
    assert by_shop["net"].status is SiteStatusKind.ERROR
    assert "511" in by_shop["net"].message
    assert by_shop["bug"].status is SiteStatusKind.ERROR
    assert by_shop["empty"].status is SiteStatusKind.EMPTY
    assert sorted(seen) == ["bug", "empty", "net", "ok"]


def test_cancel_before_start(summer_query) -> None:
    class NetScraper(FakeScraper):
        def search(self, client, query):
            return [o for o in [client.get_text("https://example.invalid/")]]  # pragma: no cover

    cancel = threading.Event()
    cancel.set()
    results = SearchOrchestrator([NetScraper("x")]).run(summer_query, cancel_event=cancel)
    assert results[0].status is SiteStatusKind.CANCELLED
