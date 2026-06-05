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

        QLabel#DialogTitle {{
            color: {PKU_RED};
            font-size: 20px;
            font-weight: 800;
        }}

        QLabel#DialogSubtitle {{
            color: {MUTED};
            font-size: 12px;
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

        QPushButton#HeaderTreeholeButton {{
            background: #fffaf7;
            color: {PKU_RED};
            border-color: #d8b9b5;
            min-width: 58px;
        }}

        QPushButton#HeaderTreeholeButton[hasUnread="true"] {{
            background: {PKU_RED};
            border-color: {PKU_RED};
            color: #ffffff;
        }}

        QPushButton#HeaderTreeholeButton[hasUnread="true"]:hover {{
            background: {PKU_RED_DARK};
            border-color: {PKU_RED_DARK};
            color: #ffffff;
        }}

        QWidget#TreeholeList {{
            background: transparent;
        }}

        QFrame#TreeholeRow,
        QFrame#TreeholeDetailRow {{
            background: #fffaf7;
            border: 1px solid #eadbd5;
            border-left: 4px solid {PKU_GOLD};
            border-radius: 7px;
        }}

        QFrame#TreeholeAuthPanel {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 8px;
        }}

        QFrame#PLibAuthPanel {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 8px;
        }}

        QLabel#TreeholeAuthTitle {{
            color: {PKU_RED_DARK};
            font-size: 16px;
            font-weight: 800;
        }}

        QLabel#TreeholeAuthSubtitle {{
            color: {MUTED};
            font-size: 11px;
        }}

        QLabel#TreeholeAuthStep {{
            color: {PKU_RED_DARK};
            font-size: 11px;
            font-weight: 800;
            padding-top: 2px;
        }}

        QLabel#TreeholeAuthStatus {{
            color: {PKU_RED_DARK};
            background: #fff6ed;
            border: 1px solid #eadbd5;
            border-radius: 8px;
            padding: 6px 9px;
            font-size: 11px;
            font-weight: 700;
        }}

        QLabel#TreeholeAuthStatus[authState="ok"] {{
            color: #166534;
            background: #f0fdf4;
            border-color: #bbf7d0;
        }}

        QLabel#TreeholeAuthStatus[authState="error"] {{
            color: #b42318;
            background: #fff6ed;
            border-color: #f4c7c3;
        }}

        QLabel#PLibAuthStatus {{
            color: {PKU_RED_DARK};
            background: #fff6ed;
            border: 1px solid #eadbd5;
            border-radius: 8px;
            padding: 8px 10px;
            font-size: 12px;
            font-weight: 700;
        }}

        QLabel#PLibAuthStatus[authState="ok"] {{
            color: #166534;
            background: #f0fdf4;
            border-color: #bbf7d0;
        }}

        QLabel#PLibAuthStatus[authState="error"] {{
            color: #b42318;
            background: #fff6ed;
            border-color: #f4c7c3;
        }}

        QLabel#PLibAuthStatus[authState="pending"] {{
            color: {PKU_RED_DARK};
            background: #fffaf7;
            border-color: #d8b9b5;
        }}

        QLabel#TreeholePreview {{
            color: {PKU_RED_DARK};
            font-size: 11px;
            font-weight: 600;
        }}

        QLabel#TreeholeComment {{
            color: {INK};
            background: #fffdfb;
            border: 1px solid #f0e6e2;
            border-radius: 6px;
            padding: 7px;
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

        QFrame#CourseBlock {{
            background: {PKU_RED};
            color: #ffffff;
            border: 1px solid {PKU_RED_DARK};
            border-radius: 6px;
            min-height: 24px;
        }}

        QFrame#CourseBlock:hover {{
            background: {PKU_RED_DARK};
            color: #ffffff;
            border-color: {PKU_GOLD};
        }}

        QLabel#CourseBlockTitle {{
            color: #ffffff;
            font-size: 11px;
            font-weight: 800;
        }}

        QLabel#CourseBlockDetail {{
            color: #ffe7df;
            font-size: 9px;
            font-weight: 500;
        }}

        QLabel#CourseBlockNote {{
            color: #fff1cc;
            font-size: 9px;
            font-weight: 650;
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

        QPushButton#ThinkingToggleButton {{
            background: #fffaf7;
            color: {PKU_RED};
            border: 1px solid #d8b9b5;
            border-radius: 7px;
            padding: 7px 12px;
            font-weight: 700;
        }}

        QPushButton#ThinkingToggleButton:hover {{
            background: #fff6ed;
            border-color: {PKU_RED};
            color: {PKU_RED_DARK};
        }}

        QPushButton#ThinkingToggleButton[thinkingVisible="true"] {{
            background: {PKU_RED};
            border-color: {PKU_RED};
            color: #ffffff;
        }}

        QPushButton#ThinkingToggleButton[thinkingVisible="true"]:hover {{
            background: {PKU_RED_DARK};
            border-color: {PKU_RED_DARK};
            color: #ffffff;
        }}

        QPushButton#ListRowButton {{
            background: #fffaf7;
            color: {INK};
            border: 1px solid #eadbd5;
            border-left: 4px solid {PKU_GOLD};
            border-radius: 7px;
            padding: 8px 10px;
            text-align: left;
            font-size: 11px;
            font-weight: 650;
        }}

        QPushButton#ListRowButton:hover {{
            background: #fff6ed;
            color: {PKU_RED_DARK};
            border-color: #d8b9b5;
            border-left-color: {PKU_RED};
        }}

        QLabel#DialogBody {{
            color: {INK};
            background: #fffdfb;
            border: 1px solid #f0e6e2;
            border-radius: 8px;
            padding: 10px;
            line-height: 1.35;
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

        QScrollArea#TreeholeMessageScroll {{
            border: 1px solid {BORDER};
            border-radius: 8px;
            background: #fffaf7;
        }}

        QScrollArea#TreeholeMessageScroll > QWidget > QWidget {{
            background: #fffaf7;
        }}

        QScrollArea#DetailScroll {{
            border: 1px solid {BORDER};
            border-radius: 8px;
            background: #fffaf7;
        }}

        QScrollArea#DetailScroll > QWidget > QWidget {{
            background: #fffaf7;
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

        QFrame#InlineToolCall {{
            border: 1px solid #eadbd5;
            border-left: 4px solid {PKU_RED};
            border-radius: 8px;
            background: #fffaf7;
        }}

        QFrame#InlineToolCall[traceRole="success"] {{
            border-left-color: #166534;
        }}

        QFrame#InlineToolCall[traceRole="error"] {{
            border-left-color: #b42318;
        }}

        QLabel#InlineToolName {{
            color: {INK};
            font-size: 12px;
            font-weight: 800;
        }}

        QLabel#InlineToolStatus {{
            color: {MUTED};
            font-size: 11px;
            font-weight: 800;
            padding: 2px 6px;
            background: #fffdfb;
            border: 1px solid #f0e6e2;
            border-radius: 6px;
        }}

        QLabel#InlineToolDetail {{
            color: #475467;
            background: #fffdfb;
            border: 1px solid #f0e6e2;
            border-radius: 6px;
            padding: 7px;
            font-family: Menlo, Monaco, Consolas, monospace;
            font-size: 10px;
        }}

        QFrame#InlineThinking {{
            border: 1px dashed #d8c4be;
            border-left: 4px solid {PKU_GOLD};
            border-radius: 8px;
            background: #fbf7f4;
        }}

        QLabel#InlineThinkingTitle {{
            color: {MUTED};
            font-size: 11px;
            font-weight: 800;
        }}

        QPlainTextEdit#InlineThinkingBody {{
            background: transparent;
            border: none;
            padding: 0;
            color: #6b6259;
            font-size: 11px;
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

        QComboBox {{
            border: 1px solid {BORDER};
            border-radius: 7px;
            background: #fffdfb;
            padding: 7px 8px;
            color: {INK};
            font-weight: 600;
        }}

        QComboBox:hover,
        QComboBox:focus {{
            border-color: {PKU_RED};
        }}

        QListWidget#PLibResultList {{
            border: 1px solid {BORDER};
            border-radius: 8px;
            background: #fffaf7;
            padding: 6px;
            color: {INK};
        }}

        QListWidget#PLibResultList::item {{
            background: #fffdfb;
            border: 1px solid #f0e6e2;
            border-left: 4px solid {PKU_GOLD};
            border-radius: 7px;
            padding: 9px;
            margin: 4px 2px;
        }}

        QListWidget#PLibResultList::item:selected {{
            border-left-color: {PKU_RED};
            border-color: #d8b9b5;
            background: #fff6ed;
            color: {INK};
        }}

        QLineEdit#TreeholeAuthInput {{
            min-height: 18px;
        }}
        """
    )
