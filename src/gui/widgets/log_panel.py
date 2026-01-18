"""Logging panel widget."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit


class LogPanel(QPlainTextEdit):
    """Read-only log display with colored levels."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)

    def append_log(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] [{level.upper():7}] {message}"
        color = self._color_for_level(level)
        self._append_colored_text(formatted, color)

    def _append_colored_text(self, text: str, color: QColor) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        cursor.insertText(text + "\n", fmt)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    @staticmethod
    def _color_for_level(level: str) -> QColor:
        normalized = level.lower()
        if normalized == "warning":
            return QColor("#b7791f")
        if normalized == "error":
            return QColor("#c53030")
        return QColor("#2d3748")
