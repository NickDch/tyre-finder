"""Runs all promo sources for all shops in parallel, filters to current codes, caches."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from tyre_finder.data.http import CancelledError, FetchError, HttpClient
from tyre_finder.data.promo.aggregators import CuponeriaSource, DiscountsBgSource, KuponovoSource
from tyre_finder.data.promo.base import LookupContext, PromoSource, ShopRef, SourceCheck
from tyre_finder.data.promo.dates import Freshness
from tyre_finder.data.promo.settings import EngineChoice, PromoSettings
from tyre_finder.data.promo.shop_pages import MedinaPromoSource, ShopPageSource
from tyre_finder.data.promo.store import ManualPromo, PromoCache
from tyre_finder.data.promo.websearch import (
    BingHtmlEngine,
    BraveEngine,
    DuckDuckGoHtmlEngine,
    GoogleCseEngine,
    SearchEngine,
    WebSearchSource,
)
from tyre_finder.models import Confidence, PromoCode, PromoOrigin

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ShopPromoResult:
    """Current promo codes for one shop plus what was checked/dropped."""

    shop: str
    codes: list[PromoCode] = field(default_factory=list)
    dropped: list[tuple[PromoCode, str]] = field(default_factory=list)
    checks: list[SourceCheck] = field(default_factory=list)
    from_cache: bool = False
    error: str = ""

    @property
    def confirmed(self) -> list[PromoCode]:
        """High-confidence codes."""
        return [c for c in self.codes if c.confidence is Confidence.HIGH]

    @property
    def possible(self) -> list[PromoCode]:
        """Low-confidence candidates ("възможен код")."""
        return [c for c in self.codes if c.confidence is Confidence.LOW]


@dataclass(slots=True)
class ShopPromoRequest:
    """A shop and its manual codes."""

    shop: ShopRef
    manual: list[ManualPromo] = field(default_factory=list)


def build_engines(settings: PromoSettings) -> list[SearchEngine]:
    """Engines in order of preference for the chosen setting."""
    google = (
        GoogleCseEngine(settings.google_api_key.strip(), settings.google_cx.strip())
        if settings.google_configured
        else None
    )
    brave = BraveEngine(settings.brave_api_key.strip()) if settings.brave_api_key.strip() else None
    choice = settings.engine
    if choice is EngineChoice.OFF:
        return []
    if choice is EngineChoice.GOOGLE:
        return [google] if google else []
    if choice is EngineChoice.BRAVE:
        return [brave] if brave else []
    if choice is EngineChoice.BING:
        return [BingHtmlEngine()]
    if choice is EngineChoice.DUCKDUCKGO:
        return [DuckDuckGoHtmlEngine()]
    engines: list[SearchEngine] = [e for e in (google, brave) if e is not None]
    return [*engines, BingHtmlEngine(), DuckDuckGoHtmlEngine()]


def filter_current(
    codes: list[PromoCode], today: date, freshness: Freshness
) -> tuple[list[PromoCode], list[tuple[PromoCode, str]]]:
    """Keep only current, tyre-related codes; de-duplicate (best confidence wins)."""
    kept: dict[str, PromoCode] = {}
    dropped: list[tuple[PromoCode, str]] = []
    for code in codes:
        reason = drop_reason(code, today, freshness)
        if reason:
            dropped.append((code, reason))
            continue
        prev = kept.get(code.key)
        if prev is None or (_rank(code) > _rank(prev)):
            kept[code.key] = code
    return list(kept.values()), dropped


def _rank(code: PromoCode) -> tuple[int, float]:
    return (1 if code.confidence is Confidence.HIGH else 0, code.score)


def drop_reason(code: PromoCode, today: date, freshness: Freshness) -> str:
    """Bulgarian reason why a code is not current/relevant, or ''."""
    if code.valid_until is not None and code.valid_until < today:
        return f"изтекъл на {code.valid_until:%d.%m.%Y}"
    if code.valid_from is not None and code.valid_from > today:
        return f"започва на {code.valid_from:%d.%m.%Y}"
    if not code.applies_to_tyres:
        return "не се отнася за гуми"
    if code.origin in (PromoOrigin.AGGREGATOR, PromoOrigin.WEB) and not freshness.is_current(
        today, code.valid_until, code.published_at, code.valid_from
    ):
        if code.published_at is None:
            return "без срок на валидност и без дата на публикуване"
        return (
            f"без срок на валидност, публикуван на {code.published_at:%d.%m.%Y} "
            f"(по-стар от {freshness.window_days} дни)"
        )
    return ""


class PromoService:
    """Finds promo codes for many shops concurrently."""

    def __init__(
        self,
        settings: PromoSettings,
        *,
        cache: PromoCache | None = None,
        sources: list[PromoSource] | None = None,
        http_factory: Callable[[threading.Event], HttpClient] | None = None,
        max_workers: int = 6,
        shop_timeout_s: float = 90.0,
    ) -> None:
        self.settings = settings
        self.cache = cache
        self.max_workers = max_workers
        self.shop_timeout_s = shop_timeout_s
        self._http_factory = http_factory or (
            lambda ev: HttpClient(
                timeout_s=15.0, min_interval_s=1.5, cancel_event=ev, max_retries=1
            )
        )
        if sources is None:
            sources = [ShopPageSource(), MedinaPromoSource()]
            if settings.use_aggregators:
                sources += [KuponovoSource(), CuponeriaSource(), DiscountsBgSource()]
            engines = build_engines(settings)
            if engines:
                sources.append(WebSearchSource(engines, settings.max_pages_per_shop))
        self.sources = sources

    def _cache_key(self, shop: ShopRef) -> str:
        return f"{shop.id}|{shop.base_url}|{self.settings.signature()}"

    def lookup(
        self,
        requests: list[ShopPromoRequest],
        on_shop_done: Callable[[ShopPromoResult], None] | None = None,
        cancel_event: threading.Event | None = None,
        now: datetime | None = None,
        use_cache: bool = True,
    ) -> dict[str, ShopPromoResult]:
        """Look up all shops; returns results keyed by shop display name."""
        cancel = cancel_event or threading.Event()
        now = now or datetime.now().astimezone().replace(tzinfo=None)
        freshness = Freshness(self.settings.window_days)
        results: dict[str, ShopPromoResult] = {}
        http = self._http_factory(cancel)
        ctx = LookupContext(http=http, today=now.date(), now=now, freshness=freshness)
        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = {pool.submit(self._one, req, ctx, use_cache): req for req in requests}
                for fut in as_completed(futures):
                    req = futures[fut]
                    try:
                        result = fut.result()
                    except CancelledError:
                        result = ShopPromoResult(req.shop.name, error="прекратено")
                    results[req.shop.name] = result
                    if on_shop_done is not None:
                        on_shop_done(result)
        finally:
            http.close()
        return results

    def _one(self, req: ShopPromoRequest, ctx: LookupContext, use_cache: bool) -> ShopPromoResult:
        shop = req.shop
        raw: list[PromoCode] = []
        checks: list[SourceCheck] = []
        cached = (
            self.cache.get(self._cache_key(shop), ctx.now) if (self.cache and use_cache) else None
        )
        if cached is not None:
            raw = cached.codes
            checks = [SourceCheck(**c) for c in cached.checks]  # type: ignore[arg-type]
        else:
            deadline = time.monotonic() + self.shop_timeout_s
            for source in self.sources:
                if not source.applies_to(shop):
                    continue
                if time.monotonic() > deadline:
                    checks.append(
                        SourceCheck(source.label, "", "пропуснато (изтече времето)", False)
                    )
                    continue
                try:
                    out = source.lookup(shop, ctx)
                except CancelledError:
                    raise
                except (FetchError, ValueError, KeyError, TypeError) as exc:
                    log.warning("%s / %s failed: %s", shop.name, source.label, exc)
                    checks.append(SourceCheck(source.label, "", f"грешка: {exc}", ok=False))
                    continue
                raw.extend(out.codes)
                checks.extend(out.checks)
            if self.cache is not None:
                self.cache.put(self._cache_key(shop), raw, [asdict(c) for c in checks], ctx.now)
        manual = [
            m.to_promo(shop.name, shop.base_url, ctx.now)
            for m in req.manual
            if m.enabled and m.code
        ]
        codes, dropped = filter_current(manual + raw, ctx.today, ctx.freshness)
        log.info(
            "%s: %d current promo codes (%d dropped)%s",
            shop.name,
            len(codes),
            len(dropped),
            " [cache]" if cached else "",
        )
        return ShopPromoResult(shop.name, codes, dropped, checks, from_cache=cached is not None)
