"""Dialogs: promo overview per shop, search-engine settings, manual promo codes."""

from __future__ import annotations

import copy
import logging
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from tyre_finder.data.promo.service import ShopPromoResult
from tyre_finder.data.promo.settings import EngineChoice, PromoSettings, PromoSettingsStore
from tyre_finder.data.promo.store import ManualPromo
from tyre_finder.models import Confidence, PromoCode
from tyre_finder.ui.icons import icon
from tyre_finder.ui.theme import Palette
from tyre_finder.ui.widgets import PROMO_WARNING, promo_date_text

log = logging.getLogger(__name__)

GOOGLE_HELP = (
    "Google Programmable Search: 1) programmablesearchengine.google.com → „Добавяне“, "
    "търсене в целия интернет → копирайте „Search engine ID“ (CX). 2) console.cloud.google.com"
    " → APIs & Services → активирайте „Custom Search API“ → Credentials → „API key“. "
    "100 безплатни заявки на ден."
)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _code_html(promo: PromoCode) -> str:
    code = f"<b><code>{_esc(promo.code)}</code></b>" if promo.code else _esc(promo.code_note)
    kind = " <i>(възможен код)</i>" if promo.confidence is Confidence.LOW else ""
    disc = f" {promo.discount_label}" if promo.discount_label else ""
    return (
        f"<li>{code}{kind}{disc} — {_esc(promo.title)}<br>"
        f"<small>{_esc(promo_date_text(promo))} · {_esc(promo.origin.label_bg)} · "
        f'<a href="{_esc(promo.source_url)}">{_esc(promo.source_url)}</a></small></li>'
    )


def overview_html(results: dict[str, ShopPromoResult], shops: list[str]) -> str:
    """HTML report of what was found / dropped / checked per shop."""
    parts = [f"<p><b>⚠ {_esc(PROMO_WARNING)}</b></p>"]
    for shop in shops:
        res = results.get(shop)
        if res is None:
            parts.append(f"<h3>{_esc(shop)}</h3><p>Търсене…</p>")
            continue
        cache = " (от кеша)" if res.from_cache else ""
        parts.append(f"<h3>{_esc(shop)}{cache}</h3>")
        if res.codes:
            parts.append("<ul>" + "".join(_code_html(c) for c in res.codes) + "</ul>")
        else:
            parts.append("<p>Няма актуален промокод.</p>")
        if res.dropped:
            items = "".join(
                f"<li>{_esc(c.code or c.title)} — {_esc(reason)} "
                f'<small><a href="{_esc(c.source_url)}">източник</a></small></li>'
                for c, reason in res.dropped
            )
            parts.append(f"<p><small>Пропуснати:</small></p><ul><small>{items}</small></ul>")
        if res.checks:
            items = "".join(
                f"<li>{'✓' if ch.ok else '✗'} {_esc(ch.source)}: {_esc(ch.outcome)}"
                + (f" <small>{_esc(ch.url)}</small>" if ch.url else "")
                + "</li>"
                for ch in res.checks
            )
            parts.append(f"<p><small>Проверено:</small></p><ul><small>{items}</small></ul>")
    return "".join(parts)


class PromoOverviewDialog(QDialog):
    """Per-shop list of current promo codes and what was checked."""

    def __init__(
        self,
        parent: QWidget | None,
        results: dict[str, ShopPromoResult],
        shops: list[str],
        palette: Palette,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Промокодове по магазини")
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(overview_html(results, shops))
        lay.addWidget(self.browser, 1)
        self.settings_requested = False
        row = QHBoxLayout()
        settings = QPushButton("Настройки за търсене…")
        settings.setIcon(icon("settings", palette.text, 16))
        settings.clicked.connect(self._settings)
        row.addWidget(settings)
        self.refresh_requested = False
        refresh = QPushButton("Търси наново (без кеша)")
        refresh.setIcon(icon("refresh", palette.text, 16))
        refresh.clicked.connect(self._refresh)
        row.addWidget(refresh)
        row.addStretch(1)
        close = QPushButton("Затвори")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)

    def _settings(self) -> None:
        self.settings_requested = True
        self.accept()

    def _refresh(self) -> None:
        self.refresh_requested = True
        self.accept()


class PromoSettingsDialog(QDialog):
    """Search engine choice, API keys and freshness window."""

    def __init__(
        self, parent: QWidget | None, store: PromoSettingsStore, settings: PromoSettings
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Търсене на промокодове")
        self._store = store
        self._settings = copy.deepcopy(settings)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.enabled = QCheckBox("Търси промокодове заедно с гумите")
        self.enabled.setChecked(settings.enabled)
        form.addRow(self.enabled)
        self.aggregators = QCheckBox(
            "Проверявай сайтове за купони (kuponovo, cuponeria, discounts)"
        )
        self.aggregators.setChecked(settings.use_aggregators)
        form.addRow(self.aggregators)
        self.engine = QComboBox()
        for choice in EngineChoice:
            self.engine.addItem(choice.label_bg, choice.value)
        self.engine.setCurrentIndex(max(self.engine.findData(settings.engine.value), 0))
        self.engine.setToolTip("Търсачка за свободно търсене в интернет")
        form.addRow("Търсачка", self.engine)
        self.google_key = QLineEdit(settings.google_api_key)
        self.google_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.google_key.setPlaceholderText("AIza…")
        form.addRow("Google API ключ", self.google_key)
        self.google_cx = QLineEdit(settings.google_cx)
        self.google_cx.setPlaceholderText("Search engine ID (CX)")
        form.addRow("Google CX", self.google_cx)
        self.brave_key = QLineEdit(settings.brave_api_key)
        self.brave_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.brave_key.setPlaceholderText("по избор")
        form.addRow("Brave API ключ", self.brave_key)
        self.window = QSpinBox()
        self.window.setRange(1, 365)
        self.window.setValue(settings.window_days)
        self.window.setSuffix(" дни")
        self.window.setToolTip(
            "Код без срок на валидност се показва само ако е публикуван в този период"
        )
        form.addRow("Без срок: публикуван до", self.window)
        self.cache = QDoubleSpinBox()
        self.cache.setRange(0, 72)
        self.cache.setDecimals(0)
        self.cache.setValue(settings.cache_hours)
        self.cache.setSuffix(" ч")
        form.addRow("Кеш", self.cache)
        self.apply_possible = QCheckBox("Прилагай и „възможни кодове“ (ниска сигурност) към цената")
        self.apply_possible.setChecked(settings.apply_possible)
        form.addRow(self.apply_possible)
        lay.addLayout(form)
        help_lbl = QLabel(
            GOOGLE_HELP + " Ключовете се пазят само във вашия конфигурационен файл "
            f"({store.path}). google.com не се претърсва директно."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setProperty("role", "muted")
        help_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(help_lbl)
        self.error = QLabel()
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Запази")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отказ")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    @property
    def settings(self) -> PromoSettings:
        """Edited settings."""
        return self._settings

    def build(self) -> PromoSettings:
        """Settings from the form."""
        s = copy.deepcopy(self._settings)
        s.enabled = self.enabled.isChecked()
        s.use_aggregators = self.aggregators.isChecked()
        s.engine = EngineChoice(self.engine.currentData())
        s.google_api_key = self.google_key.text().strip()
        s.google_cx = self.google_cx.text().strip()
        s.brave_api_key = self.brave_key.text().strip()
        s.window_days = self.window.value()
        s.cache_hours = self.cache.value()
        s.apply_possible = self.apply_possible.isChecked()
        return s

    def _save(self) -> None:
        s = self.build()
        if s.engine is EngineChoice.GOOGLE and not s.google_configured:
            self.error.setText("⚠ За Google са нужни и API ключ, и CX.")
            return
        if s.engine is EngineChoice.BRAVE and not s.brave_api_key:
            self.error.setText("⚠ Въведете Brave API ключ.")
            return
        try:
            self._store.save(s)
        except OSError as exc:
            self.error.setText(f"⚠ Неуспешен запис: {exc}")
            return
        self._settings = s
        self.accept()


class ManualPromoEditDialog(QDialog):
    """Add or edit one manual code."""

    def __init__(self, parent: QWidget | None, promo: ManualPromo | None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Промокод")
        p = promo or ManualPromo()
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.code = QLineEdit(p.code)
        self.code.setPlaceholderText("напр. WINTER10")
        form.addRow("Код", self.code)
        self.kind = QComboBox()
        self.kind.addItem("Процент (%)", "percent")
        self.kind.addItem("Сума (€) от поръчката", "amount")
        self.kind.addItem("Без изчисление (само показвай)", "none")
        self.value = QDoubleSpinBox()
        self.value.setRange(0, 5000)
        self.value.setDecimals(2)
        if p.discount_percent is not None:
            self.kind.setCurrentIndex(0)
            self.value.setValue(p.discount_percent)
        elif p.discount_amount_eur is not None:
            self.kind.setCurrentIndex(1)
            self.value.setValue(p.discount_amount_eur)
        elif promo is not None:
            self.kind.setCurrentIndex(2)
        row = QHBoxLayout()
        row.addWidget(self.kind)
        row.addWidget(self.value)
        form.addRow("Отстъпка", row)
        self.min_order = QDoubleSpinBox()
        self.min_order.setRange(0, 100000)
        self.min_order.setSuffix(" €")
        self.min_order.setSpecialValueText("—")
        self.min_order.setValue(p.min_order_eur or 0)
        form.addRow("Мин. поръчка", self.min_order)
        self.min_qty = QSpinBox()
        self.min_qty.setRange(0, 8)
        self.min_qty.setSpecialValueText("—")
        self.min_qty.setValue(p.min_quantity or 0)
        form.addRow("Мин. брой гуми", self.min_qty)
        self.brands = QLineEdit(", ".join(p.brands))
        self.brands.setPlaceholderText("празно = всички марки; напр. Nokian, Yokohama")
        form.addRow("Само за марки", self.brands)
        self.has_until = QCheckBox("Валиден до")
        self.until = QDateEdit()
        self.until.setCalendarPopup(True)
        self.until.setDisplayFormat("dd.MM.yyyy")
        if p.valid_until:
            d = date.fromisoformat(p.valid_until)
            self.until.setDate(QDate(d.year, d.month, d.day))
            self.has_until.setChecked(True)
        else:
            self.until.setDate(QDate.currentDate().addMonths(1))
        urow = QHBoxLayout()
        urow.addWidget(self.has_until)
        urow.addWidget(self.until)
        form.addRow("Срок", urow)
        self.conditions = QLineEdit(p.conditions)
        form.addRow("Условия", self.conditions)
        self.enabled = QCheckBox("Активен")
        self.enabled.setChecked(p.enabled)
        form.addRow(self.enabled)
        lay.addLayout(form)
        self.error = QLabel()
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def build(self) -> ManualPromo:
        """ManualPromo from the form."""
        kind = self.kind.currentData()
        value = self.value.value()
        until = ""
        if self.has_until.isChecked():
            until = self.until.date().toString("yyyy-MM-dd")
        return ManualPromo(
            code=self.code.text().strip(),
            discount_percent=value if kind == "percent" else None,
            discount_amount_eur=value if kind == "amount" else None,
            min_order_eur=self.min_order.value() or None,
            min_quantity=self.min_qty.value() or None,
            brands=[b.strip() for b in self.brands.text().split(",") if b.strip()],
            conditions=self.conditions.text().strip(),
            valid_until=until,
            enabled=self.enabled.isChecked(),
        )

    def _accept(self) -> None:
        errors = self.build().validate()
        if errors:
            self.error.setText("⚠ " + "; ".join(errors))
            return
        self.accept()


class ManualPromosDialog(QDialog):
    """List of manual codes for one shop."""

    def __init__(self, parent: QWidget | None, shop: str, promos: list[ManualPromo]) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Промокодове — {shop}")
        self.resize(640, 360)
        self._promos = [copy.deepcopy(p) for p in promos]
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Въведете код, който знаете (имейл, бюлетин, Facebook…). Ръчните кодове се "
            "прилагат към цената, когато отстъпката е ясна, и се пазят в настройките."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "muted")
        lay.addWidget(intro)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Код", "Отстъпка", "Валиден до", "Активен"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda _i: self._edit())
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, slot in (
            ("Добави", self._add),
            ("Редактирай", self._edit),
            ("Премахни", self._remove),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._fill()

    @property
    def promos(self) -> list[ManualPromo]:
        """Edited list."""
        return self._promos

    def _fill(self) -> None:
        self.table.setRowCount(len(self._promos))
        for r, p in enumerate(self._promos):
            if p.discount_percent is not None:
                disc = f"-{p.discount_percent:g}%"
            elif p.discount_amount_eur is not None:
                disc = f"-{p.discount_amount_eur:.2f} €"
            else:
                disc = "—"
            for c, text in enumerate(
                (p.code, disc, p.valid_until or "—", "да" if p.enabled else "не")
            ):
                self.table.setItem(r, c, QTableWidgetItem(text))

    def _row(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _add(self) -> None:
        dlg = ManualPromoEditDialog(self, None)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._promos.append(dlg.build())
            self._fill()

    def _edit(self) -> None:
        row = self._row()
        if row is None:
            return
        dlg = ManualPromoEditDialog(self, self._promos[row])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._promos[row] = dlg.build()
            self._fill()

    def _remove(self) -> None:
        row = self._row()
        if row is not None:
            del self._promos[row]
            self._fill()
