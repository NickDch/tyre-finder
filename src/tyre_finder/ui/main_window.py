"""Main application window."""

from __future__ import annotations

import logging
from datetime import timedelta

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tyre_finder import __version__
from tyre_finder.data.brands import KNOWN_BRANDS
from tyre_finder.data.promo.base import ShopRef
from tyre_finder.data.promo.service import PromoService, ShopPromoRequest, ShopPromoResult
from tyre_finder.data.promo.settings import PromoSettingsStore
from tyre_finder.data.promo.store import PromoCache
from tyre_finder.data.site_config import SiteConfig, SiteConfigError, SiteStore, build_scraper
from tyre_finder.data.sites.generic import GenericConfigError
from tyre_finder.logic.filters import FilterCriteria, SortOrder, apply_filters, brand_counts
from tyre_finder.logic.grouping import group_offers
from tyre_finder.logic.promo import apply_promos
from tyre_finder.models import (
    PromoCode,
    SearchQuery,
    Season,
    SiteResult,
    SiteStatusKind,
    TyreGroup,
    TyreOffer,
    TyreSize,
)
from tyre_finder.ui.icons import check_icon_path, icon, pixmap
from tyre_finder.ui.image_loader import ImageLoader
from tyre_finder.ui.promo_dialogs import PromoOverviewDialog, PromoSettingsDialog
from tyre_finder.ui.sites_dialog import SitesDialog
from tyre_finder.ui.theme import PALETTES, ThemeName, stylesheet
from tyre_finder.ui.widgets import (
    PROMO_WARNING,
    BrandFilter,
    EmptyState,
    ResultCard,
    SiteStatusList,
)
from tyre_finder.ui.worker import PromoWorker, SearchWorker

log = logging.getLogger(__name__)

WIDTHS = [
    135,
    145,
    155,
    165,
    175,
    185,
    195,
    205,
    215,
    225,
    235,
    245,
    255,
    265,
    275,
    285,
    295,
    305,
    315,
    325,
    335,
]
PROFILES = [25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85]
RIMS = list(range(13, 24))
PAGE_SIZE = 40


def _section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setProperty("role", "section")
    return lbl


class MainWindow(QMainWindow):
    """Search sidebar + grouped result cards."""

    def __init__(
        self,
        store: SiteStore | None = None,
        settings: QSettings | None = None,
        promo_store: PromoSettingsStore | None = None,
        promo_cache: PromoCache | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Гуми — сравнение на цени")
        self.setMinimumSize(1040, 680)
        self._settings = settings or QSettings("TyreFinder", "TyreFinder")
        self._store = store or SiteStore()
        self._sites: list[SiteConfig] = self._store.load()
        self._theme = ThemeName(str(self._settings.value("theme", ThemeName.LIGHT.value)))
        self._loader = ImageLoader(self)
        self._worker: SearchWorker | None = None
        self._offers: list[TyreOffer] = []
        self._groups: list[TyreGroup] = []
        self._visible: list[TyreGroup] = []
        self._shown = 0
        self._done_sites = 0
        self._last_query: SearchQuery | None = None
        self._promo_store = promo_store or PromoSettingsStore()
        self._promo_settings = self._promo_store.load()
        self._promo_cache = promo_cache or PromoCache(
            ttl=timedelta(hours=self._promo_settings.cache_hours)
        )
        self._promo_worker: PromoWorker | None = None
        self._promo_results: dict[str, ShopPromoResult] = {}

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_results(), 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"Готов · {self._enabled_count()} активни магазина")

        self._filter_timer = QTimer(self, singleShot=True, interval=150)
        self._filter_timer.timeout.connect(self._refresh_results)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._start_search)
        QShortcut(QKeySequence("Escape"), self, activated=self._cancel_search)

        self._restore_settings()
        self._apply_theme()
        self._brand_filter.set_brands([(b, None) for b in sorted(KNOWN_BRANDS, key=str.upper)])
        self._show_empty("idle")

    # ----------------------------------------------------------------- layout
    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        lay = QHBoxLayout(header)
        lay.setContentsMargins(20, 12, 16, 12)
        self._logo = QLabel()
        lay.addWidget(self._logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("Гуми · сравнение на цени")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Търсене в български онлайн магазини за гуми")
        subtitle.setObjectName("AppSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        lay.addLayout(titles)
        lay.addStretch(1)
        self._promo_btn = QPushButton("Промокодове")
        self._promo_btn.setToolTip("Намерени промокодове по магазини, източници и настройки")
        self._promo_btn.clicked.connect(self._open_promos)
        lay.addWidget(self._promo_btn)
        self._sites_btn = QPushButton("Сайтове")
        self._sites_btn.setToolTip("Добавяне, премахване и тест на магазини")
        self._sites_btn.clicked.connect(self._open_sites)
        lay.addWidget(self._sites_btn)
        self._theme_btn = QPushButton()
        self._theme_btn.setProperty("variant", "ghost")
        self._theme_btn.setToolTip("Светла / тъмна тема")
        self._theme_btn.clicked.connect(self._toggle_theme)
        lay.addWidget(self._theme_btn)
        return header

    def _build_sidebar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("Sidebar")
        frame.setFixedWidth(340)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(18, 14, 18, 18)
        lay.setSpacing(8)

        lay.addWidget(_section("Размер на гумата"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        self._width = QComboBox()
        self._profile = QComboBox()
        self._rim = QComboBox()
        for combo, values, prefix, tip in (
            (self._width, WIDTHS, "", "Широчина в мм"),
            (self._profile, PROFILES, "", "Височина (профил) в %"),
            (self._rim, RIMS, "R", "Диаметър на джантата в инчове"),
        ):
            for v in values:
                combo.addItem(f"{prefix}{v}", v)
            combo.setToolTip(tip)
        for col, (text, combo) in enumerate(
            (("Широчина", self._width), ("Височина", self._profile), ("Джанта", self._rim))
        ):
            lbl = QLabel(text)
            lbl.setProperty("role", "muted")
            grid.addWidget(lbl, 0, col)
            grid.addWidget(combo, 1, col)
        lay.addLayout(grid)

        lay.addWidget(_section("Сезон"))
        self._season = QComboBox()
        for season in Season:
            self._season.addItem(season.label_bg, season.value)
        self._season.setToolTip("Летни, зимни или всесезонни гуми")
        lay.addWidget(self._season)

        btns = QHBoxLayout()
        self._search_btn = QPushButton("Търси")
        self._search_btn.setProperty("variant", "primary")
        self._search_btn.setToolTip("Търси във всички активни магазини (Ctrl+Enter)")
        self._search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_btn.clicked.connect(self._start_search)
        self._cancel_btn = QPushButton("Отказ")
        self._cancel_btn.setToolTip("Прекрати търсенето (Esc)")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel_search)
        btns.addWidget(self._search_btn, 1)
        btns.addWidget(self._cancel_btn)
        lay.addSpacing(4)
        lay.addLayout(btns)
        self._progress = QProgressBar()
        self._progress.setFixedHeight(8)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        lay.addWidget(_section("Магазини"))
        self._site_status = SiteStatusList()
        self._site_status.setToolTip("Статус на търсенето по магазини")
        lay.addWidget(self._site_status)

        lay.addWidget(_section("Цена (€ за брой, най-ниска в групата)"))
        price_row = QHBoxLayout()
        self._min_price = QDoubleSpinBox()
        self._max_price = QDoubleSpinBox()
        for spin, tip in (
            (self._min_price, "Минимална цена"),
            (self._max_price, "Максимална цена"),
        ):
            spin.setRange(0, 5000)
            spin.setDecimals(0)
            spin.setSingleStep(5)
            spin.setSuffix(" €")
            spin.setToolTip(tip + " (0 = без ограничение)")
            spin.setSpecialValueText("—")
            spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
            spin.valueChanged.connect(self._schedule_filter)
        price_row.addWidget(QLabel("от"))
        price_row.addWidget(self._min_price, 1)
        price_row.addWidget(QLabel("до"))
        price_row.addWidget(self._max_price, 1)
        lay.addLayout(price_row)

        lay.addWidget(_section("Подреждане"))
        self._sort = QComboBox()
        for text, order in (
            ("Цена: ниска → висока", SortOrder.PRICE_ASC),
            ("Цена: висока → ниска", SortOrder.PRICE_DESC),
            ("Най-много магазини", SortOrder.SHOPS_DESC),
            ("Марка A → Z", SortOrder.BRAND),
        ):
            self._sort.addItem(text, order.value)
        self._sort.setToolTip("Подреждане по най-ниската цена на модела")
        self._sort.currentIndexChanged.connect(self._schedule_filter)
        lay.addWidget(self._sort)
        self._multi_only = QCheckBox("Само модели в 2+ магазина")
        self._multi_only.setToolTip("Показвай само гуми, за които има сравнение на цени")
        self._multi_only.toggled.connect(self._schedule_filter)
        lay.addWidget(self._multi_only)
        self._expand_all = QCheckBox("Разгъни сравнението на цените")
        self._expand_all.setToolTip("Показвай цените от всички магазини във всяка карта")
        self._expand_all.toggled.connect(self._schedule_filter)
        lay.addWidget(self._expand_all)

        lay.addWidget(_section("Промокодове"))
        self._use_promo = QCheckBox("Смятай с промокод")
        self._use_promo.setToolTip(
            "Сравнявай по цената с промокод (ефективна цена), когато отстъпката е ясна"
        )
        self._use_promo.setChecked(True)
        self._use_promo.toggled.connect(self._schedule_filter)
        lay.addWidget(self._use_promo)
        self._apply_possible = QCheckBox("Включи и „възможни кодове“")
        self._apply_possible.setToolTip(
            "Кодове с ниска сигурност (напр. от търсене в интернет) също да намаляват цената"
        )
        self._apply_possible.setChecked(self._promo_settings.apply_possible)
        self._apply_possible.toggled.connect(self._schedule_filter)
        lay.addWidget(self._apply_possible)
        self._promo_status = QLabel("Промокодовете се търсят заедно с гумите.")
        self._promo_status.setProperty("role", "muted")
        self._promo_status.setWordWrap(True)
        lay.addWidget(self._promo_status)
        warning = QLabel("⚠ " + PROMO_WARNING)
        warning.setProperty("role", "warning-note")
        warning.setWordWrap(True)
        lay.addWidget(warning)

        lay.addWidget(_section("Марки"))
        self._brand_filter = BrandFilter()
        self._brand_filter.changed.connect(self._schedule_filter)
        lay.addWidget(self._brand_filter)
        lay.addStretch(1)
        return frame

    def _build_results(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(22, 16, 22, 0)
        lay.setSpacing(10)
        top = QHBoxLayout()
        self._results_title = QLabel("Резултати")
        self._results_title.setProperty("role", "h2")
        self._results_info = QLabel()
        self._results_info.setProperty("role", "muted")
        top.addWidget(self._results_title)
        top.addSpacing(10)
        top.addWidget(self._results_info)
        top.addStretch(1)
        lay.addLayout(top)

        self._stack = QStackedWidget()
        self._empty = EmptyState()
        self._stack.addWidget(self._empty)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cards_host = QWidget()
        self._cards = QVBoxLayout(self._cards_host)
        self._cards.setContentsMargins(0, 0, 8, 16)
        self._cards.setSpacing(12)
        self._cards.addStretch(1)
        self._scroll.setWidget(self._cards_host)
        self._stack.addWidget(self._scroll)
        lay.addWidget(self._stack, 1)
        self._more_btn = QPushButton()
        self._more_btn.clicked.connect(self._show_more)
        return wrap

    # ------------------------------------------------------------- settings
    def _restore_settings(self) -> None:
        geometry = self._settings.value("geometry")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        else:
            self.resize(1320, 860)
        self._select(self._width, int(self._settings.value("width", 205)))
        self._select(self._profile, int(self._settings.value("profile", 55)))
        self._select(self._rim, int(self._settings.value("rim", 16)))
        season = str(self._settings.value("season", Season.SUMMER.value))
        idx = self._season.findData(season)
        self._season.setCurrentIndex(max(idx, 0))
        self._expand_all.setChecked(self._settings.value("expand_all", "false") == "true")
        self._use_promo.setChecked(self._settings.value("use_promo", "true") == "true")

    @staticmethod
    def _select(combo: QComboBox, value: int) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        """Persist window state and stop the worker."""
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("theme", self._theme.value)
        self._settings.setValue("width", self._width.currentData())
        self._settings.setValue("profile", self._profile.currentData())
        self._settings.setValue("rim", self._rim.currentData())
        self._settings.setValue("season", Season(self._season.currentData()).value)
        self._settings.setValue("expand_all", "true" if self._expand_all.isChecked() else "false")
        self._settings.setValue("use_promo", "true" if self._use_promo.isChecked() else "false")
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        if self._promo_worker is not None and self._promo_worker.isRunning():
            self._promo_worker.cancel()
            self._promo_worker.wait(5000)
        super().closeEvent(event)

    # ---------------------------------------------------------------- theme
    @property
    def palette_(self) -> object:
        """Current colour palette."""
        return PALETTES[self._theme]

    def _toggle_theme(self) -> None:
        self._theme = ThemeName.DARK if self._theme is ThemeName.LIGHT else ThemeName.LIGHT
        self._settings.setValue("theme", self._theme.value)
        self._apply_theme()
        self._refresh_results()

    def set_theme(self, theme: ThemeName) -> None:
        """Switch theme programmatically (used for screenshots)."""
        self._theme = theme
        self._apply_theme()
        self._refresh_results()

    def _apply_theme(self) -> None:
        pal = PALETTES[self._theme]
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(stylesheet(self._theme, check_icon_path(pal.accent_text)))
        self._logo.setPixmap(pixmap("tyre", pal.accent, 34))
        dark = self._theme is ThemeName.DARK
        self._theme_btn.setIcon(icon("sun" if dark else "moon", pal.text, 20))
        self._theme_btn.setText(" Светла" if dark else " Тъмна")
        self._sites_btn.setIcon(icon("settings", pal.text, 16))
        self._promo_btn.setIcon(icon("tag", pal.accent, 16))
        self._search_btn.setIcon(icon("search", pal.accent_text, 16))
        if self._site_status.count() == 0:
            self._site_status.show_sites(
                [s.name for s in self._sites if s.enabled], pal, SiteStatusKind.PENDING
            )
        else:
            self._site_status.set_palette(pal)
        if self._stack.currentWidget() is self._empty:
            self._show_empty(getattr(self, "_empty_kind", "idle"))

    # --------------------------------------------------------------- search
    def _enabled_count(self) -> int:
        return sum(1 for s in self._sites if s.enabled)

    def current_query(self) -> SearchQuery:
        """Query from the dropdowns."""
        return SearchQuery(
            TyreSize(
                self._width.currentData(), self._profile.currentData(), self._rim.currentData()
            ),
            Season(self._season.currentData()),
        )

    def _start_search(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        scrapers = []
        problems = []
        for site in self._sites:
            if not site.enabled:
                continue
            try:
                scrapers.append(build_scraper(site))
            except (SiteConfigError, GenericConfigError) as exc:
                problems.append(f"{site.name}: {exc}")
        if not scrapers:
            self.statusBar().showMessage("Няма активни магазини — отворете „Сайтове“.")
            return
        query = self.current_query()
        self._last_query = query
        self._offers = []
        self._groups = []
        self._done_sites = 0
        pal = PALETTES[self._theme]
        self._site_status.show_sites([s.name for s in scrapers], pal)
        self._progress.setRange(0, len(scrapers))
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._search_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._results_title.setText(f"{query.size} · {query.season.label_bg}")
        self._results_info.setText(f"Търсене в {len(scrapers)} магазина…")
        self._clear_cards()
        self._show_empty("loading")
        if problems:
            log.warning("Skipped sites: %s", problems)
        self._worker = SearchWorker(scrapers, query)
        self._worker.site_done.connect(self._on_site_done)
        self._worker.search_finished.connect(self._on_finished)
        self._worker.start()
        self._start_promo_lookup()

    # --------------------------------------------------------------- promos
    def _promo_requests(self) -> list[ShopPromoRequest]:
        return [
            ShopPromoRequest(ShopRef(s.id, s.name, s.base_url), list(s.manual_promos))
            for s in self._sites
            if s.enabled
        ]

    def _start_promo_lookup(self, use_cache: bool = True) -> None:
        """Start the promo lookup in parallel with the tyre search."""
        if self._promo_worker is not None and self._promo_worker.isRunning():
            return
        settings = self._promo_settings
        self._promo_cache.ttl = timedelta(hours=settings.cache_hours)
        service = PromoService(
            settings,
            cache=self._promo_cache,
            sources=None if settings.enabled else [],
        )
        self._promo_results = {}
        self._promo_status.setText(
            "Търсене на промокодове…" if settings.enabled else "Търсенето е изключено (само ръчни)."
        )
        self._promo_worker = PromoWorker(service, self._promo_requests(), use_cache=use_cache)
        self._promo_worker.shop_done.connect(self._on_promo_shop)
        self._promo_worker.promos_finished.connect(self._on_promos_finished)
        self._promo_worker.start()

    def _on_promo_shop(self, result: ShopPromoResult) -> None:
        self._promo_results[result.shop] = result
        if result.codes:
            self._schedule_filter()

    def _on_promos_finished(self, results: dict[str, ShopPromoResult]) -> None:
        self._promo_results = dict(results)
        # keep the QThread object referenced until it has really finished
        self._update_promo_status()
        self._schedule_filter()

    def _update_promo_status(self) -> None:
        shops = [r for r in self._promo_results.values() if r.codes]
        confirmed = sum(len(r.confirmed) for r in self._promo_results.values())
        possible = sum(len(r.possible) for r in self._promo_results.values())
        if not shops:
            text = "Няма актуални промокодове за избраните магазини."
        else:
            names = ", ".join(r.shop for r in shops)
            text = f"{confirmed} кода/отстъпки"
            if possible:
                text += f" и {possible} възможни"
            text += f" за: {names}."
        self._promo_status.setText(text + " Подробности: бутон „Промокодове“.")

    def promos_by_shop(self) -> dict[str, list[PromoCode]]:
        """Current codes per shop name."""
        return {shop: res.codes for shop, res in self._promo_results.items()}

    def _open_promos(self) -> None:
        shops = [s.name for s in self._sites if s.enabled]
        dlg = PromoOverviewDialog(self, self._promo_results, shops, PALETTES[self._theme])
        dlg.exec()
        if dlg.settings_requested:
            sdlg = PromoSettingsDialog(self, self._promo_store, self._promo_settings)
            if sdlg.exec():
                self._promo_settings = sdlg.settings
                self._apply_possible.setChecked(self._promo_settings.apply_possible)
                self.statusBar().showMessage("Настройките за промокодове са запазени")
        if dlg.refresh_requested or dlg.settings_requested:
            self._start_promo_lookup(use_cache=not dlg.refresh_requested)

    def _cancel_search(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._cancel_btn.setEnabled(False)
            self.statusBar().showMessage("Прекратяване…")

    def _on_site_done(self, result: SiteResult) -> None:
        self._done_sites += 1
        self._progress.setValue(self._done_sites)
        self._site_status.update_result(result)
        self._offers.extend(result.offers)
        self._groups = group_offers(self._offers)
        self._update_brand_list()
        self._refresh_results()

    def _on_finished(self, results: list[SiteResult]) -> None:
        ok = sum(1 for r in results if r.status is SiteStatusKind.OK)
        failed = [r.shop for r in results if r.status is SiteStatusKind.ERROR]
        self._progress.setVisible(False)
        self._search_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)
        cancelled = self._worker is not None and self._worker.cancelled
        self._finished_worker = self._worker  # keep the QThread alive until it really ends
        self._worker = None
        msg = (
            f"Готово: {len(self._offers)} оферти от {ok}/{len(results)} магазина, "
            f"{len(self._groups)} модела"
        )
        if failed:
            msg += " · неуспешни: " + ", ".join(failed)
        if cancelled:
            msg = "Търсенето е прекратено · " + msg
        self.statusBar().showMessage(msg)
        self._refresh_results()

    # -------------------------------------------------------------- results
    def _update_brand_list(self) -> None:
        self._brand_filter.set_brands(list(brand_counts(self._groups)))

    def _schedule_filter(self) -> None:
        self._filter_timer.start()

    def criteria(self) -> FilterCriteria:
        """Filters from the sidebar."""
        return FilterCriteria(
            min_price=self._min_price.value() or None,
            max_price=self._max_price.value() or None,
            brands=self._brand_filter.selected(),
            multi_shop_only=self._multi_only.isChecked(),
            sort=SortOrder(self._sort.currentData()),
        )

    def _clear_cards(self) -> None:
        while self._cards.count() > 1:
            item = self._cards.takeAt(0)
            widget = item.widget()
            if widget is self._more_btn:
                widget.setParent(None)
            elif widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _refresh_results(self) -> None:
        if not self._groups:
            if self._worker is None and self._last_query is not None:
                self._show_empty("none")
            return
        apply_promos(
            self._offers,
            self.promos_by_shop(),
            enabled=self._use_promo.isChecked(),
            apply_possible=self._apply_possible.isChecked(),
        )
        self._visible = apply_filters(self._groups, self.criteria())
        multi = sum(1 for g in self._visible if g.shop_count > 1)
        offers = sum(len(g.offers) for g in self._visible)
        self._results_info.setText(
            f"{len(self._visible)} модела · {offers} оферти · {multi} с няколко магазина"
        )
        if not self._visible:
            self._clear_cards()
            self._show_empty("filtered")
            return
        self._stack.setCurrentWidget(self._scroll)
        self._clear_cards()
        self._shown = 0
        self._show_more()
        self._scroll.verticalScrollBar().setValue(0)

    def _show_more(self) -> None:
        pal = PALETTES[self._theme]
        if self._more_btn.parent() is not None:
            self._cards.removeWidget(self._more_btn)
            self._more_btn.setParent(None)
        end = min(self._shown + PAGE_SIZE, len(self._visible))
        expand = self._expand_all.isChecked()
        for group in self._visible[self._shown : end]:
            card = ResultCard(
                group, pal, self._loader, expanded=expand, promos_by_shop=self.promos_by_shop()
            )
            self._cards.insertWidget(self._cards.count() - 1, card)
        self._shown = end
        remaining = len(self._visible) - self._shown
        if remaining > 0:
            self._more_btn.setText(f"Покажи още ({remaining})")
            self._cards.insertWidget(self._cards.count() - 1, self._more_btn)

    def _show_empty(self, kind: str) -> None:
        self._empty_kind = kind
        pal = PALETTES[self._theme]
        n = self._enabled_count()
        states = {
            "idle": (
                "tyre",
                pal.accent,
                "Намерете най-добрата цена",
                f"Изберете размер и сезон вляво и натиснете „Търси“. Ще претърсим {n} "
                "български онлайн магазина и ще групираме еднаквите гуми, за да видите "
                "къде е най-евтино.",
            ),
            "loading": (
                "refresh",
                pal.accent,
                "Търсим…",
                "Резултатите се появяват веднага щом всеки магазин отговори. "
                "Статусът по магазини е в лявата колона.",
            ),
            "none": (
                "alert",
                pal.warning,
                "Няма намерени гуми",
                "Нито един магазин не върна резултати за този размер и сезон. "
                "Опитайте друг размер или проверете статуса на магазините.",
            ),
            "filtered": (
                "tag",
                pal.muted,
                "Няма резултати с тези филтри",
                "Разширете ценовия диапазон или изберете повече марки.",
            ),
        }
        self._empty.show_state(*states[kind])
        self._stack.setCurrentWidget(self._empty)

    # ---------------------------------------------------------------- sites
    def _open_sites(self) -> None:
        dlg = SitesDialog(
            self, self._store, self._sites, PALETTES[self._theme], self.current_query()
        )
        if dlg.exec():
            self._sites = dlg.sites
            self._site_status.show_sites(
                [s.name for s in self._sites if s.enabled],
                PALETTES[self._theme],
                SiteStatusKind.PENDING,
            )
            self.statusBar().showMessage(f"Запазено · {self._enabled_count()} активни магазина")
            self._start_promo_lookup()
            if self._stack.currentWidget() is self._empty and self._empty_kind == "idle":
                self._show_empty("idle")

    # ------------------------------------------------------------ test hooks
    def load_offers_for_preview(
        self,
        query: SearchQuery,
        results: list[SiteResult],
        promo_results: dict[str, ShopPromoResult] | None = None,
    ) -> None:
        """Populate the window from finished results (used by the screenshot tool)."""
        self._last_query = query
        if promo_results is not None:
            self._promo_results = dict(promo_results)
            self._update_promo_status()
        self._select(self._width, query.size.width)
        self._select(self._profile, query.size.profile)
        self._select(self._rim, query.size.rim)
        self._season.setCurrentIndex(self._season.findData(query.season.value))
        self._results_title.setText(f"{query.size} · {query.season.label_bg}")
        self._site_status.show_sites([r.shop for r in results], PALETTES[self._theme])
        for r in results:
            self._site_status.update_result(r)
            self._offers.extend(r.offers)
        self._groups = group_offers(self._offers)
        self._update_brand_list()
        self._refresh_results()
        ok = sum(1 for r in results if r.status is SiteStatusKind.OK)
        self.statusBar().showMessage(
            f"Готово: {len(self._offers)} оферти от {ok}/{len(results)} магазина, "
            f"{len(self._groups)} модела"
        )

    @property
    def version(self) -> str:
        """Application version."""
        return __version__
