"""User editable list of shops, persisted as JSON in the user config directory."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from platformdirs import user_config_dir

from tyre_finder.data.base import TyreScraper
from tyre_finder.data.promo.store import ManualPromo
from tyre_finder.data.sites.diana import DianaScraper
from tyre_finder.data.sites.emag import EmagScraper
from tyre_finder.data.sites.generic import GenericScraper, GenericSelectors, GenericSiteSpec
from tyre_finder.data.sites.gumi7 import Gumi7Scraper
from tyre_finder.data.sites.gumi24 import Gumi24Scraper
from tyre_finder.data.sites.medinamed import MedinaMedScraper
from tyre_finder.data.sites.nk_platform import NkPlatformScraper
from tyre_finder.data.sites.primex import PrimexScraper
from tyre_finder.data.sites.progumi import ProGumiScraper
from tyre_finder.data.sites.supergumi import SuperGumiScraper
from tyre_finder.data.sites.tirendo import TirendoScraper

log = logging.getLogger(__name__)

CONFIG_VERSION = 1
APP_NAME = "tyre-finder"


class SiteKind(StrEnum):
    """How a site is scraped."""

    BUILTIN = "builtin"  # dedicated parser module
    NK = "nk"  # NK Software platform template: base URL only
    GENERIC = "generic"  # user defined URL template + CSS selectors


class SiteConfigError(ValueError):
    """Raised when a site definition is invalid."""


BUILTIN_PARSERS: dict[str, Callable[[], TyreScraper]] = {
    "emag": EmagScraper,
    "diana": DianaScraper,
    "gumi7": Gumi7Scraper,
    "primex": PrimexScraper,
    "progumi": ProGumiScraper,
    "supergumi": SuperGumiScraper,
    "tirendo": TirendoScraper,
    "gumi24": Gumi24Scraper,
    "medinamed": MedinaMedScraper,
}


@dataclass(slots=True)
class SiteConfig:
    """One configured shop."""

    id: str
    name: str
    kind: SiteKind
    base_url: str
    enabled: bool = True
    builtin: bool = False
    parser: str = ""
    generic: GenericSiteSpec | None = None
    manual_promos: list[ManualPromo] = field(default_factory=list)

    def validate(self) -> list[str]:
        """Return Bulgarian error messages (empty when valid)."""
        errors: list[str] = []
        if not self.name.strip():
            errors.append("Името е задължително")
        if not re.match(r"^https?://[^\s/]+\.[^\s/]+", self.base_url.strip()):
            errors.append("Невалиден адрес на сайта (пример: https://www.example.bg/)")
        if self.kind is SiteKind.BUILTIN and self.parser not in BUILTIN_PARSERS:
            errors.append(f"Непознат вграден парсер „{self.parser}“")
        if self.kind is SiteKind.GENERIC:
            if self.generic is None:
                errors.append("Липсват настройки за общия парсер")
            else:
                errors.extend(self.generic.validate())
        for promo in self.manual_promos:
            errors.extend(f"Промокод „{promo.code}“: {e}" for e in promo.validate())
        return errors

    def to_dict(self) -> dict[str, object]:
        """Serialise to JSON compatible data."""
        data = asdict(self)
        data["kind"] = self.kind.value
        if self.generic is None:
            data.pop("generic")
        data["manual_promos"] = [p.to_dict() for p in self.manual_promos]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SiteConfig:
        """Deserialise; raises :class:`SiteConfigError` on malformed data."""
        try:
            generic_raw = data.get("generic")
            generic = None
            if isinstance(generic_raw, dict):
                selectors = GenericSelectors(**dict(generic_raw.get("selectors", {})))
                generic = GenericSiteSpec(
                    search_url=str(generic_raw.get("search_url", "")),
                    page_suffix=str(generic_raw.get("page_suffix", "")),
                    season_values={
                        str(k): str(v)
                        for k, v in dict(generic_raw.get("season_values", {})).items()
                    },
                    selectors=selectors,
                )
            return cls(
                id=str(data["id"]),
                name=str(data["name"]),
                kind=SiteKind(str(data["kind"])),
                base_url=str(data["base_url"]),
                enabled=bool(data.get("enabled", True)),
                builtin=bool(data.get("builtin", False)),
                parser=str(data.get("parser", "")),
                generic=generic,
                manual_promos=[
                    ManualPromo.from_dict(dict(item))
                    for item in data.get("manual_promos", []) or []  # type: ignore[union-attr]
                ],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SiteConfigError(f"Невалиден запис за сайт: {exc}") from exc


def default_sites() -> list[SiteConfig]:
    """The 12 built-in shops."""

    def builtin(sid: str, name: str, url: str) -> SiteConfig:
        return SiteConfig(sid, name, SiteKind.BUILTIN, url, builtin=True, parser=sid)

    def nk(sid: str, name: str, url: str) -> SiteConfig:
        return SiteConfig(sid, name, SiteKind.NK, url, builtin=True)

    return [
        builtin("emag", "eMAG", "https://www.emag.bg/"),
        builtin("diana", "Гуми Диана", "https://diana-ltd.com/"),
        builtin("gumi7", "Gumi7", "https://gumi7.com/bg/"),
        builtin("primex", "Примекс", "https://primex-bg.com/"),
        builtin("progumi", "ProGumi", "https://progumi.bg/"),
        nk("bggumi", "BG Gumi", "https://www.bggumi.com/"),
        builtin("supergumi", "SuperGumi", "https://www.supergumi.bg/"),
        nk("gumivarna", "Gumi-Varna", "https://www.gumi-varna.com/"),
        builtin("tirendo", "Tirendo", "https://www.tirendo.bg/"),
        builtin("gumi24", "24Gumi", "https://24gumi.bg/"),
        builtin("medinamed", "Медина-Мед", "https://medina-med.com/"),
        nk("gumi3", "Gumi3", "https://www.gumi3.com/"),
    ]


def build_scraper(site: SiteConfig, max_pages: int = 2) -> TyreScraper:
    """Instantiate the scraper for *site*."""
    errors = site.validate()
    if errors:
        raise SiteConfigError("; ".join(errors))
    if site.kind is SiteKind.BUILTIN:
        scraper = BUILTIN_PARSERS[site.parser]()
        scraper.name = site.name
        scraper.max_pages = max_pages
        return scraper
    if site.kind is SiteKind.NK:
        return NkPlatformScraper(site.name, site.base_url)
    assert site.generic is not None  # guaranteed by validate()
    return GenericScraper(site.name, site.base_url, site.generic, max_pages=max_pages)


def default_config_path() -> Path:
    """``<user config dir>/tyre-finder/sites.json``."""
    return Path(user_config_dir(APP_NAME, appauthor=False)) / "sites.json"


def slugify(name: str) -> str:
    """Make a config id from a display name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "site"


@dataclass(slots=True)
class SiteStore:
    """Loads and saves the list of sites."""

    path: Path = field(default_factory=default_config_path)

    def load(self) -> list[SiteConfig]:
        """Load sites; falls back to the defaults if the file is missing or broken."""
        if not self.path.exists():
            return default_sites()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            sites = [SiteConfig.from_dict(item) for item in raw["sites"]]
        except (OSError, json.JSONDecodeError, KeyError, TypeError, SiteConfigError) as exc:
            log.warning("Cannot read %s (%s); using defaults", self.path, exc)
            return default_sites()
        return sites

    def save(self, sites: list[SiteConfig]) -> None:
        """Validate and write *sites* atomically."""
        ids = [s.id for s in sites]
        if len(ids) != len(set(ids)):
            raise SiteConfigError("Има сайтове с еднакъв идентификатор")
        for site in sites:
            errors = site.validate()
            if errors:
                raise SiteConfigError(f"{site.name}: " + "; ".join(errors))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": CONFIG_VERSION, "sites": [s.to_dict() for s in sites]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        log.info("Saved %d sites to %s", len(sites), self.path)

    def reset(self) -> list[SiteConfig]:
        """Restore and persist the defaults."""
        sites = default_sites()
        self.save(sites)
        return sites
