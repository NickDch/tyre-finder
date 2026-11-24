"""Background search worker (QThread) with cancellation."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QThread, Signal

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.promo.service import PromoService, ShopPromoRequest
from tyre_finder.logic.search import SearchOrchestrator
from tyre_finder.models import SearchQuery, SiteResult

log = logging.getLogger(__name__)


class SearchWorker(QThread):
    """Runs :class:`SearchOrchestrator` off the GUI thread."""

    site_done = Signal(object)  # SiteResult
    search_finished = Signal(list)  # list[SiteResult]

    def __init__(self, scrapers: list[TyreScraper], query: SearchQuery) -> None:
        super().__init__()
        self._orchestrator = SearchOrchestrator(scrapers)
        self._query = query
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Ask all scrapers to stop as soon as possible."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        """True after :meth:`cancel`."""
        return self._cancel.is_set()

    def run(self) -> None:
        """Thread body."""
        log.info("Search started: %s %s", self._query.size, self._query.season.value)

        def emit(result: SiteResult) -> None:
            self.site_done.emit(result)

        results = self._orchestrator.run(self._query, emit, self._cancel)
        self.search_finished.emit(results)


class SiteTestWorker(QThread):
    """Runs one scraper for the "Test" button in the sites dialog."""

    done = Signal(object)  # SiteResult

    def __init__(self, scraper: TyreScraper, query: SearchQuery) -> None:
        super().__init__()
        self._orchestrator = SearchOrchestrator([scraper])
        self._query = query

    def run(self) -> None:
        """Thread body."""
        results = self._orchestrator.run(self._query)
        self.done.emit(results[0])


class PromoWorker(QThread):
    """Looks up promo codes for all shops (runs in parallel with :class:`SearchWorker`)."""

    shop_done = Signal(object)  # ShopPromoResult
    promos_finished = Signal(dict)  # dict[str, ShopPromoResult]

    def __init__(
        self,
        service: PromoService,
        requests: list[ShopPromoRequest],
        use_cache: bool = True,
    ) -> None:
        super().__init__()
        self._service = service
        self._requests = requests
        self._use_cache = use_cache
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Stop pending lookups."""
        self._cancel.set()

    def run(self) -> None:
        """Thread body."""
        log.info("Promo lookup started for %d shops", len(self._requests))
        results = self._service.lookup(
            self._requests,
            on_shop_done=self.shop_done.emit,
            cancel_event=self._cancel,
            use_cache=self._use_cache,
        )
        self.promos_finished.emit(results)
