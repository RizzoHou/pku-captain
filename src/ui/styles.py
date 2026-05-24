"""Application-wide Qt styling."""

from __future__ import annotations

from PyQt6.QtWidgets import QApplication

PKU_RED = "#8c0000"
PKU_RED_DARK = "#650000"
PKU_GOLD = "#b78b36"
INK = "#1f2328"
MUTED = "#667085"
SURFACE = "#ffffff"
BACKGROUND = "#f7f3f0"
BORDER = "#e2d8d4"


def apply_app_style(app: QApplication) -> None:
    """Apply a restrained PKU-inspired red / white visual system."""
    app.setStyleSheet(
        f"""
        QMainWindow {{
            background: {BACKGROUND};
        }}

        QStatusBar {{
            background: #fffaf7;
            border-top: 1px solid {BORDER};
            color: {MUTED};
            padding: 3px 8px;
        }}

        QSplitter::handle {{
            background: {BORDER};
        }}

        QWidget#DashboardPanel,
        QWidget#ChatPanel,
        QWidget#ToolTracePanel {{
            background: {BACKGROUND};
        }}

        QLabel#DashboardTitle {{
            color: {PKU_RED};
            font-size: 26px;
            font-weight: 800;
        }}

        QLabel#DashboardSubtitle,
        QLabel#PanelSubtitle {{
            color: {MUTED};
        }}

        QLabel#SectionTitle {{
            color: {PKU_RED};
            font-size: 16px;
            font-weight: 700;
            padding-bottom: 4px;
            border-bottom: 2px solid {PKU_RED};
        }}

        QFrame#DashboardCard {{
            border: 1px solid {BORDER};
            border-radius: 8px;
            background: {SURFACE};
        }}

        QFrame#DashboardCard:hover {{
            border-color: {PKU_GOLD};
        }}

        QLabel#CardTitle {{
            color: {PKU_RED_DARK};
            font-size: 15px;
            font-weight: 700;
        }}

        QLabel#CardBody {{
            color: #475467;
            line-height: 1.35;
        }}

        QPushButton {{
            border: 1px solid {BORDER};
            border-radius: 7px;
            padding: 7px 12px;
            background: {SURFACE};
            color: {INK};
            font-weight: 600;
        }}

        QPushButton:hover {{
            border-color: {PKU_RED};
            color: {PKU_RED};
        }}

        QPushButton:disabled {{
            background: #f2eeee;
            color: #98a2b3;
            border-color: {BORDER};
        }}

        QPushButton#PrimaryButton {{
            background: {PKU_RED};
            border-color: {PKU_RED};
            color: #ffffff;
        }}

        QPushButton#PrimaryButton:hover {{
            background: {PKU_RED_DARK};
            border-color: {PKU_RED_DARK};
            color: #ffffff;
        }}

        QPushButton#SecondaryButton {{
            background: #fffaf7;
            color: {PKU_RED};
            border-color: #d8b9b5;
        }}

        QPlainTextEdit {{
            border: 1px solid {BORDER};
            border-radius: 8px;
            background: #fffdfb;
            color: {INK};
            padding: 8px;
            selection-background-color: {PKU_RED};
        }}

        QPlainTextEdit:focus {{
            border-color: {PKU_RED};
        }}

        QScrollArea {{
            background: transparent;
        }}

        QScrollArea#MessageScroll {{
            border: 1px solid {BORDER};
            border-radius: 8px;
            background: #fffaf7;
        }}

        QScrollArea#MessageScroll > QWidget > QWidget,
        QWidget#MessageHost {{
            background: #fffaf7;
        }}

        QLineEdit {{
            border: 1px solid {BORDER};
            border-radius: 7px;
            background: #fffdfb;
            padding: 7px 8px;
            color: {INK};
        }}

        QLineEdit:focus {{
            border-color: {PKU_RED};
        }}
        """
    )
