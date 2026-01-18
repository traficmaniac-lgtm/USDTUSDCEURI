"""Dialog for selecting exchanges."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)


class ExchangeSelectorDialog(QDialog):
    """Selectable list of exchanges."""

    def __init__(self, exchanges: list[str], selected: set[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Exchanges")
        self._checkboxes: dict[str, QCheckBox] = {}
        self._build_ui(exchanges, selected)

    def _build_ui(self, exchanges: list[str], selected: set[str]) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose exchanges to include in the feed:"))

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        for exchange in exchanges:
            checkbox = QCheckBox(exchange)
            checkbox.setChecked(exchange in selected)
            container_layout.addWidget(checkbox)
            self._checkboxes[exchange] = checkbox
        container_layout.addStretch()
        scroll_area.setWidget(container)
        layout.addWidget(scroll_area)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_exchanges(self) -> list[str]:
        return [
            exchange
            for exchange, checkbox in self._checkboxes.items()
            if checkbox.isChecked()
        ]
