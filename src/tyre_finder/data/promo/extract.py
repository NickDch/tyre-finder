"""Extract promo codes, discounts and conditions from free text.

Used for the shops' own promo pages, aggregator descriptions and open-web pages.
Nothing is invented: every value comes from the analysed text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from tyre_finder.data.brands import KNOWN_BRANDS, normalize_brand
from tyre_finder.data.promo.dates import DateKind, find_dates
from tyre_finder.models import BGN_PER_EUR

_KEYWORD = (
    r"(?:промо\s*-?\s*код(?:а|ът)?|промокод(?:а|ът)?|код(?:а|ът)?\s+за\s+(?:отстъпка|намаление)"
    r"|код(?:а|ът)?|купон(?:а|ът)?|ваучер(?:а|ът)?|promo\s*code|coupon(?:\s*code)?|voucher"
    r"|discount\s*code|code)"
)
# keyword, optional punctuation/quotes, then the code itself
_STRONG_RE = re.compile(
    rf"(?<![\w-]){_KEYWORD}\s*(?:[:\-–—]\s*)?[„\"“”'«»]?\s*(?P<code>[A-Za-z0-9][A-Za-z0-9_-]{{2,23}})"
    r"(?=[\s„\"“”'«».,;:!?)\]]|$)",
    re.IGNORECASE,
)
_KEYWORD_RE = re.compile(_KEYWORD, re.IGNORECASE)
_TOKEN_RE = re.compile(r"(?<![\w/-])(?P<code>[A-Z0-9][A-Z0-9_-]{3,23})(?![\w-])")

# Words that look like codes but are not.
STOPWORDS = frozenset(
    {
        "EUR",
        "BGN",
        "DOT",
        "SUV",
        "XL",
        "RF",
        "RFT",
        "ROF",
        "SSR",
        "MS",
        "BLACK",
        "FRIDAY",
        "CYBER",
        "MONDAY",
        "PROMO",
        "CODE",
        "SALE",
        "FREE",
        "TOP",
        "NEW",
        "HTTP",
        "HTTPS",
        "WWW",
        "HTML",
        "ONLINE",
        "SHOP",
        "SMS",
        "VIBER",
        "PREMIUM",
        "OFF",
        "ROAD",
        "TYRES",
        "TIRES",
        "GUMI",
        "LIDL",
        "PLUS",
        "APP",
        "VAT",
        "DDS",
        "EMAG",
        "GENIUS",
        "EASYBOX",
        "IUTE",
        "TBI",
        "BNPL",
        "COM",
        "BG",
        "THE",
        "AND",
        "FOR",
        "WITH",
        "YOUR",
        "AT",
        "ON",
        "IN",
        "BY",
    }
)
_SIZE_LIKE_RE = re.compile(
    r"^\d{3}[-/]?\d{2}[-/]?Z?R?F?\d{2}$|^\d{2}Z?R\d{2}$|^R\d{2}$|^\d+$|^\d{2,3}[A-Z]{1,2}$"
)

_PERCENT_RE = re.compile(r"(?<![\d.,])-?\s?(?P<v>\d{1,2}(?:[.,]\d{1,2})?)\s?%")
_AMOUNT_RE = re.compile(
    r"(?<![\d.,])-?\s?(?P<v>\d{1,4}(?:[.,]\d{1,2})?)\s?(?P<cur>€|евро|eur\b|лв\.?|лева|bgn\b)",
    re.IGNORECASE,
)
_MIN_ORDER_RE = re.compile(
    r"(?:поръчк|покупк|пазаруван|кошниц|order)\w*\s+(?:на\s+стойност\s+|с\s+обща\s+стойност\s+)?"
    r"(?:над|от|минимум|min\.?|над\s+сума)\s+(?P<v>\d{1,5}(?:[.,]\d{1,2})?)\s?"
    r"(?P<cur>€|евро|eur\b|лв\.?|лева|bgn\b)",
    re.IGNORECASE,
)
_QTY_RE = re.compile(
    r"(?:минимум|поне|при\s+покупка\s+на|комплект\s+от|покупка\s+на|купи|купете|от)\s+(?P<n>\d|две|четири|2|4)"
    r"\s*(?:бр\.?|броя)?\s*(?:\w+\s+){0,3}?(?:гуми|гума|броя)",
    re.IGNORECASE,
)
_SELECTED_RE = re.compile(r"избрани\s+(?:продукти|артикули|модели|гуми|стоки|категории)", re.I)
_UP_TO_RE = re.compile(r"(?:\bдо|up\s+to)\s*-?\s*\d{1,2}(?:[.,]\d+)?\s?%", re.IGNORECASE)
_TYRE_RE = re.compile(r"гум|шин|tyre|tire|автомобил|джант", re.IGNORECASE)
_NOT_TYRE_RE = re.compile(
    r"електро|смарт|\bIT\b|четки|Oral-B|Pampers|Whiskas|телевизор|смартфон|лаптоп|"
    r"парфюм|козметик|играчк|дрех|обувк|аудио|грил|тиган|мултикукър|препарат|храна за",
    re.IGNORECASE,
)
_SERVICES_RE = re.compile(r"монтаж|демонтаж|баланс|услуг", re.IGNORECASE)
_NEWSLETTER_RE = re.compile(r"бюлетин|newsletter|абонира", re.IGNORECASE)
_PERSONAL_RE = re.compile(r"Lidl\s*Plus|личен\s+код|своя\s+код|твоя\s+код|в\s+приложението", re.I)

_AMBIGUOUS_BRANDS = frozenset({"EVENT", "ATLAS", "DYNAMO", "FEDERAL", "DIPLOMAT", "EVERGREEN"})
_BRAND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"(?<![\w-]){re.escape(b)}(?![\w-])", re.IGNORECASE), normalize_brand(b))
    for b in sorted(KNOWN_BRANDS, key=len, reverse=True)
    if normalize_brand(b) not in _AMBIGUOUS_BRANDS
]
_NUM_WORDS = {"две": 2, "четири": 4}


def _to_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def _to_eur(value: float, currency: str) -> float:
    cur = currency.lower().rstrip(".")
    if cur in {"лв", "лева", "bgn"}:
        return round(value / BGN_PER_EUR, 2)
    return value


@dataclass(slots=True)
class Terms:
    """Discount terms found in a text."""

    percent: float | None = None
    amount_eur: float | None = None
    min_order_eur: float | None = None
    min_quantity: int | None = None
    brands: tuple[str, ...] = ()
    valid_from: date | None = None
    valid_until: date | None = None
    other_dates: list[date] = field(default_factory=list)
    selected_only: bool = False
    applies_to_tyres: bool = True
    services_only: bool = False
    newsletter: bool = False
    personal_code: bool = False


def brands_in_text(text: str) -> tuple[str, ...]:
    """Normalised keys of the tyre brands named in *text* (in order of appearance)."""
    hits: list[tuple[int, str]] = []
    spans: list[tuple[int, int]] = []
    for pattern, key in _BRAND_PATTERNS:
        for m in pattern.finditer(text):
            if any(a <= m.start() < b for a, b in spans):
                continue
            spans.append(m.span())
            hits.append((m.start(), key))
    seen: dict[str, None] = {}
    for _, key in sorted(hits):
        seen.setdefault(key, None)
    return tuple(seen)


def parse_terms(text: str, *, general_store: bool = False) -> Terms:
    """Discount, min order, quantity, brands, dates and scope found in *text*.

    ``general_store``: the shop sells more than tyres (eMAG) - a discount is only
    considered tyre related when the text mentions tyres.
    """
    terms = Terms()
    m = _MIN_ORDER_RE.search(text)
    min_span = m.span() if m else (-1, -1)
    if m:
        terms.min_order_eur = _to_eur(_to_float(m.group("v")), m.group("cur"))
    pm = _PERCENT_RE.search(text)
    if pm:
        terms.percent = _to_float(pm.group("v"))
    else:
        for am in _AMOUNT_RE.finditer(text):
            if min_span[0] <= am.start() < min_span[1]:
                continue
            terms.amount_eur = _to_eur(_to_float(am.group("v")), am.group("cur"))
            break
    qm = _QTY_RE.search(text)
    if qm:
        raw = qm.group("n").lower()
        qty = _NUM_WORDS.get(raw) or int(raw)
        if qty > 1:
            terms.min_quantity = qty
    terms.brands = brands_in_text(text)
    for found in find_dates(text):
        if found.kind is DateKind.UNTIL:
            if terms.valid_until is None:  # the first expiry belongs to the code's sentence
                terms.valid_until = found.value
        elif found.kind is DateKind.PERIOD_START:
            terms.valid_from = terms.valid_from or found.value
        else:
            terms.other_dates.append(found.value)
    terms.selected_only = (bool(_SELECTED_RE.search(text)) and not terms.brands) or bool(
        _UP_TO_RE.search(text)
    )
    mentions_tyres = bool(_TYRE_RE.search(text))
    if general_store:
        terms.applies_to_tyres = mentions_tyres
    elif _NOT_TYRE_RE.search(text) and not mentions_tyres:
        terms.applies_to_tyres = False
    terms.services_only = bool(_SERVICES_RE.search(text)) and "гуми" not in _strip_services(text)
    terms.newsletter = bool(_NEWSLETTER_RE.search(text))
    terms.personal_code = bool(_PERSONAL_RE.search(text))
    return terms


def _strip_services(text: str) -> str:
    """Text without 'монтаж/баланс на гуми' phrases (so 'гуми' there does not count)."""
    return re.sub(
        r"(?:монтаж|демонтаж|баланс)\w*(?:\s*(?:,|и)\s*(?:монтаж|демонтаж|баланс)\w*)*\s+на\s+гуми",
        "",
        text,
        flags=re.IGNORECASE,
    ).lower()


def looks_like_code(token: str) -> bool:
    """Heuristic: promo codes are 3-24 latin letters/digits, not common words or sizes."""
    t = token.strip("-_")
    if len(t) < 3 or t.upper() in STOPWORDS or _SIZE_LIKE_RE.match(t.upper()):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_-]+", t):
        return False
    has_digit = any(c.isdigit() for c in t)
    has_alpha = any(c.isalpha() for c in t)
    if not has_alpha:
        return False
    # lower-case dictionary words ("code here") are not codes; codes are upper/mixed with digits
    return has_digit or t.isupper() or (any(c.isupper() for c in t[1:]) and len(t) >= 5)


@dataclass(frozen=True, slots=True)
class CodeCandidate:
    """A code-like token with the text window around it."""

    code: str
    position: int
    strong: bool  # directly after a keyword such as "код:" / "промокод"
    window: str


def find_code_candidates(text: str, window: int = 220) -> list[CodeCandidate]:
    """Codes right after a keyword (strong) or code-like tokens near a keyword (weak)."""
    out: dict[str, CodeCandidate] = {}
    for m in _STRONG_RE.finditer(text):
        code = m.group("code")
        if looks_like_code(code):
            key = code.upper()
            if key not in out or not out[key].strong:
                out[key] = CodeCandidate(code, m.start("code"), True, _window(text, m, window))
    keyword_positions = [k.start() for k in _KEYWORD_RE.finditer(text)]
    for m in _TOKEN_RE.finditer(text):
        code = m.group("code")
        key = code.upper()
        if key in out or not looks_like_code(code) or not any(c.isdigit() for c in code):
            continue
        if any(abs(m.start() - p) <= 80 for p in keyword_positions):
            out[key] = CodeCandidate(code, m.start(), False, _window(text, m, window))
    return sorted(out.values(), key=lambda c: c.position)


_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)|\n")


def _window(text: str, m: re.Match[str], size: int) -> str:
    """The sentence with the code plus the next one (bounded by *size* characters)."""
    lo = max(0, m.start() - size)
    start = lo
    for end in _SENTENCE_END_RE.finditer(text, lo, m.start()):
        start = end.end()
    stop = min(len(text), m.end() + size)
    ends = list(_SENTENCE_END_RE.finditer(text, m.end(), stop))
    if len(ends) >= 2:
        stop = ends[1].end()
    elif ends and not _SENTENCE_END_RE.search(text, ends[0].end(), stop):
        stop = min(stop, len(text))
    return " ".join(text[start:stop].split())


def shop_context(text: str, position: int, size: int = 250) -> str:
    """Wider context (for "is the shop mentioned?"): up to *size* chars around."""
    return text[max(0, position - size) : position + size]


def mentions_shop(text: str, names: tuple[str, ...]) -> bool:
    """True when the shop name or domain occurs in *text*."""
    low = text.lower()
    return any(n and n.lower() in low for n in names)


def score_candidate(
    cand: CodeCandidate,
    terms: Terms,
    shop_names: tuple[str, ...],
    *,
    current_date_found: bool,
) -> float:
    """Confidence score 0..1 for an open-web candidate."""
    score = 0.0
    if cand.strong:
        score += 0.45
    if mentions_shop(cand.window, shop_names):
        score += 0.25
    if terms.percent is not None or terms.amount_eur is not None:
        score += 0.15
    if current_date_found:
        score += 0.15
    if any(c.isdigit() for c in cand.code) and any(c.isalpha() for c in cand.code):
        score += 0.05
    return min(score, 1.0)
