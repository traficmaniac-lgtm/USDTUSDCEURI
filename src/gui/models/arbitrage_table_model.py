"""Table model for arbitrage opportunities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


@dataclass(frozen=True)
class OpportunityRow:
    """Container for a single arbitrage opportunity row."""

    buy_exchange: str
    buy_ask: float
    sell_exchange: str
    sell_bid: float
    spread_abs: float
    spread_pct: float


class ArbitrageTableModel(QAbstractTableModel):
    """Qt table model for arbitrage opportunity rows."""

    _headers = [
        "Buy exchange",
        "Buy ask",
        "Sell exchange",
        "Sell bid",
        "Spread $",
        "Spread %",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[OpportunityRow] = []

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # type: ignore[override]
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:  # type: ignore[override]
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None

        row = self._rows[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            return self._format_display(row, column)

        if role == Qt.TextAlignmentRole:
            if column in {1, 3, 4, 5}:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:  # type: ignore[override]
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        if 0 <= section < len(self._headers):
            return self._headers[section]
        return None

    def update_opportunities(self, rows: list[OpportunityRow]) -> None:
        """Replace the table rows with new opportunities."""
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    @staticmethod
    def _format_display(row: OpportunityRow, column: int) -> str:
        if column == 0:
            return row.buy_exchange
        if column == 1:
            return f"{row.buy_ask:.6f}"
        if column == 2:
            return row.sell_exchange
        if column == 3:
            return f"{row.sell_bid:.6f}"
        if column == 4:
            return f"{row.spread_abs:.6f}"
        if column == 5:
            return f"{row.spread_pct:.4f}%"
        return ""
