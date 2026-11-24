"""Polite HTTP client shared by all scrapers."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

# A plain desktop-browser identity.  Some shops sit behind Cloudflare bot
# rules that reject unknown product tokens in the User-Agent, so we no longer
# append "TyreFinder/1.0".  We stay polite through throttling instead.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.7",
    # Only encodings httpx can decode without optional packages.
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

#: Statuses worth one more polite attempt after a pause.  403 is included
#: because WAFs often reject a single request burst and then let us through.
RETRY_STATUSES = frozenset({403, 429, 502, 503, 511})

_CHALLENGE_MARKERS = (
    "_cf_chl_opt",
    "/cdn-cgi/challenge-platform/",
    "<title>Just a moment...</title>",
    "Attention Required! | Cloudflare",
    "challenges.cloudflare.com",
)


def is_challenge_page(status: int, text: str, headers: dict[str, str] | None = None) -> bool:
    """True if the response is an anti-bot (JavaScript/CAPTCHA) challenge page.

    Such pages can only be passed by a real browser running JavaScript; the
    application deliberately does not try to solve or bypass them.
    """
    if headers and headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    if status not in (403, 429, 503):
        return False
    head = text[:20000]
    return any(marker in head for marker in _CHALLENGE_MARKERS)


@dataclass(frozen=True, slots=True)
class Fetched:
    """A finished HTTP exchange (any status)."""

    status: int
    url: str  # final URL after redirects
    text: str
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def is_challenge(self) -> bool:
        """True if this is an anti-bot challenge page (see :func:`is_challenge_page`)."""
        return is_challenge_page(self.status, self.text, self.headers)


class FetchError(Exception):
    """Raised when a page cannot be downloaded."""

    def __init__(self, message: str, status: int | None = None, short: str = "") -> None:
        super().__init__(message)
        self.status = status
        #: One-line summary for the status list (the full text goes to tooltips).
        self.short = short or message


class BlockedError(FetchError):
    """The site refused access (HTTP 403/429, CAPTCHA or a JavaScript challenge)."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        short: str = "",
        challenge: bool = False,
    ) -> None:
        super().__init__(message, status, short)
        self.challenge = challenge


class NotFoundError(FetchError):
    """The page does not exist (HTTP 404/410) - usually the site changed its URLs."""


def error_for_status(fetched: Fetched, host: str) -> FetchError:
    """Build a user-facing (Bulgarian) error for a failed response."""
    status = fetched.status
    if fetched.is_challenge:
        return BlockedError(
            f"Сайтът е блокирал достъпа: {host} показва Cloudflare проверка "
            "„Just a moment…“ (JavaScript защита срещу ботове, HTTP "
            f"{status}). Програмата не заобикаля такива проверки — отворете "
            "сайта в браузъра или опитайте по-късно.",
            status,
            short="Блокиран достъп: Cloudflare JavaScript проверка",
            challenge=True,
        )
    if status == 403:
        return BlockedError(
            f"Сайтът е блокирал достъпа: HTTP 403 от {host}. Опитайте по-късно или от друга мрежа.",
            status,
            short="Блокиран достъп (HTTP 403)",
        )
    if status == 429:
        return BlockedError(
            f"Сайтът е блокирал достъпа: твърде много заявки към {host} (HTTP 429). "
            "Изчакайте няколко минути.",
            status,
            short="Блокиран достъп: твърде много заявки (HTTP 429)",
        )
    if status == 511:
        return BlockedError(
            f"Сайтът е блокирал достъпа: {host} поиска CAPTCHA (HTTP 511) — защита срещу ботове.",
            status,
            short="Блокиран достъп: CAPTCHA (HTTP 511)",
        )
    if status in (404, 410):
        return NotFoundError(
            f"Страницата не е намерена: HTTP {status} от {host}. Сайтът вероятно е "
            "сменил адресите си — нужна е актуализация на програмата.",
            status,
            short=f"Страницата не е намерена (HTTP {status}) — сайтът е сменил адресите",
        )
    if status >= 500:
        return FetchError(f"Сървърна грешка при {host} (HTTP {status}). Опитайте по-късно.", status)
    return FetchError(f"HTTP {status} от {host}", status)


class CancelledError(Exception):
    """Raised when the user cancelled the search."""


class HttpClient:
    """Thread-safe HTTP client with timeouts and a minimal per-host delay."""

    def __init__(
        self,
        timeout_s: float = 20.0,
        min_interval_s: float = 0.8,
        cancel_event: threading.Event | None = None,
        max_retries: int = 2,
    ) -> None:
        self._client = httpx.Client(
            headers=DEFAULT_HEADERS,
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            follow_redirects=True,
        )
        self._min_interval_s = min_interval_s
        self._max_retries = max_retries
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()
        self._cancel_event = cancel_event or threading.Event()
        self._warmed: set[str] = set()

    @property
    def cancel_event(self) -> threading.Event:
        """Event that aborts pending requests when set."""
        return self._cancel_event

    def _throttle(self, host: str) -> None:
        with self._lock:
            last = self._last_request.get(host, 0.0)
            wait = self._min_interval_s - (time.monotonic() - last)
            self._last_request[host] = time.monotonic() + max(wait, 0.0)
        if wait > 0 and self._cancel_event.wait(wait):
            raise CancelledError("Търсенето е прекратено")

    def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        retry: bool = True,
    ) -> Fetched:
        """Perform a request and return it whatever the status code.

        Raises :class:`FetchError` only for network errors/timeouts.
        """
        if self._cancel_event.is_set():
            raise CancelledError("Търсенето е прекратено")
        host = urlsplit(url).netloc
        response: httpx.Response | None = None
        attempts = self._max_retries + 1 if retry else 1
        for attempt in range(attempts):
            self._throttle(host)
            log.debug("%s %s (attempt %d)", method, url, attempt + 1)
            try:
                response = self._client.request(
                    method, url, params=params, data=data, headers=headers
                )
            except httpx.TimeoutException as exc:
                raise FetchError(f"Изтече времето за отговор ({host})") from exc
            except httpx.HTTPError as exc:
                raise FetchError(f"Мрежова грешка: {exc}") from exc
            if response.status_code not in RETRY_STATUSES or attempt == attempts - 1:
                break
            if is_challenge_page(response.status_code, response.text, dict(response.headers)):
                # Retrying a JavaScript challenge only adds load; report it instead.
                break
            delay = 2.0 * (attempt + 1)
            log.info("%s answered HTTP %d, retrying in %.1fs", host, response.status_code, delay)
            if self._cancel_event.wait(delay):
                raise CancelledError("Търсенето е прекратено")
        assert response is not None
        return Fetched(
            response.status_code,
            str(response.url),
            response.text,
            {k.lower(): v for k, v in response.headers.items()},
        )

    def warm_up(self, home_url: str) -> None:
        """Open the shop home page once per session, like a visitor would.

        This picks up the session cookies the shop sets on the first visit.
        Failures are ignored - the real request reports any problem.
        """
        host = urlsplit(home_url).netloc
        with self._lock:
            if host in self._warmed:
                return
            self._warmed.add(host)
        try:
            result = self.fetch(home_url, retry=False)
            log.debug("warm-up %s -> HTTP %d", host, result.status)
        except FetchError as exc:
            log.info("warm-up of %s failed: %s", host, exc)

    def get_text(self, url: str, *, referer: str | None = None) -> str:
        """Download *url* and return the decoded body.

        Raises :class:`BlockedError`, :class:`NotFoundError` or
        :class:`FetchError` for HTTP errors.
        """
        headers = {"Referer": referer, "Sec-Fetch-Site": "same-origin"} if referer else None
        result = self.fetch(url, headers=headers)
        if result.status >= 400:
            raise error_for_status(result, urlsplit(url).netloc)
        return result.text

    def close(self) -> None:
        """Release network resources."""
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
