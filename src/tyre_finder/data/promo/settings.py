"""Promo lookup settings incl. the user's search API keys (stored only in the user config)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from enum import StrEnum
from pathlib import Path

from platformdirs import user_config_dir

log = logging.getLogger(__name__)


class EngineChoice(StrEnum):
    """Which web search engine to use."""

    AUTO = "auto"  # Google CSE if configured, then Brave if configured, then Bing, DuckDuckGo
    GOOGLE = "google"
    BRAVE = "brave"
    BING = "bing"
    DUCKDUCKGO = "ddg"
    OFF = "off"

    @property
    def label_bg(self) -> str:
        """Bulgarian label."""
        return _ENGINE_LABELS[self]


_ENGINE_LABELS: dict[EngineChoice, str] = {
    EngineChoice.AUTO: "Автоматично (Google → Brave → Bing → DuckDuckGo)",
    EngineChoice.GOOGLE: "Google Programmable Search (API ключ + CX)",
    EngineChoice.BRAVE: "Brave Search API (ключ)",
    EngineChoice.BING: "Bing (без ключ)",
    EngineChoice.DUCKDUCKGO: "DuckDuckGo (без ключ)",
    EngineChoice.OFF: "Без търсене в интернет",
}


@dataclass(slots=True)
class PromoSettings:
    """User preferences for promo codes."""

    enabled: bool = True
    use_aggregators: bool = True
    engine: EngineChoice = EngineChoice.AUTO
    google_api_key: str = ""
    google_cx: str = ""
    brave_api_key: str = ""
    window_days: int = 30
    cache_hours: float = 6.0
    apply_possible: bool = False  # apply low-confidence ("възможен код") codes too
    max_pages_per_shop: int = 3

    @property
    def google_configured(self) -> bool:
        """Both Google values are set."""
        return bool(self.google_api_key.strip() and self.google_cx.strip())

    def signature(self) -> str:
        """Cache key part: results depend on these values (not on secrets themselves)."""
        return (
            f"{self.engine.value}|g{int(self.google_configured)}|b{int(bool(self.brave_api_key))}"
            f"|w{self.window_days}|a{int(self.use_aggregators)}"
        )

    def to_dict(self) -> dict[str, object]:
        """JSON data."""
        data = asdict(self)
        data["engine"] = self.engine.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> PromoSettings:
        """Tolerant loader: unknown keys ignored, bad values replaced by defaults."""
        defaults = cls()
        kwargs: dict[str, object] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            default = getattr(defaults, f.name)
            try:
                if f.name == "engine":
                    kwargs[f.name] = EngineChoice(str(value))
                elif isinstance(default, bool):
                    kwargs[f.name] = bool(value)
                elif isinstance(default, int):
                    kwargs[f.name] = max(1, int(value))  # type: ignore[arg-type]
                elif isinstance(default, float):
                    kwargs[f.name] = max(0.0, float(value))  # type: ignore[arg-type]
                else:
                    kwargs[f.name] = str(value)
            except (TypeError, ValueError):
                log.warning("Ignoring bad promo setting %s=%r", f.name, value)
        return cls(**kwargs)  # type: ignore[arg-type]


def default_settings_path() -> Path:
    """``<user config dir>/tyre-finder/promo_settings.json``."""
    return Path(user_config_dir("tyre-finder", appauthor=False)) / "promo_settings.json"


@dataclass(slots=True)
class PromoSettingsStore:
    """Loads/saves :class:`PromoSettings`."""

    path: Path = field(default_factory=default_settings_path)

    def load(self) -> PromoSettings:
        """Settings or defaults."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return PromoSettings()
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Cannot read %s (%s); using defaults", self.path, exc)
            return PromoSettings()
        return PromoSettings.from_dict(raw if isinstance(raw, dict) else {})

    def save(self, settings: PromoSettings) -> None:
        """Atomic write (the file may contain API keys: user-only permissions)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), "utf-8")
        try:
            tmp.chmod(0o600)
        except OSError:
            log.debug("chmod not supported for %s", tmp)
        tmp.replace(self.path)
