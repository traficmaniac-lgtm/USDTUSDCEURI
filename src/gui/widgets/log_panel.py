"""Logging panel widget."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit


class LogPanel(QPlainTextEdit):
    """Read-only log display with colored levels."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setStyleSheet("background-color: #0b0f14; color: #e2e8f0;")

    def append_log(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_text = level.upper()
        prefix = f"[{timestamp}] [{level_text}] "
        color = self._color_for_level(level_text)
        self._append_colored_text(prefix, message, color)

    def _append_colored_text(self, prefix: str, message: str, color: QColor) -> None:
        scroll_bar = self.verticalScrollBar()
        previous_value = scroll_bar.value()
        was_at_bottom = previous_value >= scroll_bar.maximum()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        prefix_format = QTextCharFormat()
        prefix_format.setForeground(color)
        prefix_format.setFontWeight(QFont.Bold)
        message_format = QTextCharFormat()
        message_format.setForeground(color)
        cursor.insertText(prefix, prefix_format)
        cursor.insertText(message + "\n", message_format)
        if was_at_bottom:
            self.setTextCursor(cursor)
            self.ensureCursorVisible()
        else:
            scroll_bar.setValue(previous_value)

    @staticmethod
    def _color_for_level(level: str) -> QColor:
        normalized = level.lower()
        if normalized in {"success", "ok"}:
            return QColor("#48bb78")
        if normalized == "warning":
            return QColor("#f6e05e")
        if normalized == "error":
            return QColor("#f56565")
        return QColor("#e2e8f0")
