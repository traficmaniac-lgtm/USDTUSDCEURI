"""Table model for scanner results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


@dataclass
class ScannerRow:
    """Container for a scanner row."""

    pair: str
    best_buy_exchange: str | None
    buy_ask: float | None
    best_sell_exchange: str | None
    sell_bid: float | None
    spread_abs: float | None
    spread_pct: float | None
    volume_24h: float | None
    stable_hits: int | None
    score: float | None
    status: str


class ScannerTableModel(QAbstractTableModel):
    """Qt table model for scanner results."""

    _headers = [
        "Pair",
        "Best Buy (Exchange)",
        "Buy Ask",
        "Best Sell (Exchange)",
        "Sell Bid",
        "Spread $",
        "Spread %",
        "24h Volume (median)",
        "Stable hits (K)",
        "Score",
        "Status",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[ScannerRow] = []

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
            if column in {2, 4, 5, 6, 7, 8, 9}:
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

    def set_rows(self, rows: list[ScannerRow]) -> None:
        """Replace the table rows with new items."""
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def notify_rows_updated(self) -> None:
        """Notify views that existing rows were updated."""
        if not self._rows:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._rows) - 1, len(self._headers) - 1)
        self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole])

    @staticmethod
    def _format_display(row: ScannerRow, column: int) -> str:
        if column == 0:
            return row.pair
        if column == 1:
            return row.best_buy_exchange or "—"
        if column == 2:
            return "—" if row.buy_ask is None else f"{row.buy_ask:.6f}"
        if column == 3:
            return row.best_sell_exchange or "—"
        if column == 4:
            return "—" if row.sell_bid is None else f"{row.sell_bid:.6f}"
        if column == 5:
            return "—" if row.spread_abs is None else f"{row.spread_abs:.6f}"
        if column == 6:
            return "—" if row.spread_pct is None else f"{row.spread_pct:.4f}%"
        if column == 7:
            return "—" if row.volume_24h is None else f"{row.volume_24h:,.0f}"
        if column == 8:
            return "—" if row.stable_hits is None else str(row.stable_hits)
        if column == 9:
            return "—" if row.score is None else f"{row.score:.2f}"
        if column == 10:
            return row.status
        return ""
