"""Shared types for promo-code sources."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from tyre_finder.data.http import HttpClient
from tyre_finder.data.promo.dates import Freshness
from tyre_finder.models import PromoCode

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ShopRef:
    """The shop a lookup is for (decoupled from the site config)."""

    id: str
    name: str
    base_url: str

    @property
    def domain(self) -> str:
        """'gumi7.com' for 'https://gumi7.com/bg/'."""
        host = urlsplit(self.base_url).netloc.lower()
        return host.removeprefix("www.")

    @property
    def names(self) -> tuple[str, ...]:
        """Strings that identify the shop in a text (name, domain, domain label)."""
        label = self.domain.split(".")[0]
        variants = {self.name, self.domain, label, label.replace("-", " ")}
        return tuple(v for v in variants if len(v) >= 4)

    @property
    def general_store(self) -> bool:
        """Marketplaces that sell far more than tyres."""
        return self.domain in GENERAL_STORES


GENERAL_STORES = frozenset({"emag.bg"})


@dataclass(slots=True)
class SourceCheck:
    """What one source did for a shop (shown in the promo dialog)."""

    source: str
    url: str
    outcome: str  # Bulgarian, e.g. "2 кода", "няма страница (404)", "блокирано"
    ok: bool = True


@dataclass(slots=True)
class LookupContext:
    """Everything a source needs."""

    http: HttpClient
    today: date
    now: datetime
    freshness: Freshness = field(default_factory=Freshness)


@dataclass(slots=True)
class SourceOutput:
    """Codes plus a log of the URLs checked."""

    codes: list[PromoCode] = field(default_factory=list)
    checks: list[SourceCheck] = field(default_factory=list)


class PromoSource(ABC):
    """One place where promo codes may be published."""

    label: str = "source"

    @abstractmethod
    def applies_to(self, shop: ShopRef) -> bool:
        """Whether this source should be asked for *shop*."""

    @abstractmethod
    def lookup(self, shop: ShopRef, ctx: LookupContext) -> SourceOutput:
        """Find codes for *shop*. Must not raise for HTTP/parse problems."""

    @staticmethod
    def soup(html: str) -> BeautifulSoup:
        """Parse HTML with lxml."""
        return BeautifulSoup(html, "lxml")
