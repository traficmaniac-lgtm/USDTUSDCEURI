"""Table model for displaying exchange quotes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


@dataclass(frozen=True)
class QuoteRow:
    """Container for a single quote row."""

    exchange: str
    bid: float
    ask: float
    last: float
    spread: float
    timestamp: str
    status: str


class QuotesTableModel(QAbstractTableModel):
    """Qt table model for quote rows."""

    _headers = [
        "Exchange",
        "Bid",
        "Ask",
        "Last",
        "Spread",
        "Timestamp",
        "Status",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[QuoteRow] = []

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
            if column in {1, 2, 3, 4}:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)

        if role == Qt.ForegroundRole and column == 6:
            return self._status_color(row.status)

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

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:  # type: ignore[override]
        if not self._rows:
            return
        key_funcs = {
            0: lambda row: row.exchange,
            1: lambda row: row.bid,
            2: lambda row: row.ask,
            3: lambda row: row.last,
            4: lambda row: row.spread,
            5: lambda row: row.timestamp,
            6: lambda row: row.status,
        }
        key_func = key_funcs.get(column, lambda row: row.exchange)
        reverse = order == Qt.SortOrder.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=key_func, reverse=reverse)
        self.layoutChanged.emit()

    def update_quotes(self, quotes: list[dict[str, Any]]) -> None:
        """Replace the table rows with new quote dictionaries."""
        self.beginResetModel()
        self._rows = [
            QuoteRow(
                exchange=str(item.get("exchange", "")),
                bid=float(item.get("bid", 0.0)),
                ask=float(item.get("ask", 0.0)),
                last=float(item.get("last", 0.0)),
                spread=float(item.get("spread", 0.0)),
                timestamp=str(item.get("timestamp", "")),
                status=str(item.get("status", "")),
            )
            for item in quotes
        ]
        self.endResetModel()

    def update_exchange_quote(self, quote: dict[str, Any]) -> None:
        """Update a single exchange row with new quote data."""
        exchange = str(quote.get("exchange", ""))
        if not exchange:
            return
        for index, row in enumerate(self._rows):
            if row.exchange != exchange:
                continue
            self._rows[index] = QuoteRow(
                exchange=exchange,
                bid=float(quote.get("bid", 0.0)),
                ask=float(quote.get("ask", 0.0)),
                last=float(quote.get("last", 0.0)),
                spread=float(quote.get("spread", 0.0)),
                timestamp=str(quote.get("timestamp", "")),
                status=str(quote.get("status", "")),
            )
            top_left = self.index(index, 0)
            bottom_right = self.index(index, self.columnCount() - 1)
            self.dataChanged.emit(top_left, bottom_right)
            return

        self.beginInsertRows(QModelIndex(), len(self._rows), len(self._rows))
        self._rows.append(
            QuoteRow(
                exchange=exchange,
                bid=float(quote.get("bid", 0.0)),
                ask=float(quote.get("ask", 0.0)),
                last=float(quote.get("last", 0.0)),
                spread=float(quote.get("spread", 0.0)),
                timestamp=str(quote.get("timestamp", "")),
                status=str(quote.get("status", "")),
            )
        )
        self.endInsertRows()

    def _format_display(self, row: QuoteRow, column: int) -> str:
        if column == 0:
            return row.exchange
        if column == 1:
            return f"{row.bid:.6f}"
        if column == 2:
            return f"{row.ask:.6f}"
        if column == 3:
            return f"{row.last:.6f}"
        if column == 4:
            return f"{row.spread:.6f}"
        if column == 5:
            return row.timestamp
        if column == 6:
            return row.status
        return ""

    @staticmethod
    def _status_color(status: str):
        normalized = status.lower()
        if normalized == "ok":
            return Qt.GlobalColor.darkGreen
        if normalized == "warning":
            return Qt.GlobalColor.darkYellow
        if normalized == "error":
            return Qt.GlobalColor.darkRed
        return Qt.GlobalColor.black
