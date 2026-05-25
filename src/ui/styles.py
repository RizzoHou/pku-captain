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

        QLabel#HeaderWeather {{
            color: {PKU_RED_DARK};
            font-size: 13px;
            font-weight: 700;
            padding-top: 2px;
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

        QWidget#TodoList {{
            background: transparent;
        }}

        QFrame#TodoRow {{
            background: #fffaf7;
            border: 1px solid #eadbd5;
            border-left: 4px solid {PKU_RED};
            border-radius: 7px;
        }}

        QLabel#TodoMarker {{
            background: {SURFACE};
            border: 2px solid {PKU_RED};
            border-radius: 6px;
        }}

        QLabel#TodoTitle {{
            color: {INK};
            font-size: 12px;
            font-weight: 700;
        }}

        QLabel#TodoCourse {{
            color: {MUTED};
            font-size: 10px;
        }}

        QLabel#TodoDeadline {{
            color: {PKU_RED_DARK};
            font-size: 10px;
            font-weight: 700;
        }}

        QLabel#TodoMore {{
            color: {MUTED};
            font-size: 10px;
            padding-left: 4px;
        }}

        QPushButton#InlineToggleButton {{
            background: transparent;
            border: none;
            color: {PKU_RED};
            padding: 3px 0;
            font-size: 11px;
            font-weight: 700;
        }}

        QPushButton#InlineToggleButton:hover {{
            color: {PKU_RED_DARK};
            text-decoration: underline;
        }}

        QWidget#ScheduleGrid {{
            background: #fffdfb;
        }}

        QLabel#ScheduleHeader {{
            color: {PKU_RED_DARK};
            font-weight: 700;
            font-size: 12px;
            padding: 5px 3px;
            border-bottom: 1px solid {BORDER};
        }}

        QLabel#ScheduleSlot {{
            color: {MUTED};
            font-size: 11px;
            padding: 2px 0;
        }}

        QLabel#ScheduleEmpty {{
            min-height: 18px;
            border: 1px solid #f0e6e2;
            border-radius: 4px;
            background: #fffaf7;
        }}

        QPushButton#CourseBlock {{
            background: {PKU_RED};
            color: #ffffff;
            border: 1px solid {PKU_RED_DARK};
            border-radius: 6px;
            padding: 1px 4px;
            font-size: 11px;
            font-weight: 700;
            min-height: 24px;
        }}

        QPushButton#CourseBlock:hover {{
            background: {PKU_RED_DARK};
            color: #ffffff;
            border-color: {PKU_GOLD};
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

        QScrollArea#DashboardScroll {{
            border: none;
            background: transparent;
        }}

        QScrollArea#DashboardScroll > QWidget > QWidget {{
            background: {BACKGROUND};
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

        QFrame#MessageBubble {{
            border-radius: 8px;
            border: 1px solid #eadbd5;
            background: #ffffff;
        }}

        QFrame#MessageBubble[messageRole="user"] {{
            background: {PKU_RED};
            border-color: {PKU_RED};
        }}

        QFrame#MessageBubble[messageRole="system"] {{
            background: #fff6ed;
            border-color: #eadbd5;
        }}

        QFrame#MessageBubble QLabel#MessageAuthor {{
            color: {PKU_RED_DARK};
            font-weight: 800;
            font-size: 11px;
        }}

        QFrame#MessageBubble[messageRole="user"] QLabel#MessageAuthor,
        QFrame#MessageBubble[messageRole="user"] QLabel#MessageText {{
            color: #ffffff;
        }}

        QLabel#MessageText {{
            color: {INK};
            line-height: 1.35;
        }}

        QFrame#ToolTraceRow {{
            border: 1px solid #eadbd5;
            border-radius: 8px;
            background: #fffaf7;
        }}

        QFrame#ToolTraceRow[traceRole="pending"] {{
            border-left: 4px solid {PKU_RED};
        }}

        QFrame#ToolTraceRow[traceRole="success"] {{
            border-left: 4px solid #166534;
        }}

        QFrame#ToolTraceRow[traceRole="error"] {{
            border-left: 4px solid #b42318;
        }}

        QLabel#ToolTraceName {{
            color: {INK};
            font-weight: 700;
            font-size: 12px;
        }}

        QLabel#ToolTraceStatus {{
            color: {MUTED};
            font-size: 11px;
            font-weight: 700;
        }}

        QLabel#ToolTraceDetail {{
            color: #475467;
            background: #fffdfb;
            border: 1px solid #f0e6e2;
            border-radius: 6px;
            padding: 7px;
            font-family: Menlo, Monaco, Consolas, monospace;
            font-size: 10px;
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
