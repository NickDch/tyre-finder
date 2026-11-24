"""Core domain models shared by the data, logic and UI layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum, StrEnum

BGN_PER_EUR = 1.95583


class Season(StrEnum):
    """Tyre season."""

    SUMMER = "summer"
    WINTER = "winter"
    ALL_SEASON = "all_season"

    @property
    def label_bg(self) -> str:
        """Bulgarian label used in the UI."""
        return _SEASON_LABELS[self]


_SEASON_LABELS: dict[Season, str] = {
    Season.SUMMER: "Летни",
    Season.WINTER: "Зимни",
    Season.ALL_SEASON: "Всесезонни",
}


@dataclass(frozen=True, slots=True)
class TyreSize:
    """Tyre size, e.g. 205/55 R16."""

    width: int
    profile: int
    rim: int

    def __str__(self) -> str:
        return f"{self.width}/{self.profile} R{self.rim}"


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """What the user is searching for."""

    size: TyreSize
    season: Season


@dataclass(slots=True)
class TyreOffer:
    """A single tyre offer scraped from one shop."""

    shop: str
    brand: str
    model: str
    size: TyreSize
    season: Season | None
    price: float
    currency: str
    url: str
    image_url: str | None = None
    load_index: str | None = None
    speed_index: str | None = None
    ean: str | None = None
    raw_title: str = ""
    badges: tuple[str, ...] = ()
    promo: PromoPrice | None = None

    @property
    def effective_price_eur(self) -> float:
        """Per-tyre price used for comparison: the promo price when one applies."""
        if self.promo is not None and self.promo.compare_price_eur is not None:
            return self.promo.compare_price_eur
        return self.price_eur

    @property
    def price_eur(self) -> float:
        """Price converted to EUR (Bulgaria uses the euro; BGN at the fixed rate)."""
        if self.currency.upper() == "BGN":
            return round(self.price / BGN_PER_EUR, 2)
        return self.price

    @property
    def size_label(self) -> str:
        """Human readable size incl. load and speed index."""
        suffix = f" {self.load_index or ''}{self.speed_index or ''}".rstrip()
        return f"{self.size}{suffix}"


class SiteStatusKind(Enum):
    """Outcome of searching a single site."""

    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    EMPTY = "empty"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class SiteResult:
    """Result of searching one site."""

    shop: str
    status: SiteStatusKind
    offers: list[TyreOffer] = field(default_factory=list)
    message: str = ""
    elapsed_s: float = 0.0
    #: Longer explanation (shown in tooltips / the Sites dialog), if any.
    detail: str = ""


@dataclass(slots=True)
class TyreGroup:
    """The same tyre offered by one or more shops."""

    key: str
    brand: str
    model: str
    size_label: str
    season: Season | None
    offers: list[TyreOffer]

    @property
    def best_offer(self) -> TyreOffer:
        """Cheapest offer in the group (effective price, i.e. with a promo code if any)."""
        return min(self.offers, key=lambda o: o.effective_price_eur)

    @property
    def best_price(self) -> float:
        """Lowest effective price in the group."""
        return self.best_offer.effective_price_eur

    @property
    def max_price(self) -> float:
        """Highest effective price in the group."""
        return max(o.effective_price_eur for o in self.offers)

    @property
    def price_spread(self) -> float:
        """Difference between the most expensive and the cheapest offer."""
        return self.max_price - self.best_price

    @property
    def shop_count(self) -> int:
        """Number of distinct shops that offer this tyre."""
        return len({o.shop for o in self.offers})

    @property
    def sorted_offers(self) -> list[TyreOffer]:
        """Offers from cheapest to most expensive."""
        return sorted(self.offers, key=lambda o: o.effective_price_eur)

    @property
    def image_url(self) -> str | None:
        """First available product image."""
        best = self.best_offer
        if best.image_url:
            return best.image_url
        return next((o.image_url for o in self.offers if o.image_url), None)


# --------------------------------------------------------------------------- promo codes


class PromoOrigin(StrEnum):
    """Where a promo code was found."""

    SHOP = "shop"  # the shop's own promo/news pages
    BADGE = "badge"  # a badge on the product tile itself
    AGGREGATOR = "aggregator"  # BG coupon sites (kuponovo.bg, cuponeria.bg, ...)
    WEB = "web"  # open web search result
    MANUAL = "manual"  # entered by the user

    @property
    def label_bg(self) -> str:
        """Bulgarian label."""
        return _ORIGIN_LABELS[self]


_ORIGIN_LABELS: dict[PromoOrigin, str] = {
    PromoOrigin.SHOP: "сайта на магазина",
    PromoOrigin.BADGE: "етикет на продукта",
    PromoOrigin.AGGREGATOR: "сайт за купони",
    PromoOrigin.WEB: "търсене в интернет",
    PromoOrigin.MANUAL: "въведен ръчно",
}


class Confidence(StrEnum):
    """How sure we are that a code is real and current."""

    HIGH = "high"
    LOW = "low"  # shown as "възможен код", never applied unless the user allows it


@dataclass(slots=True)
class PromoCode:
    """A discount code (or code-less discount) for one shop.

    ``code`` is ``None`` when the discount needs no public code (card payment discount)
    or the code is personal/hidden (see ``code_note``).
    """

    shop: str
    code: str | None
    title: str
    origin: PromoOrigin
    source_url: str
    fetched_at: datetime
    discount_percent: float | None = None
    discount_amount_eur: float | None = None
    min_order_eur: float | None = None
    min_quantity: int | None = None
    brands: tuple[str, ...] = ()  # normalised brand keys; empty = all brands
    conditions: str = ""
    code_note: str = ""
    valid_from: date | None = None
    valid_until: date | None = None
    published_at: date | None = None
    confidence: Confidence = Confidence.HIGH
    score: float = 1.0
    applies_to_tyres: bool = True  # False when the conditions name other product groups
    selected_products_only: bool = False  # "на избрани продукти" - cannot be computed

    @property
    def key(self) -> str:
        """Identity used to de-duplicate the same code from several sources."""
        ident = (self.code or self.title).strip().upper()
        return f"{self.shop}|{ident}"

    @property
    def discount_label(self) -> str:
        """'-6%' / '-10.00 €' / ''."""
        if self.discount_percent is not None:
            return f"-{self.discount_percent:g}%"
        if self.discount_amount_eur is not None:
            return f"-{self.discount_amount_eur:.2f} €"
        return ""


@dataclass(slots=True)
class PromoPrice:
    """A promo code applied to one offer."""

    promo: PromoCode
    unit_price_eur: float | None  # per tyre, when the discount applies to a single tyre
    set4_total_eur: float | None  # total for 4 tyres with the code
    note: str = ""

    @property
    def compare_price_eur(self) -> float | None:
        """Per-tyre price for comparisons (set-of-4 total / 4 when only that applies)."""
        if self.unit_price_eur is not None:
            return self.unit_price_eur
        if self.set4_total_eur is not None:
            return round(self.set4_total_eur / 4, 2)
        return None
