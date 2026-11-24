"""Offscreen smoke tests for the Qt UI (no network)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from datetime import date, datetime, timedelta

from PySide6.QtCore import QSettings

from tyre_finder.app import create_app
from tyre_finder.data.promo.service import ShopPromoResult
from tyre_finder.data.promo.settings import PromoSettingsStore
from tyre_finder.data.promo.store import ManualPromo, PromoCache
from tyre_finder.data.site_config import SiteKind, SiteStore
from tyre_finder.models import (
    Confidence,
    PromoCode,
    PromoOrigin,
    SearchQuery,
    Season,
    SiteResult,
    SiteStatusKind,
    TyreOffer,
    TyreSize,
)
from tyre_finder.ui.main_window import MainWindow
from tyre_finder.ui.promo_dialogs import (
    ManualPromoEditDialog,
    PromoOverviewDialog,
    PromoSettingsDialog,
    overview_html,
)
from tyre_finder.ui.sites_dialog import SiteEditDialog, SitesDialog
from tyre_finder.ui.theme import PALETTES, ThemeName
from tyre_finder.ui.widgets import OfferRow, PromoLine, ResultCard


@pytest.fixture
def window(tmp_path):
    create_app([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = MainWindow(
        store=SiteStore(tmp_path / "sites.json"),
        settings=settings,
        promo_store=PromoSettingsStore(tmp_path / "promo.json"),
        promo_cache=PromoCache(tmp_path / "promo-cache.json", ttl=timedelta(hours=6)),
    )
    yield win
    win.close()


def _offer(shop: str, price: float) -> TyreOffer:
    return TyreOffer(
        shop,
        "Michelin",
        "Primacy 4",
        TyreSize(205, 55, 16),
        Season.SUMMER,
        price,
        "EUR",
        f"https://{shop}.bg/p",
        load_index="91",
        speed_index="V",
    )


def test_results_grouped_and_filtered(window) -> None:
    query = SearchQuery(TyreSize(205, 55, 16), Season.SUMMER)
    results = [
        SiteResult("a", SiteStatusKind.OK, [_offer("a", 100.0)]),
        SiteResult("b", SiteStatusKind.OK, [_offer("b", 95.0)]),
        SiteResult("c", SiteStatusKind.ERROR, message="HTTP 511"),
    ]
    window.load_offers_for_preview(query, results)
    assert len(window._groups) == 1
    assert window._groups[0].best_offer.shop == "b"
    assert "1 модела" in window._results_info.text()
    window.set_theme(ThemeName.DARK)
    window._min_price.setValue(120)
    window._refresh_results()
    assert window._visible == []


def test_sites_dialog_opens(window, tmp_path) -> None:
    dlg = SitesDialog(
        window,
        SiteStore(tmp_path / "s.json"),
        window._sites,
        PALETTES[ThemeName.LIGHT],
        window.current_query(),
    )
    assert dlg.table.rowCount() == 12
    dlg.close()


def test_combo_values_roundtrip(window) -> None:
    window._season.setCurrentIndex(window._season.findData(Season.WINTER.value))
    assert window.current_query().season is Season.WINTER
    assert window.criteria().sort.value == "price_asc"


def test_site_edit_dialog_generic_box(window) -> None:
    dlg = SiteEditDialog(window, None, set(), window.current_query())
    dlg.kind.setCurrentIndex(dlg.kind.findData(SiteKind.GENERIC.value))
    assert not dlg.generic_box.isHidden()
    dlg.name.setText("Тест")
    dlg.url.setText("https://www.bggumi.com/")
    site = dlg.build_site()
    assert site.kind is SiteKind.GENERIC
    assert site.validate()  # selectors still empty -> errors shown


def _promo(shop: str, **kw: object) -> PromoCode:
    base: dict[str, object] = {
        "shop": shop,
        "code": "TYRE6",
        "title": "Код TYRE6",
        "origin": PromoOrigin.SHOP,
        "source_url": "https://a.bg/promo",
        "fetched_at": datetime(2026, 11, 23, 12),
        "discount_percent": 6.0,
        "valid_until": date(2026, 11, 30),
    }
    base.update(kw)
    return PromoCode(**base)  # type: ignore[arg-type]


def test_promo_changes_best_offer_and_toggle(window) -> None:
    query = SearchQuery(TyreSize(205, 55, 16), Season.SUMMER)
    results = [
        SiteResult("a", SiteStatusKind.OK, [_offer("a", 100.0)]),
        SiteResult("b", SiteStatusKind.OK, [_offer("b", 97.0)]),
    ]
    possible = _promo("b", code="MAYBE5", confidence=Confidence.LOW, origin=PromoOrigin.WEB)
    promos = {
        "a": ShopPromoResult("a", codes=[_promo("a")]),
        "b": ShopPromoResult("b", codes=[possible]),
    }
    window.load_offers_for_preview(query, results, promos)
    assert window._groups[0].best_offer.shop == "a"
    assert window._groups[0].best_price == 94.0
    card = window._cards.itemAt(0).widget()
    assert isinstance(card, ResultCard)
    card.set_expanded(True, animate=False)
    rows = card.findChildren(OfferRow)
    assert len(rows) == 2
    lines = card.findChildren(PromoLine)
    assert len(lines) == 2  # applied code for "a" + possible code for "b"
    assert "2 кода" not in window._promo_status.text()
    window._use_promo.setChecked(False)
    window._refresh_results()
    assert window._groups[0].best_offer.shop == "b"
    window._apply_possible.setChecked(True)
    window._use_promo.setChecked(True)
    window._refresh_results()
    assert window._groups[0].best_offer.shop == "b"  # 97 * 0.94 < 94
    html = overview_html(promos, ["a", "b", "c"])
    assert "TYRE6" in html and "възможен код" in html and "Търсене" in html


def test_promo_dialogs(window, tmp_path) -> None:
    dlg = PromoOverviewDialog(window, {}, ["a"], PALETTES[ThemeName.LIGHT])
    assert "Няма" in dlg.browser.toPlainText() or "Търсене" in dlg.browser.toPlainText()
    store = PromoSettingsStore(tmp_path / "ps.json")
    sdlg = PromoSettingsDialog(window, store, store.load())
    sdlg.google_key.setText("KEY")
    sdlg.engine.setCurrentIndex(sdlg.engine.findData("google"))
    sdlg._save()
    assert "CX" in sdlg.error.text()  # CX missing -> not saved
    sdlg.google_cx.setText("CX1")
    sdlg._save()
    assert store.load().google_cx == "CX1"
    edit = ManualPromoEditDialog(window, ManualPromo(code="A5", discount_percent=5))
    assert edit.build().discount_percent == 5
    edit.code.setText("")
    edit._accept()
    assert "кода" in edit.error.text()
