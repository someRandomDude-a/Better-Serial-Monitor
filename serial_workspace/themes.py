"""Shared Qt and plotting palettes. Glass is opaque for portability and legibility."""

PALETTES = {
    "Dark": dict(bg="#10141d", panel="#181e2a", raised="#202838", text="#e7edf7",
                 muted="#95a3ba", border="#2c374b", plot="#121823", selection="#273c55"),
    "Light": dict(bg="#f0f3f8", panel="#ffffff", raised="#e8edf5", text="#18253b",
                  muted="#53647b", border="#d3dce8", plot="#ffffff", selection="#dbeafe"),
    "AMOLED": dict(bg="#000000", panel="#080808", raised="#151515", text="#f0f0f0",
                   muted="#a6adb8", border="#292929", plot="#000000", selection="#172d3d"),
    "Liquid Glass": dict(bg="#dfeaf3", panel="#f3f8fc", raised="#e4eef7", text="#1c354c",
                         muted="#526c82", border="#b9cfdf", plot="#f2f8fc", selection="#d2e9f8"),
}


def stylesheet(settings):
    p = PALETTES[settings.theme]
    pad = 5 if settings.compact else 8
    radius = 15 if settings.theme == "Liquid Glass" else 8
    # A dark foreground on the accent preserves contrast even for bright custom colors.
    accent = settings.accent
    rgb = [int(accent[i:i + 2], 16) for i in (1, 3, 5)]
    ink = "#10141d" if sum(a * b for a, b in zip(rgb, (0.2126, 0.7152, 0.0722))) > 145 else "#ffffff"
    return f"""
        QWidget {{ color: {p['text']}; font-family: 'Segoe UI', 'Noto Sans', sans-serif;
                   font-size: {settings.font_size}pt; }}
        QMainWindow, QDialog, QWidget#workspace {{ background: {p['bg']}; }}
        QWidget#settingsContent {{ background: {p['panel']}; }}
        QFrame#card, QFrame#topbar, QFrame#sidebar {{ background: {p['panel']};
                     border: 1px solid {p['border']}; border-radius: {radius}px; }}
        QFrame#sidebar {{ border-radius: 0px; border-width: 0px 1px 0px 0px; }}
        QLabel {{ background: transparent; border: none; }}
        QLabel#muted {{ color: {p['muted']}; }}
        QLabel#eyebrow {{ color: {p['muted']}; font-size: 9pt; font-weight: 600; }}
        QLabel#title {{ font-size: 22pt; font-weight: 600; }}
        QLabel#metric {{ font-size: 19pt; font-weight: 600; }}
        QLabel#section {{ font-size: 12pt; font-weight: 600; }}
        QPushButton, QToolButton {{ background: {p['raised']}; border: 1px solid {p['border']};
                     border-radius: 6px; padding: {pad}px 12px; }}
        QPushButton:hover, QToolButton:hover {{ border-color: {accent}; background: {p['selection']}; }}
        QPushButton:pressed {{ background: {p['selection']}; }}
        QPushButton:disabled {{ color: {p['muted']}; background: {p['panel']}; }}
        QPushButton#primary {{ background: {accent}; color: {ink}; border-color: {accent}; font-weight: 600; }}
        QPushButton#nav {{ text-align: left; background: transparent; border: none; padding: 12px; }}
        QPushButton#nav:checked {{ background: {p['selection']}; color: {p['text']};
                                 border-left: 3px solid {accent}; border-radius: 5px; font-weight: 600; }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {p['plot']};
                     border: 1px solid {p['border']}; border-radius: 5px; padding: {pad}px; selection-background-color: {p['selection']}; }}
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {accent}; }}
        QComboBox QAbstractItemView {{ background: {p['panel']}; selection-background-color: {p['selection']}; }}
        QPlainTextEdit, QTextBrowser, QTableWidget {{ background: {p['plot']}; border: 1px solid {p['border']};
                     border-radius: 6px; selection-background-color: {p['selection']}; }}
        QPlainTextEdit {{ font-family: 'Consolas', 'DejaVu Sans Mono', monospace; }}
        QCheckBox {{ spacing: 7px; padding: 3px; }}
        QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {p['muted']};
                               background: {p['plot']}; border-radius: 3px; }}
        QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
        QTabWidget::pane {{ border: 1px solid {p['border']}; background: {p['panel']}; border-radius: 6px; }}
        QTabBar::tab {{ background: {p['raised']}; padding: 10px 14px; border-bottom: 2px solid transparent; }}
        QTabBar::tab:selected {{ background: {p['panel']}; border-color: {accent}; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollBar:vertical {{ width: 10px; background: {p['panel']}; }}
        QScrollBar::handle:vertical {{ background: {p['border']}; min-height: 28px; border-radius: 4px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QHeaderView::section {{ background: {p['raised']}; padding: 8px; border: none; text-align: left; }}
        QStatusBar {{ background: {p['panel']}; color: {p['muted']}; border-top: 1px solid {p['border']}; }}
        QMenu {{ background: {p['panel']}; border: 1px solid {p['border']}; padding: 5px; }}
        QMenu::item {{ padding: 7px 24px; }}
        QMenu::item:selected {{ background: {p['selection']}; }}
        QToolTip {{ background: {p['raised']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 6px; }}
        QSplitter::handle {{ background: {p['border']}; }}
    """
