"""Reusable widgets: result cards, brand filter, site status list, empty state."""

from __future__ import annotations

import webbrowser

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tyre_finder.data.brands import normalize_brand
from tyre_finder.logic.promo import Applicability, PromoEvaluation, promos_for_offer
from tyre_finder.models import (
    Confidence,
    PromoCode,
    PromoOrigin,
    Season,
    SiteResult,
    SiteStatusKind,
    TyreGroup,
    TyreOffer,
)
from tyre_finder.ui.icons import icon, pixmap
from tyre_finder.ui.image_loader import ImageLoader
from tyre_finder.ui.theme import Palette

SEASON_ICON = {Season.SUMMER: "sun", Season.WINTER: "snow", Season.ALL_SEASON: "allseason"}


def season_color(palette: Palette, season: Season | None) -> str:
    """Accent colour of a season."""
    if season is Season.SUMMER:
        return palette.summer
    if season is Season.WINTER:
        return palette.winter
    if season is Season.ALL_SEASON:
        return palette.allseason
    return palette.muted


def fmt_price(value: float, currency: str = "EUR") -> str:
    """'38.50 €'."""
    symbol = "€" if currency.upper() == "EUR" else "лв."
    return f"{value:,.2f} {symbol}".replace(",", " ")


def open_url(url: str) -> None:
    """Open *url* in the default browser."""
    webbrowser.open(url, new=2)


def _label(text: str, role: str | None = None, *, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


PROMO_WARNING = (
    "Промокодовете са събрани от публични източници (сайтовете на магазините, сайтове за "
    "купони, интернет) и може да са изтекли или с допълнителни условия. Проверете кода в "
    "количката на магазина преди поръчка."
)


def promo_date_text(promo: PromoCode) -> str:
    """'валиден до 30.11.2026' / 'публикуван на 01.11.2026' / 'проверено 23.11.2026'."""
    if promo.valid_until is not None:
        return f"валиден до {promo.valid_until:%d.%m.%Y}"
    if promo.published_at is not None:
        return f"публикуван на {promo.published_at:%d.%m.%Y}"
    if promo.origin is PromoOrigin.MANUAL:
        return "въведен ръчно, без срок"
    return f"на сайта към {promo.fetched_at:%d.%m.%Y}"


def promo_tooltip(promo: PromoCode, extra: str = "") -> str:
    """Rich tooltip with all conditions."""
    lines = [f"<b>{promo.title}</b>"]
    if promo.code:
        lines.append(f"Код: <b>{promo.code}</b>")
    if promo.code_note:
        lines.append(promo.code_note)
    if promo.discount_label:
        lines.append(f"Отстъпка: {promo.discount_label}")
    if promo.min_order_eur is not None:
        lines.append(f"Минимална поръчка: {promo.min_order_eur:.2f} €")
    if promo.min_quantity is not None:
        lines.append(f"Минимум {promo.min_quantity} бр.")
    if promo.brands:
        lines.append("Марки: " + ", ".join(b.title() for b in promo.brands))
    lines.append(promo_date_text(promo).capitalize())
    if promo.conditions:
        lines.append(f"<i>Условия:</i> {promo.conditions[:500]}")
    source = promo.origin.label_bg
    if promo.confidence is Confidence.LOW:
        source += f" · ниска сигурност ({promo.score:.0%}) — възможен код"
    lines.append(f"Източник: {source}<br>{promo.source_url}")
    if extra:
        lines.append(extra)
    lines.append(f"<small>{PROMO_WARNING}</small>")
    return "<br>".join(lines)


class PromoLine(QFrame):
    """One promo code under a shop row: badge, copy, discounted price, date, source."""

    def __init__(self, ev: PromoEvaluation, applied: bool, palette: Palette) -> None:
        super().__init__()
        self.setObjectName("PromoLine")
        promo = ev.promo
        possible = promo.confidence is Confidence.LOW
        lay = QHBoxLayout(self)
        lay.setContentsMargins(26, 0, 4, 0)
        lay.setSpacing(6)
        tag = QLabel()
        tag.setPixmap(pixmap("tag", palette.muted if possible else palette.accent, 14))
        lay.addWidget(tag)
        if possible:
            lay.addWidget(_label("възможен код", "promo-meta"))
        if promo.code:
            badge = _label(promo.code, "promo-possible" if possible else "promo-code")
            lay.addWidget(badge)
            copy = QPushButton()
            copy.setProperty("variant", "mini")
            copy.setIcon(icon("copy", palette.text, 13))
            copy.setToolTip("Копирай кода")
            copy.setCursor(Qt.CursorShape.PointingHandCursor)
            copy.clicked.connect(lambda _=False, c=promo.code, b=copy: _copy(c, b))
            lay.addWidget(copy)
        else:
            badge = _label(promo.code_note or "без код", "promo-nocode")
            badge.setMaximumWidth(330)
            lay.addWidget(badge)
        badge.setToolTip(promo_tooltip(promo, ev.reason))
        if promo.discount_label:
            lay.addWidget(_label(promo.discount_label, "best-label"))
        price = ev.price
        if applied and price is not None:
            if price.unit_price_eur is not None:
                text = f"= {fmt_price(price.unit_price_eur)} / бр."
            else:
                text = f"= {fmt_price(price.compare_price_eur or 0)} / бр. при 4 бр."
            lay.addWidget(_label(text, "promo-price"))
            if price.set4_total_eur is not None:
                lay.addWidget(_label(f"4 бр.: {fmt_price(price.set4_total_eur)}", "promo-meta"))
            if price.note:
                lay.addWidget(_label(f"({price.note})", "promo-meta"))
        elif price is not None and price.compare_price_eur is not None:
            lay.addWidget(
                _label(
                    f"≈ {fmt_price(price.compare_price_eur)} / бр. (не е приложен)", "promo-meta"
                )
            )
        elif ev.applicability is Applicability.NOT_COMPUTABLE:
            lay.addWidget(_label(f"цената не е изчислена: {ev.reason}", "promo-meta"))
        lay.addWidget(_label(promo_date_text(promo), "promo-meta"))
        lay.addStretch(1)
        src = QPushButton("Източник")
        src.setProperty("variant", "mini")
        src.setIcon(icon("link", palette.text, 12))
        src.setToolTip(promo.source_url)
        src.setCursor(Qt.CursorShape.PointingHandCursor)
        src.clicked.connect(lambda _=False, u=promo.source_url: open_url(u))
        lay.addWidget(src)
        self.setToolTip(promo_tooltip(promo, ev.reason))


def _copy(code: str, button: QPushButton) -> None:
    QGuiApplication.clipboard().setText(code)
    button.setText(" Копирано")
    QTimer.singleShot(1500, lambda: button.setText("") if _alive(button) else None)


def _alive(widget: QWidget) -> bool:
    from shiboken6 import isValid  # noqa: PLC0415 - optional at import time

    return bool(isValid(widget))


class OfferRow(QFrame):
    """One shop offer inside a result card (+ its promo codes)."""

    def __init__(
        self,
        offer: TyreOffer,
        best_price: float,
        is_best: bool,
        palette: Palette,
        shop_promos: list[PromoCode] | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("OfferRow")
        self.setProperty("best", "true" if is_best else "false")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 8, 6)
        outer.setSpacing(3)
        lay = QHBoxLayout()
        lay.setSpacing(10)
        outer.addLayout(lay)
        store = QLabel()
        store.setPixmap(pixmap("store", palette.success if is_best else palette.muted, 16))
        lay.addWidget(store)
        name = _label(offer.shop)
        name.setStyleSheet("font-weight: 600;")
        lay.addWidget(name)
        detail = _label(f"{offer.brand} {offer.model} · {offer.size_label}", "muted")
        detail.setToolTip(offer.raw_title or offer.model)
        detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(detail, 1)
        if is_best:
            lay.addWidget(_label("Най-изгодно", "best-label"))
        else:
            diff = offer.effective_price_eur - best_price
            lay.addWidget(_label(f"+{fmt_price(diff)}", "diff"))
        if offer.promo is not None:
            old = _label(fmt_price(offer.price, offer.currency), "strike")
            old.setToolTip("Цена без промокод")
            lay.addWidget(old)
            price = _label(fmt_price(offer.effective_price_eur), "promo-price")
            price.setToolTip(promo_tooltip(offer.promo.promo, offer.promo.note))
        else:
            price = _label(fmt_price(offer.price, offer.currency))
            price.setStyleSheet("font-weight: 700; font-size: 11pt;")
        price.setMinimumWidth(80)
        price.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(price)
        btn = QPushButton("Отвори")
        btn.setProperty("variant", "open-best" if is_best else "open")
        btn.setIcon(icon("external", "#ffffff" if is_best else palette.accent, 14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(offer.url)
        btn.clicked.connect(lambda _=False, u=offer.url: open_url(u))
        lay.addWidget(btn)
        applied = offer.promo.promo if offer.promo is not None else None
        evaluations = promos_for_offer(offer, shop_promos or [])
        evaluations.sort(
            key=lambda e: (e.promo is not applied, e.promo.confidence is Confidence.LOW)
        )
        for ev in evaluations[:4]:
            outer.addWidget(PromoLine(ev, ev.promo is applied, palette))


class ResultCard(QFrame):
    """A tyre model with all shops that sell it."""

    IMAGE_SIZE = 128

    def __init__(
        self,
        group: TyreGroup,
        palette: Palette,
        loader: ImageLoader,
        expanded: bool = False,
        promos_by_shop: dict[str, list[PromoCode]] | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._group = group
        self._promos = promos_by_shop or {}
        self._palette = palette
        self._offers_built = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(16)
        outer.addLayout(top)

        image_box = QFrame()
        image_box.setObjectName("ImageBox")
        image_box.setFixedSize(self.IMAGE_SIZE, self.IMAGE_SIZE)
        ib = QVBoxLayout(image_box)
        ib.setContentsMargins(6, 6, 6, 6)
        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setPixmap(pixmap("tyre", "#c9ced8", 56))
        self._image.setStyleSheet("background: transparent;")
        ib.addWidget(self._image)
        top.addWidget(image_box, 0, Qt.AlignmentFlag.AlignTop)
        if group.image_url:
            loader.request(group.image_url, self._set_image, owner=self)

        info = QVBoxLayout()
        info.setSpacing(4)
        info.addWidget(_label(group.brand.upper(), "brand"))
        model = _label(group.model or "—", "model", wrap=True)
        info.addWidget(model)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(_label(group.size_label, "chip"))
        if group.season is not None:
            season_chip = QWidget()
            sl = QHBoxLayout(season_chip)
            sl.setContentsMargins(0, 0, 0, 0)
            sl.setSpacing(4)
            ic = QLabel()
            ic.setPixmap(pixmap(SEASON_ICON[group.season], season_color(palette, group.season), 16))
            sl.addWidget(ic)
            sl.addWidget(_label(group.season.label_bg))
            chips.addWidget(season_chip)
        shops = group.shop_count
        chips.addWidget(_label(f"{shops} {'магазин' if shops == 1 else 'магазина'}", "badge-soft"))
        chips.addStretch(1)
        info.addLayout(chips)
        others = [o for o in group.sorted_offers[1:4]]
        if others:
            summary = " · ".join(
                f"{o.shop} {fmt_price(o.effective_price_eur)}{'*' if o.promo else ''}"
                for o in others
            )
            more = len(group.offers) - 1 - len(others)
            if more > 0:
                summary += f" · +{more}"
            info.addWidget(_label(f"Също: {summary}", "muted", wrap=True))
        info.addStretch(1)
        top.addLayout(info, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        right.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        best = group.best_offer
        badge = _label("★ Най-добра цена" if shops > 1 else "Цена", "badge")
        right.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight)
        if best.promo is not None:
            promo = best.promo.promo
            flag_text = f"с промокод {promo.code}" if promo.code else "с промоотстъпка"
            flag = _label(f"{flag_text} {promo.discount_label}".strip(), "promo-flag")
            flag.setToolTip(promo_tooltip(promo, best.promo.note))
            right.addWidget(flag, 0, Qt.AlignmentFlag.AlignRight)
            old = _label(f"без код {fmt_price(best.price, best.currency)}", "strike")
            right.addWidget(old, 0, Qt.AlignmentFlag.AlignRight)
            price = _label(fmt_price(best.effective_price_eur), "price")
            if best.promo.unit_price_eur is None:
                price.setToolTip("Цена на брой при покупка на 4 бр. с промокода")
        else:
            price = _label(fmt_price(best.price, best.currency), "price")
        right.addWidget(price, 0, Qt.AlignmentFlag.AlignRight)
        right.addWidget(_label(f"в {best.shop}", "muted"), 0, Qt.AlignmentFlag.AlignRight)
        if group.price_spread > 0.009:
            pct = group.price_spread / group.max_price * 100
            right.addWidget(
                _label(f"Спестявате до {fmt_price(group.price_spread)} ({pct:.0f}%)", "save"),
                0,
                Qt.AlignmentFlag.AlignRight,
            )
        btns = QHBoxLayout()
        btns.setSpacing(6)
        open_best = QPushButton("Купи от " + best.shop)
        open_best.setProperty("variant", "primary")
        open_best.setIcon(icon("external", palette.accent_text, 14))
        open_best.setCursor(Qt.CursorShape.PointingHandCursor)
        open_best.setToolTip(best.url)
        open_best.clicked.connect(lambda _=False, u=best.url: open_url(u))
        btns.addWidget(open_best)
        right.addSpacing(4)
        right.addLayout(btns)
        top.addLayout(right)

        self._toggle = QPushButton()
        self._toggle.setProperty("variant", "link")
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.clicked.connect(self.toggle)
        outer.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self._offers_box = QWidget()
        self._offers_layout = QVBoxLayout(self._offers_box)
        self._offers_layout.setContentsMargins(0, 0, 0, 0)
        self._offers_layout.setSpacing(6)
        self._offers_box.setMaximumHeight(0)
        outer.addWidget(self._offers_box)
        self._anim = QPropertyAnimation(self._offers_box, b"maximumHeight", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._unlock_height)
        self._expanded = False
        self._update_toggle()
        if expanded:
            self.set_expanded(True, animate=False)

    def _set_image(self, image: QImage) -> None:
        dpr = self.devicePixelRatioF()
        target = int((self.IMAGE_SIZE - 14) * dpr)
        scaled = image.scaled(
            target,
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pm = QPixmap.fromImage(scaled)
        pm.setDevicePixelRatio(dpr)
        self._image.setPixmap(pm)

    def _build_offers(self) -> None:
        if self._offers_built:
            return
        best = self._group.best_offer
        for offer in self._group.sorted_offers:
            self._offers_layout.addWidget(
                OfferRow(
                    offer,
                    self._group.best_price,
                    offer is best,
                    self._palette,
                    self._promos.get(offer.shop, []),
                )
            )
        self._offers_built = True

    def _update_toggle(self) -> None:
        n = len(self._group.offers)
        text = (
            f"Скрий сравнението ({n})"
            if self._expanded
            else f"Сравни цени във всички магазини ({n})"
        )
        self._toggle.setText(text)
        self._toggle.setIcon(
            icon("chevron-up" if self._expanded else "chevron-down", self._palette.accent, 14)
        )

    def toggle(self) -> None:
        """Expand/collapse the per-shop list."""
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool, animate: bool = True) -> None:
        """Show or hide the per-shop offers."""
        self._build_offers()
        self._expanded = expanded
        self._update_toggle()
        target = self._offers_box.sizeHint().height() if expanded else 0
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._offers_box.maximumHeight())
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._offers_box.setMaximumHeight(16777215 if expanded else 0)

    def _unlock_height(self) -> None:
        if self._expanded:
            self._offers_box.setMaximumHeight(16777215)


class EmptyState(QFrame):
    """Friendly placeholder for 'no search yet', 'loading' and 'no results'."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("EmptyState")
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(10)
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title = QLabel()
        self._title.setObjectName("EmptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text = QLabel()
        self._text.setObjectName("EmptyText")
        self._text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text.setWordWrap(True)
        self._text.setMaximumWidth(460)
        lay.addWidget(self._icon)
        lay.addWidget(self._title)
        lay.addWidget(self._text, 0, Qt.AlignmentFlag.AlignCenter)

    def show_state(self, icon_name: str, color: str, title: str, text: str) -> None:
        """Update the content."""
        self._icon.setPixmap(pixmap(icon_name, color, 72))
        self._title.setText(title)
        self._text.setText(text)


class BrandFilter(QWidget):
    """Checkable, searchable brand list with 'all' and 'clear'."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Търси марка…")
        self._search.setClearButtonEnabled(True)
        self._search.setToolTip("Филтрира списъка с марки")
        self._search.textChanged.connect(self._apply_search)
        lay.addWidget(self._search)
        row = QHBoxLayout()
        self._all = QPushButton("Всички")
        self._all.setToolTip("Избери всички марки")
        self._none = QPushButton("Изчисти")
        self._none.setToolTip("Премахни избора на всички марки")
        self._all.clicked.connect(lambda: self._set_all(True))
        self._none.clicked.connect(lambda: self._set_all(False))
        row.addWidget(self._all)
        row.addWidget(self._none)
        lay.addLayout(row)
        self._list = QListWidget()
        self._list.setMinimumHeight(180)
        self._list.setToolTip("Отметнете марките, които искате да виждате")
        self._list.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self._list)
        self._summary = QLabel()
        self._summary.setProperty("role", "muted")
        lay.addWidget(self._summary)
        self._selection: set[str] | None = None  # None = all brands
        self._updating = False

    def set_brands(self, brands: list[tuple[str, int | None]]) -> None:
        """Replace the list, keeping the user's selection (by normalised brand)."""
        self._updating = True
        self._list.clear()
        for name, count in brands:
            text = f"{name}  ({count})" if count else name
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = self._selection is None or normalize_brand(name) in self._selection
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self._list.addItem(item)
        self._updating = False
        self._apply_search(self._search.text())
        self._update_summary()

    def select_only(self, brands: set[str]) -> None:
        """Check only *brands* (display or normalised names)."""
        wanted = {normalize_brand(b) for b in brands}
        self._updating = True
        for item in self._items():
            name = normalize_brand(item.data(Qt.ItemDataRole.UserRole))
            on = name in wanted
            item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self._updating = False
        self._recompute()

    def selected(self) -> set[str] | None:
        """Selected brand names, or None if all are selected."""
        return None if self._selection is None else set(self._selection)

    def _items(self) -> list[QListWidgetItem]:
        return [self._list.item(i) for i in range(self._list.count())]

    def _set_all(self, checked: bool) -> None:
        self._updating = True
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for item in self._items():
            if not item.isHidden() or not self._search.text():
                item.setCheckState(state)
        self._updating = False
        self._recompute()

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        if not self._updating:
            self._recompute()

    def _recompute(self) -> None:
        items = self._items()
        checked = {
            normalize_brand(i.data(Qt.ItemDataRole.UserRole))
            for i in items
            if i.checkState() == Qt.CheckState.Checked
        }
        self._selection = None if len(checked) == len(items) else checked
        self._update_summary()
        self.changed.emit()

    def _update_summary(self) -> None:
        total = self._list.count()
        n = total if self._selection is None else len(self._selection)
        self._summary.setText(f"Избрани: {n} от {total}" if total else "")

    def _apply_search(self, text: str) -> None:
        needle = text.strip().lower()
        for item in self._items():
            item.setHidden(bool(needle) and needle not in item.text().lower())


_STATUS_ICON = {
    SiteStatusKind.PENDING: ("clock", "muted"),
    SiteStatusKind.RUNNING: ("refresh", "warning"),
    SiteStatusKind.OK: ("check", "success"),
    SiteStatusKind.EMPTY: ("minus", "muted"),
    SiteStatusKind.ERROR: ("alert", "danger"),
    SiteStatusKind.CANCELLED: ("x", "muted"),
}


class SiteStatusList(QListWidget):
    """Per-site progress and status."""

    def __init__(self) -> None:
        super().__init__()
        self.setIconSize(QSize(16, 16))
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._rows: dict[str, QListWidgetItem] = {}
        self._state: dict[str, tuple[SiteStatusKind, str]] = {}
        self._palette: Palette | None = None

    def show_sites(
        self, shops: list[str], palette: Palette, status: SiteStatusKind = SiteStatusKind.RUNNING
    ) -> None:
        """Show all shops with an initial status."""
        self._palette = palette
        self.clear()
        self._rows.clear()
        self._state.clear()
        for shop in shops:
            item = QListWidgetItem()
            self.addItem(item)
            self._rows[shop] = item
            self._set(
                item, shop, status, "Търсене…" if status is SiteStatusKind.RUNNING else "Готов"
            )
        self.setFixedHeight(min(27 * max(len(shops), 1) + 14, 420))

    def set_palette(self, palette: Palette) -> None:
        """Re-render icons in a new theme, keeping the statuses."""
        self._palette = palette
        for shop, item in self._rows.items():
            status, message = self._state[shop]
            tooltip = item.toolTip()
            self._set(item, shop, status, message)
            item.setToolTip(tooltip)

    def update_result(self, result: SiteResult) -> None:
        """Update one shop's row."""
        item = self._rows.get(result.shop)
        if item is not None:
            extra = f" · {result.elapsed_s:.1f} с" if result.elapsed_s else ""
            self._set(item, result.shop, result.status, result.message + extra)
            if result.detail:
                item.setToolTip(f"{result.shop}: {result.detail}")

    def _set(self, item: QListWidgetItem, shop: str, status: SiteStatusKind, message: str) -> None:
        assert self._palette is not None
        self._state[shop] = (status, message)
        name, color_attr = _STATUS_ICON[status]
        item.setIcon(icon(name, getattr(self._palette, color_attr), 16))
        item.setText(f"{shop} — {message}")
        item.setToolTip(f"{shop}: {message}")
