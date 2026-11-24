"""Normalisation of brand and model names so that offers from different shops match."""

from __future__ import annotations

import re

from tyre_finder.data.brands import normalize_brand
from tyre_finder.models import TyreOffer

# Marks that describe the variant/label rather than the tread pattern.
_NOISE_PATTERNS: tuple[str, ...] = (
    r"\bXL\b",
    r"\bEXTRA\s*LOAD\b",
    r"\bREINF(?:ORCED)?\b",
    r"\bRF\b",
    r"\bFR\b",
    r"\bMFS\b",
    r"\bFP\b",
    r"\bM\s*\+\s*S\b",
    r"\bM/S\b",
    r"\bMS\b",
    r"\b3PMSF\b",
    r"\bTL\b",
    r"\bDOT\s*\d{2,4}(?:/\d{2,4})?\b",
    r"\(\s*HB\s*\)",
    r"\bECE[-\s]?\w*\b",
    r"\bTUBELESS\b",
    r"\bZR\b",
    r"(?<=\d)XL\b",
    r"\bС\s*БОРД\b",
    r"\bБОРД\b",
    r"\bГУМ[АИ]\b",
    r"\bЛЕТН[АИ]\b",
    r"\bЛЯТНА\b",
    r"\bЗИМН[АИ]\b",
    r"\bВСЕСЕЗОНН[АИ]\b",
    r"\b\d{2,3}(?:/\d{2,3})?[A-HJ-NP-Z]\b",  # load/speed index such as 91V
    r"\b\d{3}\s*/\s*\d{2}\s*Z?R\s*\d{2}C?\b",  # embedded size
)
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)
# Run-flat versions are different products: removed from the model key but kept as a flag.
_RUNFLAT_RE = re.compile(
    r"\b(?:RFT|RUN\s*FLAT|RUNFLAT|ROF|SSR|ZP|DSST|EMT|HRS|SEAL(?:INSIDE)?)\b", re.IGNORECASE
)
_SPLIT_RE = re.compile(r"[A-Z]+|\d+")


def _strip_brand_prefix(model: str, brand_key: str) -> str:
    compact = re.sub(r"[^0-9A-Z]", "", model)
    if brand_key and compact.startswith(brand_key) and len(compact) > len(brand_key):
        # remove the brand letters from the beginning, keeping the rest intact
        removed = 0
        out = []
        for ch in model:
            if removed < len(brand_key) and ch.isalnum():
                removed += 1
                continue
            if removed >= len(brand_key):
                out.append(ch)
        return "".join(out)
    return model


def clean_model(model: str, brand: str = "") -> str:
    """Upper-case model with noise words removed, e.g. 'Ventus Prime 4 K135'."""
    text = _RUNFLAT_RE.sub(" ", model.upper())
    text = _NOISE_RE.sub(" ", text)
    text = text.replace("+", " PLUS ")
    text = _strip_brand_prefix(text.strip(), normalize_brand(brand))
    return " ".join(text.split())


def model_compact_key(model: str, brand: str = "") -> str:
    """'PremiumContact 7' and 'PREMIUM CONTACT 7' -> 'PREMIUMCONTACT7'."""
    return re.sub(r"[^0-9A-Z]", "", clean_model(model, brand))


def keys_compatible(short: str, long: str) -> bool:
    """Lenient match: 'Z107' vs 'ZUPERECOZ107', 'SP702' vs 'SP702ZR', 'PRIMACY5' vs
    'PRIMACY5ENERGY'. The shorter key must contain a digit and at least 4 chars."""
    if short == long:
        return True
    if len(short) > len(long):
        short, long = long, short
    if len(short) < 4 or not any(ch.isdigit() for ch in short):
        return False
    return long.startswith(short) or long.endswith(short)


def model_token_key(model: str, brand: str = "") -> str:
    """Order independent key: 'K135 Ventus Prime 4' == 'Ventus Prime4 K135'."""
    tokens: list[str] = []
    for word in re.split(r"[^0-9A-Z]+", clean_model(model, brand)):
        tokens.extend(_SPLIT_RE.findall(word))
    return " ".join(sorted(tokens))


def is_runflat(text: str) -> bool:
    """True if the title/model marks a run-flat (or self-sealing) tyre."""
    return bool(_RUNFLAT_RE.search(text))


def size_key(offer: TyreOffer) -> str:
    """Size part of the matching key."""
    s = offer.size
    return f"{s.width}/{s.profile}R{s.rim}"


def bucket_key(offer: TyreOffer) -> tuple[str, str, str, str]:
    """Offers can only match inside the same brand + size(+RF) + load/speed bucket."""
    runflat = "RF" if is_runflat(f"{offer.model} {offer.raw_title}") else ""
    return (
        normalize_brand(offer.brand),
        size_key(offer) + runflat,
        (offer.load_index or "").strip(),
        (offer.speed_index or "").upper().strip(),
    )
