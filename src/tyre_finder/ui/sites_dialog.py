"""Dialog for enabling, adding, editing, removing and testing shops."""

from __future__ import annotations

import copy
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tyre_finder.data.site_config import (
    SiteConfig,
    SiteConfigError,
    SiteKind,
    SiteStore,
    build_scraper,
    default_sites,
    slugify,
)
from tyre_finder.data.sites.generic import GenericConfigError, GenericSelectors, GenericSiteSpec
from tyre_finder.models import SearchQuery, Season, SiteResult, SiteStatusKind
from tyre_finder.ui.icons import icon
from tyre_finder.ui.promo_dialogs import ManualPromosDialog
from tyre_finder.ui.theme import Palette
from tyre_finder.ui.worker import SiteTestWorker

log = logging.getLogger(__name__)

KIND_LABELS: dict[SiteKind, str] = {
    SiteKind.BUILTIN: "Вграден парсер",
    SiteKind.NK: "Шаблон „NK платформа“ (bggumi, gumi3, gumi-varna…)",
    SiteKind.GENERIC: "Общ парсер (URL шаблон + CSS селектори)",
}
_SELECTOR_HELP: dict[str, str] = {
    "item": "Елемент за един продукт, напр. div.product",
    "title": "Заглавие (марка + модел), напр. h2 a",
    "price": "Цена, напр. .price",
    "link": "Линк: css@href, напр. h2 a@href",
    "image": "Снимка: css@src, напр. img@src или img@data-src",
    "brand": "(по избор) Марка; ако е празно, марката се разпознава от заглавието",
    "size": "(по избор) Размер; ако е празно, се търси в заглавието",
}


def _run_test(
    parent: QWidget, site: SiteConfig, query: SearchQuery, label: QLabel
) -> SiteTestWorker | None:
    """Start a sample search for *site*; result is written to *label*."""
    try:
        scraper = build_scraper(site, max_pages=1)
    except (SiteConfigError, GenericConfigError) as exc:
        label.setText(f"⚠ {exc}")
        return None
    label.setText(f"Тестово търсене за {query.size} {query.season.label_bg.lower()}…")
    worker = SiteTestWorker(scraper, query)

    def done(result: SiteResult) -> None:
        if result.status is SiteStatusKind.OK:
            label.setText(
                f"✔ {site.name}: {len(result.offers)} оферти за {query.size} "
                f"({result.elapsed_s:.1f} с)"
            )
        elif result.status is SiteStatusKind.EMPTY:
            label.setText(
                f"• {site.name}: страницата се зареди, но няма разпознати оферти. "
                "Проверете селекторите."
            )
        else:
            label.setText(f"⚠ {site.name}: {result.detail or result.message}")

    worker.done.connect(done)
    worker.finished.connect(worker.deleteLater)
    worker.setParent(parent)
    worker.start()
    return worker


class SiteEditDialog(QDialog):
    """Add or edit one site."""

    def __init__(
        self,
        parent: QWidget | None,
        site: SiteConfig | None,
        existing_ids: set[str],
        query: SearchQuery,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Редакция на сайт" if site else "Нов сайт")
        self.setMinimumWidth(620)
        self._existing_ids = existing_ids
        self._query = query
        self._original = site
        self._worker: SiteTestWorker | None = None
        lay = QVBoxLayout(self)

        form = QFormLayout()
        self.name = QLineEdit(site.name if site else "")
        self.name.setToolTip("Име, което ще се показва в резултатите")
        self.url = QLineEdit(site.base_url if site else "https://")
        self.url.setToolTip("Начален адрес на магазина, напр. https://www.gumi3.com/")
        self.kind = QComboBox()
        kinds = [SiteKind.NK, SiteKind.GENERIC]
        if site and site.kind is SiteKind.BUILTIN:
            kinds = [SiteKind.BUILTIN]
        for k in kinds:
            self.kind.addItem(KIND_LABELS[k], k.value)
        if site:
            self.kind.setCurrentIndex(max(0, kinds.index(site.kind)))
        self.kind.setEnabled(not (site and site.kind is SiteKind.BUILTIN))
        self.kind.setToolTip("Как се извличат резултатите от сайта")
        form.addRow("Име:", self.name)
        form.addRow("Адрес:", self.url)
        form.addRow("Тип:", self.kind)
        lay.addLayout(form)

        spec = site.generic if site and site.generic else GenericSiteSpec()
        self.generic_box = QGroupBox("Общ парсер")
        gform = QFormLayout(self.generic_box)
        self.search_url = QLineEdit(spec.search_url)
        self.search_url.setPlaceholderText(
            "https://shop.bg/search?w={width}&h={profile}&r={rim}&season={season}"
        )
        self.search_url.setToolTip("Задължително: {width}, {profile}, {rim}; по избор {season}")
        self.page_suffix = QLineEdit(spec.page_suffix)
        self.page_suffix.setPlaceholderText("&page={page}  (по избор)")
        gform.addRow("URL за търсене:", self.search_url)
        gform.addRow("Страници (суфикс):", self.page_suffix)
        self.season_edits: dict[Season, QLineEdit] = {}
        for season in Season:
            edit = QLineEdit(spec.season_values.get(season.value, season.value))
            edit.setToolTip(f"Стойност на {{season}} за {season.label_bg.lower()} гуми")
            self.season_edits[season] = edit
            gform.addRow(f"Сезон „{season.label_bg}“:", edit)
        self.selector_edits: dict[str, QLineEdit] = {}
        for field_name, help_text in _SELECTOR_HELP.items():
            edit = QLineEdit(getattr(spec.selectors, field_name))
            edit.setPlaceholderText(help_text)
            edit.setToolTip(help_text)
            self.selector_edits[field_name] = edit
            gform.addRow(f"Селектор {field_name}:", edit)
        lay.addWidget(self.generic_box)

        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #e03a3a;")
        lay.addWidget(self.error)
        test_row = QHBoxLayout()
        self.test_btn = QPushButton("Тест")
        self.test_btn.setToolTip("Пусни примерно търсене със зададения размер")
        self.test_btn.clicked.connect(self._test)
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)
        lay.addLayout(test_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Запази")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отказ")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()

    def _kind_changed(self) -> None:
        self.generic_box.setVisible(SiteKind(self.kind.currentData()) is SiteKind.GENERIC)
        self.adjustSize()

    def build_site(self) -> SiteConfig:
        """Create a SiteConfig from the form (not yet validated)."""
        kind = SiteKind(self.kind.currentData())
        base = self._original
        site_id = base.id if base else slugify(self.name.text())
        if not base:
            candidate, n = site_id, 2
            while candidate in self._existing_ids:
                candidate = f"{site_id}-{n}"
                n += 1
            site_id = candidate
        generic = None
        if kind is SiteKind.GENERIC:
            generic = GenericSiteSpec(
                search_url=self.search_url.text().strip(),
                page_suffix=self.page_suffix.text().strip(),
                season_values={s.value: e.text().strip() for s, e in self.season_edits.items()},
                selectors=GenericSelectors(
                    **{k: e.text().strip() for k, e in self.selector_edits.items()}
                ),
            )
        return SiteConfig(
            id=site_id,
            name=self.name.text().strip(),
            kind=kind,
            base_url=self.url.text().strip(),
            enabled=base.enabled if base else True,
            builtin=base.builtin if base else False,
            parser=base.parser if base else "",
            generic=generic,
            manual_promos=copy.deepcopy(base.manual_promos) if base else [],
        )

    def _test(self) -> None:
        site = self.build_site()
        errors = site.validate()
        if errors:
            self.error.setText("\n".join(errors))
            return
        self.error.clear()
        self._worker = _run_test(self, site, self._query, self.test_result)

    def _accept(self) -> None:
        errors = self.build_site().validate()
        if errors:
            self.error.setText("\n".join(errors))
            return
        self.accept()


class SitesDialog(QDialog):
    """Manage the list of shops."""

    def __init__(
        self,
        parent: QWidget | None,
        store: SiteStore,
        sites: list[SiteConfig],
        palette: Palette,
        query: SearchQuery,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Сайтове за търсене")
        self.resize(860, 560)
        self._store = store
        self._sites = copy.deepcopy(sites)
        self._query = query
        self._worker: SiteTestWorker | None = None
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Отметнете сайтовете, в които да се търси. Вградените сайтове могат да "
            "се изключат; „Възстанови“ връща списъка по подразбиране."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "muted")
        lay.addWidget(intro)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Активен", "Име", "Тип", "Адрес", "Ръчни кодове"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.doubleClicked.connect(lambda _i: self._edit())
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        add = QPushButton("Добави")
        add.setIcon(icon("plus", palette.accent, 16))
        add.setToolTip("Добави нов сайт (шаблон NK или общ парсер)")
        add.clicked.connect(self._add)
        edit = QPushButton("Редактирай")
        edit.setIcon(icon("edit", palette.text, 16))
        edit.clicked.connect(self._edit)
        remove = QPushButton("Премахни")
        remove.setIcon(icon("trash", palette.danger, 16))
        remove.setToolTip("Премахни избрания сайт от списъка")
        remove.clicked.connect(self._remove)
        test = QPushButton("Тест")
        test.setIcon(icon("search", palette.text, 16))
        test.setToolTip(f"Примерно търсене за {query.size} {query.season.label_bg.lower()}")
        test.clicked.connect(self._test)
        promo = QPushButton("Промокод…")
        promo.setIcon(icon("tag", palette.accent, 16))
        promo.setToolTip("Ръчно добавяне/редакция на промокод за избрания магазин")
        promo.clicked.connect(self._promos)
        reset = QPushButton("Възстанови по подразбиране")
        reset.setIcon(icon("refresh", palette.text, 16))
        reset.clicked.connect(self._reset)
        for b in (add, edit, remove, test, promo):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(reset)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Запази")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отказ")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._fill()

    @property
    def sites(self) -> list[SiteConfig]:
        """Edited list."""
        return self._sites

    def _fill(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._sites))
        for r, site in enumerate(self._sites):
            chk = QTableWidgetItem()
            chk.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            chk.setCheckState(Qt.CheckState.Checked if site.enabled else Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QTableWidgetItem(site.name))
            kind = {SiteKind.BUILTIN: "вграден", SiteKind.NK: "NK шаблон", SiteKind.GENERIC: "общ"}[
                site.kind
            ]
            self.table.setItem(r, 2, QTableWidgetItem(kind))
            self.table.setItem(r, 3, QTableWidgetItem(site.base_url))
            codes = ", ".join(p.code for p in site.manual_promos) or "—"
            self.table.setItem(r, 4, QTableWidgetItem(codes))
        self.table.blockSignals(False)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self._sites[item.row()].enabled = item.checkState() == Qt.CheckState.Checked

    def _current(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.status.setText("Изберете сайт от таблицата.")
            return None
        return rows[0].row()

    def _add(self) -> None:
        dlg = SiteEditDialog(self, None, {s.id for s in self._sites}, self._query)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._sites.append(dlg.build_site())
            self._fill()
            self.table.selectRow(len(self._sites) - 1)

    def _edit(self) -> None:
        row = self._current()
        if row is None:
            return
        dlg = SiteEditDialog(self, self._sites[row], {s.id for s in self._sites}, self._query)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._sites[row] = dlg.build_site()
            self._fill()

    def _remove(self) -> None:
        row = self._current()
        if row is None:
            return
        site = self._sites[row]
        answer = QMessageBox.question(self, "Премахване", f"Да премахна ли „{site.name}“?")
        if answer == QMessageBox.StandardButton.Yes:
            del self._sites[row]
            self._fill()

    def _test(self) -> None:
        row = self._current()
        if row is None:
            return
        self._worker = _run_test(self, self._sites[row], self._query, self.status)

    def _promos(self) -> None:
        row = self._current()
        if row is None:
            return
        site = self._sites[row]
        dlg = ManualPromosDialog(self, site.name, site.manual_promos)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            site.manual_promos = dlg.promos
            self._fill()
            self.status.setText(
                f"{site.name}: {len(site.manual_promos)} ръчни кода (натиснете „Запази“)."
            )

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self, "Възстановяване", "Да върна ли списъка със сайтове по подразбиране?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            manual = {s.id: s.manual_promos for s in self._sites}
            self._sites = default_sites()
            for site in self._sites:
                site.manual_promos = manual.get(site.id, [])
            self._fill()
            self.status.setText("Списъкът е възстановен (натиснете „Запази“).")

    def _save(self) -> None:
        try:
            self._store.save(self._sites)
        except SiteConfigError as exc:
            self.status.setText(f"⚠ {exc}")
            return
        except OSError as exc:
            self.status.setText(f"⚠ Неуспешен запис: {exc}")
            return
        self.accept()
