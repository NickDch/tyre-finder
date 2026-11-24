"""Render the main window offscreen with a live search and save light/dark screenshots.

Usage: QT_QPA_PLATFORM=offscreen uv run python tools/screenshot.py OUT_PREFIX
"""

from __future__ import annotations

import logging
import sys
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSettings, QTimer

from tyre_finder.app import create_app, setup_logging
from tyre_finder.data.promo.base import ShopRef
from tyre_finder.data.promo.service import PromoService, ShopPromoRequest
from tyre_finder.data.promo.settings import PromoSettingsStore
from tyre_finder.data.promo.store import PromoCache
from tyre_finder.data.site_config import SiteKind, SiteStore, build_scraper
from tyre_finder.logic.search import SearchOrchestrator
from tyre_finder.models import SearchQuery, Season, TyreSize
from tyre_finder.ui.main_window import MainWindow
from tyre_finder.ui.promo_dialogs import PromoOverviewDialog
from tyre_finder.ui.sites_dialog import SiteEditDialog, SitesDialog
from tyre_finder.ui.theme import PALETTES, ThemeName

log = logging.getLogger("screenshot")


def wait(ms: int) -> None:
    """Spin the event loop so that images can load."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    """Entry point."""
    setup_logging()
    prefix = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshot")
    app = create_app()
    store = SiteStore(path=prefix.parent / "screenshot-sites.json")
    settings = QSettings(str(prefix.parent / "screenshot-settings.ini"), QSettings.Format.IniFormat)
    promo_store = PromoSettingsStore(prefix.parent / "screenshot-promo.json")
    promo_cache = PromoCache(prefix.parent / "screenshot-promo-cache.json", ttl=timedelta(hours=6))
    win = MainWindow(
        store=store, settings=settings, promo_store=promo_store, promo_cache=promo_cache
    )
    win.show()
    win.setGeometry(0, 0, 1440, 1000)
    season = Season(sys.argv[2]) if len(sys.argv) > 2 else Season.WINTER
    query = SearchQuery(TyreSize(205, 55, 16), season)
    win.set_theme(ThemeName.LIGHT)
    wait(300)
    win.grab().save(str(prefix.with_name(prefix.name + "-empty.png")))
    scrapers = [build_scraper(s) for s in store.load() if s.enabled]
    results = SearchOrchestrator(scrapers).run(query)
    for r in sorted(results, key=lambda r: r.shop):
        log.info("%-12s %-6s %3d", r.shop, r.status.value, len(r.offers))
    sites = [s for s in store.load() if s.enabled]
    promo_results = PromoService(promo_store.load(), cache=promo_cache).lookup(
        [ShopPromoRequest(ShopRef(s.id, s.name, s.base_url), s.manual_promos) for s in sites]
    )
    for name, res in sorted(promo_results.items()):
        log.info("promo %-12s %d current, %d dropped", name, len(res.codes), len(res.dropped))
    win.load_offers_for_preview(query, results, promo_results)
    win._multi_only.setChecked(True)
    wait(400)
    win._refresh_results()
    promo_groups = [g for g in win._groups if g.best_offer.promo is not None]
    # prefer showing a real promo code campaign (e.g. Medina-Med) over a card discount
    coded = [g for g in promo_groups if g.best_offer.promo and g.best_offer.promo.promo.brands]
    promo_brands = {g.brand for g in (coded or promo_groups)}
    if promo_brands:
        win._brand_filter.select_only(promo_brands)
    wait(400)
    win._refresh_results()
    first = win._cards.itemAt(0).widget()
    if first is not None and hasattr(first, "set_expanded"):
        first.set_expanded(True, animate=False)
    wait(6000)
    win.grab().save(str(prefix.with_name(prefix.name + "-light.png")))
    win.set_theme(ThemeName.DARK)
    first = win._cards.itemAt(0).widget()
    if first is not None and hasattr(first, "set_expanded"):
        first.set_expanded(True, animate=False)
    wait(2500)
    win.grab().save(str(prefix.with_name(prefix.name + "-dark.png")))
    win.set_theme(ThemeName.LIGHT)
    pdlg = PromoOverviewDialog(
        win, promo_results, [s.name for s in sites], PALETTES[ThemeName.LIGHT]
    )
    pdlg.show()
    wait(300)
    pdlg.grab().save(str(prefix.with_name(prefix.name + "-promos.png")))
    pdlg.close()
    dlg = SitesDialog(win, store, win._sites, PALETTES[ThemeName.LIGHT], query)
    dlg.show()
    dlg.table.selectRow(5)
    wait(300)
    dlg.grab().save(str(prefix.with_name(prefix.name + "-sites.png")))
    edit = SiteEditDialog(dlg, None, set(), query)
    edit.kind.setCurrentIndex(edit.kind.findData(SiteKind.GENERIC.value))
    edit.name.setText("Моят магазин")
    edit.url.setText("https://www.gumi3.com/")
    edit.search_url.setText(
        "https://www.gumi3.com/eshop/search?type=1&width={width}&height={profile}"
        "&inch={rim}&season={season}"
    )
    for season, value in ((Season.SUMMER, "2"), (Season.WINTER, "1"), (Season.ALL_SEASON, "3")):
        edit.season_edits[season].setText(value)
    for key, value in (
        ("item", "div.list div.product"),
        ("title", "h2 a"),
        ("price", ".price"),
        ("link", "h2 a@href"),
        ("image", ".thumb img@src"),
        ("size", ".sizes"),
    ):
        edit.selector_edits[key].setText(value)
    edit.show()
    edit._test()
    for _ in range(40):
        wait(250)
        if edit.test_result.text().startswith(("✔", "⚠", "•")):
            break
    log.info("Generic test: %s", edit.test_result.text())
    edit.grab().save(str(prefix.with_name(prefix.name + "-generic.png")))
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
