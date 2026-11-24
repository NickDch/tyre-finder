"""Light and dark QSS themes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from string import Template


class ThemeName(StrEnum):
    """Available themes."""

    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True, slots=True)
class Palette:
    """Theme colours."""

    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_soft: str
    success: str
    success_soft: str
    danger: str
    warning: str
    summer: str
    winter: str
    allseason: str


PALETTES: dict[ThemeName, Palette] = {
    ThemeName.LIGHT: Palette(
        bg="#f3f5f9",
        surface="#ffffff",
        surface_alt="#f7f8fb",
        border="#e2e6ee",
        text="#1b2130",
        muted="#6b7385",
        accent="#ff5a1f",
        accent_hover="#e94a10",
        accent_text="#ffffff",
        accent_soft="#fff0ea",
        success="#12a150",
        success_soft="#e6f7ee",
        danger="#e03a3a",
        warning="#d98a00",
        summer="#f59e0b",
        winter="#3b82f6",
        allseason="#10b981",
    ),
    ThemeName.DARK: Palette(
        bg="#0f1218",
        surface="#181c25",
        surface_alt="#1f2430",
        border="#2a3040",
        text="#e8ebf2",
        muted="#8d95a8",
        accent="#ff7a45",
        accent_hover="#ff8f63",
        accent_text="#151515",
        accent_soft="#3a2419",
        success="#34d27b",
        success_soft="#173326",
        danger="#ff6b6b",
        warning="#f5b342",
        summer="#fbbf24",
        winter="#60a5fa",
        allseason="#34d399",
    ),
}

_QSS = Template("""
* { font-size: 10pt; }
QWidget { background: $bg; color: $text; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 6px;
           border-radius: 6px; }
QLabel { background: transparent; }
QFrame#Header { background: $surface; border-bottom: 1px solid $border; }
QLabel#AppTitle { font-size: 15pt; font-weight: 700; }
QLabel#AppSubtitle { color: $muted; }
QFrame#Sidebar { background: $surface; border-right: 1px solid $border; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QLabel[role="section"] { color: $muted; font-size: 8.5pt; font-weight: 700;
                         letter-spacing: 1px; padding-top: 6px; }
QLabel[role="muted"] { color: $muted; }
QLabel[role="h2"] { font-size: 13pt; font-weight: 700; }
QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {
    background: $surface_alt; border: 1px solid $border; border-radius: 8px;
    padding: 6px 10px; min-height: 20px; selection-background-color: $accent;
}
QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover, QLineEdit:hover { border-color: $accent; }
QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {
    border: 1px solid $accent; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border;
    selection-background-color: $accent_soft; selection-color: $text; outline: none; }
QPushButton { background: $surface_alt; border: 1px solid $border; border-radius: 8px;
              padding: 7px 14px; }
QPushButton:hover { border-color: $accent; color: $accent; }
QPushButton:pressed { background: $accent_soft; }
QPushButton:disabled { color: $muted; border-color: $border; }
QPushButton[variant="primary"] { background: $accent; color: $accent_text; border: none;
                                 font-weight: 700; padding: 9px 16px; }
QPushButton[variant="primary"]:hover { background: $accent_hover; color: $accent_text; }
QPushButton[variant="primary"]:disabled { background: $border; color: $muted; }
QPushButton[variant="ghost"] { background: transparent; border: none; padding: 6px 8px; }
QPushButton[variant="ghost"]:hover { background: $surface_alt; }
QPushButton[variant="link"] { background: transparent; border: none; color: $accent;
                              padding: 2px 4px; }
QPushButton[variant="open"] { background: $accent_soft; color: $accent; border: none;
                              font-weight: 600; padding: 5px 12px; }
QPushButton[variant="open"]:hover { background: $accent; color: $accent_text; }
QPushButton[variant="open-best"] { background: $success; color: #ffffff; border: none;
                                   font-weight: 700; padding: 5px 12px; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 0; border: none; }
QProgressBar { background: $surface_alt; border: none; border-radius: 4px; height: 8px;
               text-align: center; color: transparent; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QListWidget { background: $surface_alt; border: 1px solid $border; border-radius: 8px;
              padding: 4px; outline: none; }
QListWidget::item { padding: 4px 6px; border-radius: 6px; }
QListWidget::item:hover { background: $accent_soft; }
QListWidget::item:selected { background: $accent_soft; color: $text; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator, QListWidget::indicator, QTableWidget::indicator {
    width: 16px; height: 16px; border-radius: 4px; border: 1px solid $border;
    background: $surface; }
QCheckBox::indicator:checked, QListWidget::indicator:checked,
QTableWidget::indicator:checked { background: $accent; border-color: $accent;
    image: url($check_icon); }
QFrame#Card { background: $surface; border: 1px solid $border; border-radius: 14px; }
QFrame#Card:hover { border-color: $accent; }
QFrame#ImageBox { background: #ffffff; border: 1px solid $border; border-radius: 10px; }
QLabel[role="brand"] { color: $muted; font-weight: 700; font-size: 9pt; letter-spacing: 1px; }
QLabel[role="model"] { font-size: 13pt; font-weight: 700; }
QLabel[role="chip"] { background: $surface_alt; border: 1px solid $border; border-radius: 9px;
                      padding: 2px 8px; font-size: 9pt; }
QLabel[role="price"] { font-size: 18pt; font-weight: 800; color: $text; }
QLabel[role="badge"] { background: $success; color: #ffffff; border-radius: 9px;
                       padding: 3px 9px; font-size: 8.5pt; font-weight: 700; }
QLabel[role="badge-soft"] { background: $accent_soft; color: $accent; border-radius: 9px;
                            padding: 3px 9px; font-size: 8.5pt; font-weight: 700; }
QLabel[role="save"] { color: $success; font-weight: 600; }
QFrame#OfferRow { background: $surface_alt; border-radius: 8px; }
QFrame#OfferRow[best="true"] { background: $success_soft; border: 1px solid $success; }
QLabel[role="diff"] { color: $danger; font-size: 9pt; }
QLabel[role="best-label"] { color: $success; font-weight: 700; font-size: 9pt; }
QLabel[role="promo-code"] { background: $accent_soft; color: $accent; border: 1px dashed $accent;
                            border-radius: 6px; padding: 1px 7px; font-weight: 800;
                            font-family: "DejaVu Sans Mono", "Consolas", monospace; }
QLabel[role="promo-nocode"] { background: $accent_soft; color: $accent; border-radius: 6px;
                              padding: 1px 7px; font-weight: 700; font-size: 9pt; }
QLabel[role="promo-possible"] { background: $surface; color: $muted; border: 1px dashed $muted;
                                border-radius: 6px; padding: 1px 7px; font-weight: 700;
                                font-family: "DejaVu Sans Mono", "Consolas", monospace; }
QLabel[role="promo-price"] { color: $success; font-weight: 800; font-size: 11pt; }
QLabel[role="promo-meta"] { color: $muted; font-size: 8.5pt; }
QLabel[role="strike"] { color: $muted; text-decoration: line-through; }
QLabel[role="promo-flag"] { background: $success; color: #ffffff; border-radius: 8px;
                            padding: 2px 8px; font-size: 8.5pt; font-weight: 700; }
QLabel[role="warning-note"] { background: $accent_soft; color: $text;
                              border-left: 3px solid $warning; border-radius: 4px;
                              padding: 6px 8px; font-size: 8.5pt; }
QFrame#PromoLine { background: transparent; }
QPushButton[variant="mini"] { background: transparent; border: 1px solid $border;
                              border-radius: 6px; padding: 2px 6px; font-size: 8.5pt; }
QPushButton[variant="mini"]:hover { border-color: $accent; color: $accent; }
QFrame#EmptyState { background: transparent; }
QLabel#EmptyTitle { font-size: 15pt; font-weight: 700; }
QLabel#EmptyText { color: $muted; }
QTableWidget { background: $surface; border: 1px solid $border; border-radius: 8px;
               gridline-color: $border; selection-background-color: $accent_soft;
               selection-color: $text; }
QHeaderView::section { background: $surface_alt; border: none; padding: 6px;
                       border-bottom: 1px solid $border; font-weight: 600; }
QTabWidget::pane { border: 1px solid $border; border-radius: 8px; }
QTabBar::tab { background: transparent; padding: 8px 14px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { border-bottom: 2px solid $accent; color: $accent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar:horizontal { height: 0; }
QStatusBar { background: $surface; border-top: 1px solid $border; color: $muted; }
QDialog { background: $bg; }
QGroupBox { border: 1px solid $border; border-radius: 10px; margin-top: 14px; padding: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: $muted; }
""")


def stylesheet(name: ThemeName, check_icon: str = "") -> str:
    """Build the QSS for *name*; *check_icon* is a path to a check-mark image."""
    return _QSS.substitute(vars_of(PALETTES[name]), check_icon=check_icon)


def vars_of(palette: Palette) -> dict[str, str]:
    """Palette as a mapping for templates."""
    return {k: getattr(palette, k) for k in palette.__dataclass_fields__}
