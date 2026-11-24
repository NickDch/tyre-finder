"""Known tyre brands and aliases used for splitting titles and normalisation."""

from __future__ import annotations

import re

# Canonical display names. Multi-word names must be listed so that titles such as
# "BF GOODRICH G-GRIP" are split correctly into brand and model.
KNOWN_BRANDS: tuple[str, ...] = (
    "Accelera",
    "Aeolus",
    "Aoteli",
    "Aplus",
    "Apollo",
    "Arivo",
    "Atlas",
    "Austone",
    "Autogreen",
    "Avon",
    "Barum",
    "BFGoodrich",
    "Bridgestone",
    "Ceat",
    "Continental",
    "Cooper",
    "Davanti",
    "Dayton",
    "Debica",
    "Delinte",
    "Diplomat",
    "Double Coin",
    "Dunlop",
    "Dynamo",
    "Effiplus",
    "Esa-Tecar",
    "Event",
    "Evergreen",
    "Falken",
    "Federal",
    "Firemax",
    "Firestone",
    "Fortuna",
    "Fortune",
    "Fulda",
    "General Tire",
    "Gislaved",
    "Giti",
    "Goodride",
    "Goodyear",
    "Grenlander",
    "Gripmax",
    "GT Radial",
    "Hankook",
    "Headway",
    "Hifly",
    "Imperial",
    "Infinity",
    "Kelly",
    "Kenda",
    "Kingstar",
    "Kleber",
    "Kormoran",
    "Kumho",
    "Landsail",
    "Landspider",
    "Lassa",
    "Laufenn",
    "Leao",
    "Linglong",
    "Marangoni",
    "Mastercraft",
    "Matador",
    "Maxxis",
    "Mazzini",
    "Michelin",
    "Milestone",
    "Minerva",
    "Mirage",
    "Momo",
    "Nankang",
    "Nexen",
    "Nokian",
    "Nordexx",
    "Nova Force",
    "Novex",
    "Onyx",
    "Ovation",
    "Petlas",
    "Pirelli",
    "Platin",
    "Point S",
    "Powertrac",
    "Premiorri",
    "Radar",
    "Rapid",
    "Riken",
    "RoadX",
    "Roadhog",
    "Roadstone",
    "Rotalla",
    "Rovelo",
    "Royal Black",
    "Sailun",
    "Sava",
    "Semperit",
    "Sonix",
    "Star Performer",
    "Starmaxx",
    "Sumitomo",
    "Sunny",
    "Superia",
    "Syron",
    "Taurus",
    "Tercelo",
    "Tigar",
    "Tomket",
    "Toyo",
    "Tracmax",
    "Triangle",
    "Tristar",
    "Unigrip",
    "Uniroyal",
    "Viking",
    "Vredestein",
    "Wanli",
    "Westlake",
    "Windforce",
    "Yokohama",
    "Zeetex",
    "Zmax",
    "Rauffan",
    "Torque",
    "Three-A",
    "Kapsen",
    "Habilead",
    "Comforser",
    "Hilo",
    "Firenza",
    "Antares",
    "Ilink",
    "Kinforest",
    "Lanvigator",
    "Duraturn",
    "Delmax",
    "Doublestar",
    "Chengshan",
    "Joyroad",
    "Haida",
    "Compasal",
    "Sunfull",
    "Saferich",
    "Mazzini",
    "Ecovision",
    "Rockblade",
    "Massimo",
    "Atturo",
    "Bars",
)

# Normalised alias -> canonical normalised brand.
BRAND_ALIASES: dict[str, str] = {
    "BFGOODRICH": "BFGOODRICH",
    "BFG": "BFGOODRICH",
    "GOODYEAR": "GOODYEAR",
    "COOPERTIRES": "COOPER",
    "GENERAL": "GENERALTIRE",
    "GENERALTIRES": "GENERALTIRE",
    "GTRADIAL": "GTRADIAL",
    "GT": "GTRADIAL",
    "NOKIANTYRES": "NOKIAN",
    "STARPERFORMER": "STARPERFORMER",
    "POINTS": "POINTS",
    "ESATECAR": "ESATECAR",
    "THREEA": "THREEA",
    "3A": "THREEA",
}

# Extra spellings that appear in shop titles, mapped to the canonical display name.
_TITLE_SPELLINGS: dict[str, str] = {
    "BF GOODRICH": "BFGoodrich",
    "B.F. GOODRICH": "BFGoodrich",
    "GOOD YEAR": "Goodyear",
    "COOPER TIRES": "Cooper",
    "NOKIAN TYRES": "Nokian",
    "GENERAL TIRES": "General Tire",
    "GENERAL": "General Tire",
    "ROAD X": "RoadX",
    "ESA TECAR": "Esa-Tecar",
    "GITISYNERGY": "Giti",
}


def normalize_brand(brand: str) -> str:
    """Return a canonical, comparison-friendly brand key (upper case, alnum only)."""
    key = re.sub(r"[^0-9A-Z]", "", brand.upper())
    return BRAND_ALIASES.get(key, key)


def _brand_patterns() -> list[tuple[str, str]]:
    spellings: dict[str, str] = {b.upper(): b for b in KNOWN_BRANDS}
    spellings.update(_TITLE_SPELLINGS)
    # Longest first so that "GT RADIAL" wins over "GT".
    return sorted(spellings.items(), key=lambda kv: len(kv[0]), reverse=True)


_PATTERNS = _brand_patterns()


def split_brand_model(title: str) -> tuple[str, str]:
    """Split "BRAND MODEL ..." into (brand, model) using the known brand list.

    Falls back to the first word when the brand is unknown.
    """
    text = " ".join(title.split())
    upper = text.upper()
    for spelling, canonical in _PATTERNS:
        if upper == spelling or upper.startswith(spelling + " "):
            return canonical, text[len(spelling) :].strip()
    first, _, rest = text.partition(" ")
    return first, rest.strip()


def display_brand(brand: str) -> str:
    """Return a nice display name for a brand as written by a shop."""
    key = normalize_brand(brand)
    for known in KNOWN_BRANDS:
        if normalize_brand(known) == key:
            return known
    return brand.strip().upper() if brand.isupper() or brand.islower() else brand.strip()
