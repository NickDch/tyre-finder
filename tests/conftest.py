from __future__ import annotations

from pathlib import Path

import pytest

from tyre_finder.data.http import Fetched, error_for_status
from tyre_finder.models import SearchQuery, Season, TyreSize

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def summer_query() -> SearchQuery:
    return SearchQuery(TyreSize(205, 55, 16), Season.SUMMER)


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


PROMO = "promo/"


class FakeHttp:
    """Stand-in for HttpClient: URL -> (status, body, final_url)."""

    def __init__(self, pages: dict[str, tuple[int, str] | tuple[int, str, str]]) -> None:
        self.pages = pages
        self.requested: list[str] = []
        self.warmed: list[str] = []
        self.referers: list[str | None] = []

    def fetch(self, url: str, **_kwargs: object):
        self.requested.append(url)
        entry = self.pages.get(url, (404, ""))
        final = entry[2] if len(entry) == 3 else url
        return Fetched(entry[0], final, entry[1])

    def warm_up(self, home_url: str) -> None:
        self.warmed.append(home_url)

    def get_text(self, url: str, *, referer: str | None = None) -> str:
        self.referers.append(referer)
        res = self.fetch(url)
        if res.status >= 400:
            raise error_for_status(res, "test")
        return res.text

    def close(self) -> None:
        pass
