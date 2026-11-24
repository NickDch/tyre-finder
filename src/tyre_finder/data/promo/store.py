"""JSON (de)serialisation of promo codes, the 6-hour cache and manual codes."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timedelta
from pathlib import Path

from platformdirs import user_cache_dir

from tyre_finder.data.brands import normalize_brand
from tyre_finder.models import Confidence, PromoCode, PromoOrigin

log = logging.getLogger(__name__)

_DATE_FIELDS = {"valid_from", "valid_until", "published_at"}


def promo_to_dict(promo: PromoCode) -> dict[str, object]:
    """JSON compatible dict."""
    data: dict[str, object] = {}
    for f in fields(PromoCode):
        value = getattr(promo, f.name)
        if isinstance(value, datetime | date):
            value = value.isoformat()
        elif isinstance(value, tuple):
            value = list(value)
        elif isinstance(value, PromoOrigin | Confidence):
            value = value.value
        data[f.name] = value
    return data


def promo_from_dict(data: dict[str, object]) -> PromoCode:
    """Inverse of :func:`promo_to_dict`; raises ValueError/KeyError/TypeError when malformed."""
    kwargs: dict[str, object] = dict(data)
    for name in _DATE_FIELDS:
        raw = kwargs.get(name)
        kwargs[name] = date.fromisoformat(str(raw)) if raw else None
    kwargs["fetched_at"] = datetime.fromisoformat(str(kwargs["fetched_at"]))
    kwargs["origin"] = PromoOrigin(str(kwargs["origin"]))
    kwargs["confidence"] = Confidence(str(kwargs.get("confidence", "high")))
    kwargs["brands"] = tuple(str(b) for b in kwargs.get("brands", []) or [])  # type: ignore[union-attr]
    known = {f.name for f in fields(PromoCode)}
    return PromoCode(**{k: v for k, v in kwargs.items() if k in known})  # type: ignore[arg-type]


def default_cache_path() -> Path:
    """``<user cache dir>/tyre-finder/promos.json``."""
    return Path(user_cache_dir("tyre-finder", appauthor=False)) / "promos.json"


@dataclass(slots=True)
class CachedLookup:
    """Cached result for one shop."""

    codes: list[PromoCode]
    checks: list[dict[str, object]]
    stored_at: datetime


@dataclass(slots=True)
class PromoCache:
    """Per-shop promo results with a TTL (default 6 h)."""

    path: Path = field(default_factory=default_cache_path)
    ttl: timedelta = timedelta(hours=6)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _read(self) -> dict[str, dict[str, object]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Promo cache unreadable (%s); ignoring", exc)
            return {}
        return raw if isinstance(raw, dict) else {}

    def get(self, key: str, now: datetime) -> CachedLookup | None:
        """Fresh cached entry or None."""
        with self._lock:
            entry = self._read().get(key)
        if not isinstance(entry, dict):
            return None
        try:
            stored = datetime.fromisoformat(str(entry["stored_at"]))
            if now - stored > self.ttl or stored > now + timedelta(minutes=5):
                return None
            codes = [promo_from_dict(c) for c in entry.get("codes", [])]  # type: ignore[union-attr]
            checks = list(entry.get("checks", []))  # type: ignore[call-overload]
        except (KeyError, TypeError, ValueError) as exc:
            log.info("Dropping bad cache entry %s: %s", key, exc)
            return None
        return CachedLookup(codes, checks, stored)

    def put(
        self, key: str, codes: list[PromoCode], checks: list[dict[str, object]], now: datetime
    ) -> None:
        """Store an entry (atomic file replace)."""
        with self._lock:
            data = self._read()
            data[key] = {
                "stored_at": now.isoformat(),
                "codes": [promo_to_dict(c) for c in codes],
                "checks": checks,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)

    def clear(self) -> None:
        """Forget everything."""
        with self._lock:
            self.path.unlink(missing_ok=True)


@dataclass(slots=True)
class ManualPromo:
    """A code the user typed in (stored with the site in sites.json)."""

    code: str = ""
    discount_percent: float | None = None
    discount_amount_eur: float | None = None
    min_order_eur: float | None = None
    min_quantity: int | None = None
    brands: list[str] = field(default_factory=list)  # display names as typed
    conditions: str = ""
    valid_until: str = ""  # ISO date or ""
    enabled: bool = True

    def validate(self) -> list[str]:
        """Bulgarian error messages."""
        errors: list[str] = []
        if not self.code.strip():
            errors.append("Въведете кода")
        if self.discount_percent is not None and not 0 < self.discount_percent < 100:
            errors.append("Процентът трябва да е между 0 и 100")
        if self.discount_amount_eur is not None and self.discount_amount_eur <= 0:
            errors.append("Сумата трябва да е положителна")
        if self.valid_until:
            try:
                date.fromisoformat(self.valid_until)
            except ValueError:
                errors.append("Невалидна дата (ГГГГ-ММ-ДД)")
        return errors

    def to_dict(self) -> dict[str, object]:
        """JSON data."""
        return {f.name: getattr(self, f.name) for f in fields(ManualPromo)}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ManualPromo:
        """Raises TypeError/ValueError on malformed data."""

        def opt_float(key: str) -> float | None:
            value = data.get(key)
            return None if value in (None, "") else float(value)  # type: ignore[arg-type]

        qty = data.get("min_quantity")
        return cls(
            code=str(data.get("code", "")),
            discount_percent=opt_float("discount_percent"),
            discount_amount_eur=opt_float("discount_amount_eur"),
            min_order_eur=opt_float("min_order_eur"),
            min_quantity=None if qty in (None, "") else int(qty),  # type: ignore[call-overload]
            brands=[str(b) for b in data.get("brands", []) or []],  # type: ignore[union-attr]
            conditions=str(data.get("conditions", "")),
            valid_until=str(data.get("valid_until", "") or ""),
            enabled=bool(data.get("enabled", True)),
        )

    def to_promo(self, shop: str, source_url: str, now: datetime) -> PromoCode:
        """As a high-confidence PromoCode."""
        return PromoCode(
            shop=shop,
            code=self.code.strip(),
            title=f"Ръчно въведен код {self.code.strip()}",
            origin=PromoOrigin.MANUAL,
            source_url=source_url,
            fetched_at=now,
            discount_percent=self.discount_percent,
            discount_amount_eur=self.discount_amount_eur,
            min_order_eur=self.min_order_eur,
            min_quantity=self.min_quantity,
            brands=tuple(normalize_brand(b) for b in self.brands if b.strip()),
            conditions=self.conditions,
            valid_until=date.fromisoformat(self.valid_until) if self.valid_until else None,
            confidence=Confidence.HIGH,
        )
