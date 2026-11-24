"""Open-web search for promo codes.

Engines, in order of preference (``auto``):

1. Google Programmable Search (Custom Search JSON API) - needs the user's API key + CX.
2. Brave Search API - needs the user's key.
3. Bing HTML and 4. DuckDuckGo HTML - no key.

google.com itself is never scraped (blocked and against its terms). Keys live only in
the user's config file (see :mod:`tyre_finder.data.promo.settings`).

The Bing/DuckDuckGo result markup (``li.b_algo``, ``a.result__a``) could not be checked
live from the development machine (both answer data-centre IPs with a bot challenge or
an empty page, which is detected and reported as "blocked"); the JSON APIs are stable.
"""

from __future__ import annotations

import logging
import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import parse_qs, unquote, urlsplit

from bs4 import BeautifulSoup

from tyre_finder.data.http import CancelledError, FetchError, HttpClient
from tyre_finder.data.parsing import clean_text
from tyre_finder.data.promo.base import (
    LookupContext,
    PromoSource,
    ShopRef,
    SourceCheck,
    SourceOutput,
)
from tyre_finder.data.promo.dates import (
    DateKind,
    find_dates,
    page_published_date,
    parse_iso_datetime,
)
from tyre_finder.data.promo.extract import (
    find_code_candidates,
    mentions_shop,
    parse_terms,
    score_candidate,
    shop_context,
)
from tyre_finder.models import Confidence, PromoCode, PromoOrigin

log = logging.getLogger(__name__)

HIGH_CONFIDENCE = 0.85
# Coupon aggregators are read by dedicated parsers; skip them in web results.
SKIP_DOMAINS = frozenset(
    {"kuponovo.bg", "cuponeria.bg", "discounts.bg", "google.com", "bing.com", "duckduckgo.com"}
)


class EngineError(Exception):
    """The engine failed (bad key, quota, network)."""


class EngineBlockedError(EngineError):
    """The engine answered with a bot challenge / empty page."""


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One search result."""

    title: str
    url: str
    snippet: str
    published: date | None = None


class SearchEngine(ABC):
    """A web search backend."""

    name: str = "engine"

    def __init__(self) -> None:
        self._lock = threading.Lock()  # one query at a time per engine (politeness)

    @abstractmethod
    def search(self, http: HttpClient, query: str, fresh_days: int) -> list[SearchHit]:
        """Run *query*; raises :class:`EngineError` on failure."""

    def run(self, http: HttpClient, query: str, fresh_days: int) -> list[SearchHit]:
        """Serialised :meth:`search`."""
        with self._lock:
            return self.search(http, query, fresh_days)


class GoogleCseEngine(SearchEngine):
    """Google Programmable Search Engine - Custom Search JSON API (100 free queries/day)."""

    name = "Google Programmable Search"
    endpoint = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str, cx: str) -> None:
        super().__init__()
        self.api_key = api_key
        self.cx = cx

    def search(self, http: HttpClient, query: str, fresh_days: int) -> list[SearchHit]:
        months = max(1, round(fresh_days / 30))
        params = {
            "key": self.api_key,
            "cx": self.cx,
            "q": query,
            "num": "10",
            "hl": "bg",
            "gl": "bg",
            "dateRestrict": f"m{months}" if fresh_days >= 28 else f"d{fresh_days}",
        }
        res = http.fetch(self.endpoint, params=params, retry=False)
        return self.parse(res.status, res.text)

    @staticmethod
    def parse(status: int, body: str) -> list[SearchHit]:
        """Parse a Custom Search JSON response."""
        data = _json(body)
        if status != 200:
            message = ""
            if isinstance(data.get("error"), dict):
                message = str(data["error"].get("message", ""))
            raise EngineError(f"Google: HTTP {status} {message}".strip())
        hits: list[SearchHit] = []
        for item in data.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            published = None
            pagemap = item.get("pagemap") if isinstance(item.get("pagemap"), dict) else {}
            for meta in pagemap.get("metatags", []) or []:
                for key in ("article:published_time", "og:updated_time", "date"):
                    if isinstance(meta, dict) and meta.get(key):
                        published = parse_iso_datetime(str(meta[key]))
                        break
                if published:
                    break
            hits.append(
                SearchHit(
                    clean_text(str(item.get("title", ""))),
                    str(item.get("link", "")),
                    clean_text(str(item.get("snippet", ""))),
                    published,
                )
            )
        return hits


class BraveEngine(SearchEngine):
    """Brave Search API (needs a subscription token; has a free tier)."""

    name = "Brave Search API"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self.api_key = api_key

    def search(self, http: HttpClient, query: str, fresh_days: int) -> list[SearchHit]:
        freshness = "pw" if fresh_days <= 7 else "pm" if fresh_days <= 31 else "py"
        res = http.fetch(
            self.endpoint,
            params={"q": query, "count": "10", "country": "BG", "freshness": freshness},
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
            retry=False,
        )
        return self.parse(res.status, res.text)

    @staticmethod
    def parse(status: int, body: str) -> list[SearchHit]:
        """Parse a Brave web search response."""
        if status != 200:
            raise EngineError(f"Brave: HTTP {status}")
        data = _json(body)
        web = data.get("web") if isinstance(data.get("web"), dict) else {}
        hits: list[SearchHit] = []
        for item in web.get("results", []) or []:
            if not isinstance(item, dict):
                continue
            published = parse_iso_datetime(str(item.get("page_age") or ""))
            hits.append(
                SearchHit(
                    clean_text(str(item.get("title", ""))),
                    str(item.get("url", "")),
                    clean_text(re.sub(r"<[^>]+>", "", str(item.get("description", "")))),
                    published,
                )
            )
        return hits


class BingHtmlEngine(SearchEngine):
    """bing.com HTML results, no key. Time filter: past month."""

    name = "Bing (без ключ)"
    endpoint = "https://www.bing.com/search"

    def search(self, http: HttpClient, query: str, fresh_days: int) -> list[SearchHit]:
        age = 'ex1:"ez2"' if fresh_days <= 7 else 'ex1:"ez3"'
        res = http.fetch(
            self.endpoint,
            params={"q": query, "setlang": "bg", "cc": "BG", "filters": age},
            retry=False,
        )
        return self.parse(res.status, res.text)

    @staticmethod
    def parse(status: int, html: str) -> list[SearchHit]:
        """Parse Bing's result page; an empty/challenge page raises EngineBlockedError."""
        if status != 200:
            raise EngineBlockedError(f"Bing: HTTP {status}")
        soup = BeautifulSoup(html, "lxml")
        hits: list[SearchHit] = []
        for li in soup.select("li.b_algo"):
            link = li.select_one("h2 a[href]")
            if link is None:
                continue
            snippet_tag = li.select_one(".b_caption p") or li.select_one("p")
            snippet = clean_text(snippet_tag.get_text(" ")) if snippet_tag else ""
            hits.append(SearchHit(clean_text(link.get_text(" ")), str(link["href"]), snippet))
        if not hits and (soup.select_one("li.b_no") or "captcha" in html.lower()):
            raise EngineBlockedError("Bing не върна резултати (вероятно защита срещу ботове)")
        return hits


class DuckDuckGoHtmlEngine(SearchEngine):
    """html.duckduckgo.com, no key. Time filter ``df=m`` (past month)."""

    name = "DuckDuckGo (без ключ)"
    endpoint = "https://html.duckduckgo.com/html/"

    def search(self, http: HttpClient, query: str, fresh_days: int) -> list[SearchHit]:
        df = "w" if fresh_days <= 7 else "m" if fresh_days <= 31 else "y"
        res = http.fetch(
            self.endpoint,
            method="POST",
            data={"q": query, "kl": "bg-bg", "df": df},
            headers={"Referer": "https://html.duckduckgo.com/"},
            retry=False,
        )
        return self.parse(res.status, res.text)

    @staticmethod
    def parse(status: int, html: str) -> list[SearchHit]:
        """Parse DDG's HTML endpoint; the bot challenge raises EngineBlockedError."""
        if status == 202 or "anomaly" in html[:5000].lower() or "bots use duckduckgo" in html:
            raise EngineBlockedError("DuckDuckGo поиска потвърждение, че не сте бот")
        if status != 200:
            raise EngineBlockedError(f"DuckDuckGo: HTTP {status}")
        soup = BeautifulSoup(html, "lxml")
        hits: list[SearchHit] = []
        for result in soup.select("div.result"):
            link = result.select_one("a.result__a[href]")
            if link is None:
                continue
            snippet_tag = result.select_one(".result__snippet")
            hits.append(
                SearchHit(
                    clean_text(link.get_text(" ")),
                    _ddg_target(str(link["href"])),
                    clean_text(snippet_tag.get_text(" ")) if snippet_tag else "",
                )
            )
        return hits


def _ddg_target(href: str) -> str:
    """Unwrap DuckDuckGo's ``//duckduckgo.com/l/?uddg=<url>`` redirect."""
    parts = urlsplit(href if "://" in href else f"https:{href}")
    if parts.path.startswith("/l/"):
        target = parse_qs(parts.query).get("uddg")
        if target:
            return unquote(target[0])
    return href


def _json(body: str) -> dict[str, object]:
    import json  # noqa: PLC0415 - tiny helper

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def shop_queries(shop: ShopRef) -> list[str]:
    """Queries for one shop (2 per shop keeps Google CSE within 100/day with a 6 h cache)."""
    return [
        f'"{shop.name}" OR "{shop.domain}" промокод OR "промо код" OR "код за отстъпка"',
        f'"{shop.domain}" promo code OR coupon',
    ]


class WebSearchSource(PromoSource):
    """Searches the web, opens the top results and extracts candidate codes."""

    label = "Търсене в интернет"

    def __init__(self, engines: list[SearchEngine], max_pages: int = 3) -> None:
        self.engines = engines
        self.max_pages = max_pages
        self._blocked: set[str] = set()
        self._blocked_lock = threading.Lock()

    def applies_to(self, shop: ShopRef) -> bool:
        return bool(self.engines)

    def _search(self, ctx: LookupContext, query: str, checks: list[SourceCheck]) -> list[SearchHit]:
        for engine in self.engines:
            with self._blocked_lock:
                if engine.name in self._blocked:
                    continue
            try:
                hits = engine.run(ctx.http, query, ctx.freshness.window_days)
            except CancelledError:
                raise
            except EngineBlockedError as exc:
                with self._blocked_lock:
                    self._blocked.add(engine.name)
                checks.append(SourceCheck(engine.name, query, f"блокирано: {exc}", ok=False))
                continue
            except (EngineError, FetchError) as exc:
                checks.append(SourceCheck(engine.name, query, str(exc), ok=False))
                continue
            checks.append(SourceCheck(engine.name, query, f"{len(hits)} резултата"))
            return hits
        if self.engines and all(e.name in self._blocked for e in self.engines):
            checks.append(
                SourceCheck(
                    self.label,
                    query,
                    "пропуснато: търсачките без ключ са блокирани — добавете Google API ключ",
                    ok=False,
                )
            )
        return []

    def lookup(self, shop: ShopRef, ctx: LookupContext) -> SourceOutput:
        out = SourceOutput()
        hits: dict[str, SearchHit] = {}
        for query in shop_queries(shop):
            for hit in self._search(ctx, query, out.checks):
                domain = urlsplit(hit.url).netloc.lower().removeprefix("www.")
                if hit.url and domain not in SKIP_DOMAINS:
                    hits.setdefault(hit.url, hit)
        for hit in hits.values():  # candidates straight from the snippets
            out.codes.extend(
                self.extract(f"{hit.title}. {hit.snippet}", hit.url, shop, ctx, hit.published)
            )
        relevant = [
            h for h in hits.values() if mentions_shop(f"{h.title} {h.snippet} {h.url}", shop.names)
        ]
        for hit in relevant[: self.max_pages]:
            try:
                html = ctx.http.get_text(hit.url)
            except FetchError as exc:
                out.checks.append(SourceCheck(self.label, hit.url, str(exc), ok=False))
                continue
            codes = self.extract_page(html, hit.url, shop, ctx, hit.published)
            out.codes.extend(codes)
            out.checks.append(SourceCheck(self.label, hit.url, f"{len(codes)} кандидата"))
        return out

    def extract_page(
        self, html: str, url: str, shop: ShopRef, ctx: LookupContext, hit_date: date | None
    ) -> list[PromoCode]:
        """Candidates in a fetched result page."""
        soup = BeautifulSoup(html, "lxml")
        published = page_published_date(soup) or hit_date
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
            tag.decompose()
        return self.extract(clean_text(soup.get_text(" ")), url, shop, ctx, published)

    def extract(
        self, text: str, url: str, shop: ShopRef, ctx: LookupContext, published: date | None
    ) -> list[PromoCode]:
        """Candidates in a text; each must mention the shop near the code."""
        codes: list[PromoCode] = []
        for cand in find_code_candidates(text):
            if not mentions_shop(shop_context(text, cand.position), shop.names):
                continue
            terms = parse_terms(cand.window, general_store=shop.general_store)
            until = terms.valid_until
            future_date = any(
                f.kind is DateKind.UNTIL and f.value >= ctx.today for f in find_dates(cand.window)
            )
            recent = published is not None and published >= ctx.today - timedelta(
                days=ctx.freshness.window_days
            )
            has_discount = terms.percent is not None or terms.amount_eur is not None
            score = score_candidate(
                cand, terms, shop.names, current_date_found=future_date or recent
            )
            codes.append(
                PromoCode(
                    shop=shop.name,
                    code=cand.code,
                    title=f"Възможен код {cand.code}",
                    origin=PromoOrigin.WEB,
                    source_url=url,
                    fetched_at=ctx.now,
                    discount_percent=terms.percent,
                    discount_amount_eur=terms.amount_eur,
                    min_order_eur=terms.min_order_eur,
                    min_quantity=terms.min_quantity,
                    brands=terms.brands,
                    conditions=cand.window,
                    valid_from=terms.valid_from,
                    valid_until=until,
                    published_at=published,
                    confidence=Confidence.HIGH
                    if score >= HIGH_CONFIDENCE and has_discount
                    else Confidence.LOW,
                    score=round(score, 2),
                    applies_to_tyres=terms.applies_to_tyres,
                    selected_products_only=terms.selected_only,
                )
            )
        return codes
