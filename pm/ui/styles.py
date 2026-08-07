# Anamorph - projection mapping
# Copyright (C) 2026 Kaio Augusto
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Studio Dark Luxury Theme for Projection Mapper
A refined, professional dark interface with cyan accents
"""

# Comprehensive QSS stylesheet
STUDIO_DARK_QSS = """
/* ============================================
   FONT IMPORTS & BASE THEME
   ============================================ */

/* Note: For production, load these fonts from files or Google Fonts */
/* Using system fallbacks that approximate the aesthetic */

* {
    font-family: "JetBrains Mono", "Fira Code", "SF Mono", "Cascadia Code", "Consolas", monospace;
}

QMainWindow {
    background-color: #0a0a0b;
    color: #e8e8e8;
}

/* Dialogs were never styled, so every one of them - outputs, help - opened
   as a light-grey panel with dark-theme widgets sitting on it. */
QDialog {
    background-color: #0f0f11;
    color: #e8e8e8;
}

/* ============================================
   TYPE HIERARCHY
   ============================================ */

QLabel#panelTitle {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: #00d4aa;
    padding: 4px 0px;
}

QLabel {
    font-size: 11px;
    color: #a0a0a0;
}

/* ============================================
   TOOLBAR - TOP CONTROL BAR
   ============================================ */

QToolBar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1a1a1c, stop:1 #141416);
    border-bottom: 1px solid #2a2a2e;
    padding: 6px 12px;
    spacing: 8px;
}

QToolBar::separator {
    background: #2a2a2e;
    width: 1px;
    margin: 4px 8px;
}

QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 6px 12px;
    color: #808080;
    font-size: 11px;
    font-weight: 500;
}

QToolButton:hover {
    background: rgba(0, 212, 170, 0.08);
    border-color: #2a3a34;
    color: #00d4aa;
}

QToolButton:pressed {
    background: rgba(0, 212, 170, 0.15);
}

QToolButton:checked {
    background: rgba(0, 212, 170, 0.12);
    border-color: #00d4aa;
    color: #00d4aa;
}

/* ============================================
   MENU BAR
   ============================================ */

QMenuBar {
    background: #0f0f11;
    color: #808080;
    padding: 0px 8px;
    font-size: 11px;
    border-bottom: 1px solid #1a1a1c;
}

QMenuBar::item {
    padding: 6px 12px;
    border-radius: 4px;
}

QMenuBar::item:selected {
    background: rgba(0, 212, 170, 0.1);
    color: #00d4aa;
}

QMenu {
    background: #1a1a1c;
    border: 1px solid #2a2a2e;
    border-radius: 6px;
    padding: 6px 0px;
}

QMenu::item {
    padding: 8px 32px 8px 16px;
    color: #a0a0a0;
    font-size: 11px;
}

QMenu::item:selected {
    background: rgba(0, 212, 170, 0.1);
    color: #00d4aa;
}

QMenu::separator {
    height: 1px;
    background: #2a2a2e;
    margin: 6px 12px;
}

/* ============================================
   SCROLL AREAS & PANELS
   ============================================ */

QScrollArea {
    background: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}

QScrollBar:vertical {
    background: #0f0f11;
    width: 8px;
    border-radius: 4px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #2a2a2e;
    border-radius: 4px;
    min-height: 32px;
}

QScrollBar::handle:vertical:hover {
    background: #3a3a3e;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background: #0f0f11;
    height: 8px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background: #2a2a2e;
    border-radius: 4px;
    min-width: 32px;
}

QScrollBar::handle:horizontal:hover {
    background: #3a3a3e;
}

/* ============================================
   SIDEBAR PANELS
   ============================================ */

#objectListPanel,
#propertyPanel {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #101012, stop:1 #0f0f11);
    border-right: 1px solid #1a1a1c;
}

#propertyPanel {
    border-right: none;
    border-left: 1px solid #1a1a1c;
}

/* ============================================
   GROUP BOXES - PROPERTY SECTIONS
   ============================================ */

QGroupBox {
    background: rgba(26, 26, 30, 0.5);
    border: 1px solid #1e1e22;
    border-radius: 6px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
    font-size: 11px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 0px 6px;
    color: #707070;
    font-weight: 600;
    letter-spacing: 0.5px;
    background: #0a0a0b;
}

/* ============================================
   INPUT WIDGETS
   ============================================ */

QLineEdit {
    background: #0f0f11;
    border: 1px solid #2a2a2e;
    border-radius: 4px;
    padding: 6px 10px;
    color: #e8e8e8;
    font-size: 11px;
    selection-background-color: rgba(0, 212, 170, 0.3);
}

QLineEdit:hover {
    border-color: #3a3a3e;
}

QLineEdit:focus {
    border-color: #00d4aa;
    background: #101014;
}

QComboBox {
    background: #0f0f11;
    border: 1px solid #2a2a2e;
    border-radius: 4px;
    padding: 6px 10px;
    color: #e8e8e8;
    font-size: 11px;
    min-width: 80px;
}

QComboBox:hover {
    border-color: #3a3a3e;
}

QComboBox:focus {
    border-color: #00d4aa;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #606060;
    margin-right: 6px;
}

QComboBox QAbstractItemView {
    background: #1a1a1c;
    border: 1px solid #2a2a2e;
    border-radius: 4px;
    selection-background-color: rgba(0, 212, 170, 0.2);
    padding: 4px;
}

QSpinBox,
QDoubleSpinBox {
    background: #0f0f11;
    border: 1px solid #2a2a2e;
    border-radius: 4px;
    padding: 4px 8px;
    color: #e8e8e8;
    font-size: 11px;
}

QSpinBox:hover,
QDoubleSpinBox:hover {
    border-color: #3a3a3e;
}

QSpinBox:focus,
QDoubleSpinBox:focus {
    border-color: #00d4aa;
}

QSpinBox::up-button,
QDoubleSpinBox::up-button {
    background: transparent;
    border: none;
    width: 16px;
}

QSpinBox::down-button,
QDoubleSpinBox::down-button {
    background: transparent;
    border: none;
    width: 16px;
}

QSpinBox::up-arrow,
QDoubleSpinBox::up-arrow {
    image: none;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 4px solid #606060;
}

QSpinBox::down-arrow,
QDoubleSpinBox::down-arrow {
    image: none;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid #606060;
}

/* ============================================
   SLIDERS
   ============================================ */

QSlider::groove:horizontal {
    background: #1a1a1e;
    height: 4px;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00d4aa, stop:1 #00a080);
    width: 14px;
    height: 14px;
    margin: -5px 0px;
    border-radius: 7px;
    border: 1px solid #008866;
}

QSlider::handle:horizontal:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00e8bb, stop:1 #00b090);
}

QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00d4aa, stop:1 #00a080);
    border-radius: 2px;
}

QSlider::groove:vertical {
    background: #1a1a1e;
    width: 4px;
    border-radius: 2px;
}

QSlider::handle:vertical {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00d4aa, stop:1 #00a080);
    width: 14px;
    height: 14px;
    margin: 0px -5px;
    border-radius: 7px;
    border: 1px solid #008866;
}

/* ============================================
   BUTTONS
   ============================================ */

QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #2a2a2e, stop:1 #222226);
    border: 1px solid #3a3a3e;
    border-radius: 4px;
    padding: 6px 14px;
    color: #b0b0b0;
    font-size: 11px;
    font-weight: 500;
}

QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #32323a, stop:1 #2a2a32);
    border-color: #4a4a4e;
    color: #e0e0e0;
}

QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #222226, stop:1 #2a2a2e);
}

QPushButton:disabled {
    background: #1a1a1e;
    border-color: #2a2a2e;
    color: #505050;
}

/* Primary action button */
QPushButton#primaryButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00d4aa, stop:1 #00a080);
    border-color: #008866;
    color: #000000;
    font-weight: 600;
}

QPushButton#primaryButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00e8bb, stop:1 #00b090);
}

/* ============================================
   CHECKBOXES
   ============================================ */

QCheckBox {
    spacing: 8px;
    color: #a0a0a0;
    font-size: 11px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #3a3a3e;
    border-radius: 3px;
    background: #0f0f11;
}

QCheckBox::indicator:hover {
    border-color: #4a4a4e;
}

QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00d4aa, stop:1 #00a080);
    border-color: #008866;
}

QCheckBox::indicator:checked:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #00e8bb, stop:1 #00b090);
}

/* ============================================
   LIST WIDGETS
   ============================================ */

QListWidget {
    background: transparent;
    border: none;
    outline: none;
    font-size: 11px;
}

QListWidget::item {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 8px 10px;
    margin: 2px 4px;
    color: #909090;
}

QListWidget::item:hover {
    background: rgba(0, 212, 170, 0.06);
    border-color: #1a2a24;
    color: #c0c0c0;
}

QListWidget::item:selected {
    background: rgba(0, 212, 170, 0.12);
    border-color: #00d4aa;
    color: #00d4aa;
}

QListWidget::item:selected:!active {
    background: rgba(0, 212, 170, 0.08);
    border-color: #1a3a2a;
    color: #00d4aa;
}

/* ============================================
   STATUS BAR
   ============================================ */

QStatusBar {
    background: #0a0a0b;
    border-top: 1px solid #1a1a1c;
    color: #505050;
    font-size: 10px;
    padding: 4px 12px;
}

QStatusBar::item {
    border: none;
}

/* ============================================
   SPLITTER
   ============================================ */

QSplitter::handle {
    background: #1a1a1c;
}

QSplitter::handle:horizontal {
    width: 1px;
}

QSplitter::handle:vertical {
    height: 1px;
}

QSplitter::handle:hover {
    background: #00d4aa;
}

/* ============================================
   TOOLTIP
   ============================================ */

QToolTip {
    background: #1a1a1c;
    border: 1px solid #2a2a2e;
    border-radius: 4px;
    padding: 6px 10px;
    color: #c0c0c0;
    font-size: 10px;
}

/* ============================================
   SPECIAL WIDGETS
   ============================================ */

/* Color picker button */
QPushButton#colorButton {
    min-width: 100px;
    border: 2px solid #2a2a2e;
}

/* Media button styling */
QPushButton#mediaButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1a2a24, stop:1 #142018);
    border-color: #1a3a2a;
    color: #00d4aa;
}

QPushButton#mediaButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #203a2e, stop:1 #1a2820);
}

/* Header label for sections */
QLabel#headerLabel {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #505050;
}

/* Value display labels */
QLabel#valueLabel {
    font-size: 11px;
    font-weight: 600;
    color: #e0e0e0;
    font-family: "JetBrains Mono", "Fira Code", monospace;
}

/* ============================================
   CUSTOM CLASSES
   ============================================ */

PanelTitle {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: #00d4aa;
}

SectionHeader {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
    color: #606060;
    padding: 8px 0px 4px 0px;
}

PropertyValue {
    font-size: 11px;
    color: #c0c0c0;
}

"""

# Color palette for programmatic use
COLORS = {
    'bg_darkest': '#0a0a0b',
    'bg_dark': '#0f0f11',
    'bg_medium': '#141416',
    'bg_light': '#1a1a1c',
    'bg_hover': '#222226',
    'border_dark': '#1a1a1c',
    'border_medium': '#2a2a2e',
    'border_light': '#3a3a3e',
    'text_primary': '#e8e8e8',
    'text_secondary': '#a0a0a0',
    'text_muted': '#606060',
    'accent_primary': '#00d4aa',
    'accent_secondary': '#00a080',
    'accent_dark': '#008866',
    'accent_glow': '#00ffcc',
}
