"""Concurrent search over all enabled shops; one failing shop never breaks the others."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.http import CancelledError, FetchError, HttpClient
from tyre_finder.data.parsing import ParseError
from tyre_finder.models import SearchQuery, SiteResult, SiteStatusKind

log = logging.getLogger(__name__)

ProgressCallback = Callable[[SiteResult], None]


@dataclass(slots=True)
class SearchOrchestrator:
    """Runs all scrapers in parallel with timeouts and cancellation."""

    scrapers: list[TyreScraper]
    timeout_s: float = 20.0
    max_workers: int = 8

    def run(
        self,
        query: SearchQuery,
        on_site_done: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> list[SiteResult]:
        """Search every shop; returns one :class:`SiteResult` per scraper."""
        cancel = cancel_event or threading.Event()
        results: list[SiteResult] = []
        with (
            HttpClient(timeout_s=self.timeout_s, cancel_event=cancel) as client,
            ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="scraper") as pool,
        ):
            futures: dict[Future[SiteResult], TyreScraper] = {
                pool.submit(self._run_one, scraper, client, query): scraper
                for scraper in self.scrapers
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                if on_site_done is not None:
                    on_site_done(result)
        return results

    @staticmethod
    def _run_one(scraper: TyreScraper, client: HttpClient, query: SearchQuery) -> SiteResult:
        start = time.monotonic()
        try:
            offers = scraper.search(client, query)
        except CancelledError:
            return SiteResult(scraper.name, SiteStatusKind.CANCELLED, message="Прекратено")
        except FetchError as exc:
            log.warning("%s failed: %s", scraper.name, exc)
            return SiteResult(
                scraper.name,
                SiteStatusKind.ERROR,
                message=exc.short,
                elapsed_s=time.monotonic() - start,
                detail=str(exc),
            )
        except ParseError as exc:
            log.warning("%s parse error: %s", scraper.name, exc)
            return SiteResult(
                scraper.name,
                SiteStatusKind.ERROR,
                message=str(exc),
                elapsed_s=time.monotonic() - start,
            )
        except Exception as exc:
            log.exception("%s crashed", scraper.name)
            return SiteResult(
                scraper.name,
                SiteStatusKind.ERROR,
                message=f"Неочаквана грешка: {exc}",
                elapsed_s=time.monotonic() - start,
            )
        status = SiteStatusKind.OK if offers else SiteStatusKind.EMPTY
        return SiteResult(
            scraper.name,
            status,
            offers=offers,
            message=f"{len(offers)} оферти" if offers else "Няма резултати",
            elapsed_s=time.monotonic() - start,
        )
