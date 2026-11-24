"""Common abstract interface for all shop scrapers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from tyre_finder.data.http import FetchError, HttpClient
from tyre_finder.models import SearchQuery, TyreOffer

log = logging.getLogger(__name__)


class TyreScraper(ABC):
    """Base class for one online shop.

    Subclasses implement :meth:`build_url` and :meth:`parse`; :meth:`search`
    handles pagination, de-duplication and the final size/season filtering.
    """

    #: Display name of the shop.
    name: str = ""
    #: Home page of the shop.
    home_url: str = ""
    #: Visit the home page once before searching (collects session cookies).
    warm_up: bool = False

    def __init__(self, max_pages: int = 2) -> None:
        self.max_pages = max_pages

    @abstractmethod
    def build_url(self, query: SearchQuery, page: int) -> str | None:
        """Return the search URL for *page* (1-based) or None if unsupported."""

    @abstractmethod
    def parse(self, html: str, query: SearchQuery) -> list[TyreOffer]:
        """Parse a result page into offers."""

    def absolute(self, href: str | None) -> str:
        """Resolve a relative link against the shop home URL."""
        return urljoin(self.home_url, href or "")

    @staticmethod
    def soup(html: str) -> BeautifulSoup:
        """Parse HTML with lxml."""
        return BeautifulSoup(html, "lxml")

    def search(self, client: HttpClient, query: SearchQuery) -> list[TyreOffer]:
        """Run the search on this shop and return matching offers."""
        offers: list[TyreOffer] = []
        seen: set[str] = set()
        referer = self.home_url or None
        if self.warm_up and self.home_url:
            client.warm_up(self.home_url)
        for page in range(1, self.max_pages + 1):
            url = self.build_url(query, page)
            if url is None:
                break
            try:
                html = client.get_text(url, referer=referer)
            except FetchError as exc:
                if page == 1:
                    raise
                # A failing extra page must not throw away what we already have.
                log.warning("%s: page %d failed (%s); keeping page 1 results", self.name, page, exc)
                break
            page_offers = self.parse(html, query)
            new = [o for o in page_offers if o.url not in seen]
            log.info(
                "%s: page %d -> %d offers (%d new)", self.name, page, len(page_offers), len(new)
            )
            if not new:
                break
            for offer in new:
                seen.add(offer.url)
            offers.extend(new)
        return self.filter_matching(offers, query)

    @staticmethod
    def filter_matching(offers: list[TyreOffer], query: SearchQuery) -> list[TyreOffer]:
        """Drop offers whose size or (known) season does not match the query."""
        return [
            o
            for o in offers
            if o.size == query.size
            and (o.season is None or o.season == query.season)
            and o.price > 0
        ]
