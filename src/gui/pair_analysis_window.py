"""Pair analysis window with realtime monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..scanner.ticker_scan import PairExchangeTicker, TickerScanService


@dataclass(frozen=True)
class PairAnalysisSnapshot:
    """Snapshot for a pair analysis refresh."""

    entries: list[PairExchangeTicker]
    best_buy_exchange: str | None
    buy_ask: float | None
    best_sell_exchange: str | None
    sell_bid: float | None
    spread_abs: float | None
    spread_pct: float | None
    errors: list[str]


class PairAnalysisWorker(QObject):
    """Worker to refresh pair analysis data without blocking UI."""

    updated = Signal(PairAnalysisSnapshot)
    stopped = Signal()

    def __init__(self, symbol: str, exchanges: list[str], interval_ms: int) -> None:
        super().__init__()
        self._symbol = symbol
        self._exchanges = list(exchanges)
        self._interval_ms = interval_ms
        self._timer: QTimer | None = None
        self._stopped = False

    def start(self) -> None:
        self._stopped = False
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setInterval(self._interval_ms)
            self._timer.timeout.connect(self._run_scan)
        self._timer.start()
        self._run_scan()

    def stop(self) -> None:
        self._stopped = True
        if self._timer:
            self._timer.stop()
        self.stopped.emit()

    def refresh(self) -> None:
        self._run_scan()

    def _run_scan(self) -> None:
        if self._stopped:
            return
        service = TickerScanService()
        entries, errors = service.fetch_pair_tickers(self._symbol, self._exchanges)
        best_buy_exchange = None
        buy_ask = None
        best_sell_exchange = None
        sell_bid = None
        spread_abs = None
        spread_pct = None
        bids: list[tuple[float, str]] = []
        asks: list[tuple[float, str]] = []
        for entry in entries:
            if entry.bid is not None and entry.bid > 0:
                bids.append((entry.bid, entry.exchange))
            if entry.ask is not None and entry.ask > 0:
                asks.append((entry.ask, entry.exchange))
        if asks:
            buy_ask, best_buy_exchange = min(asks, key=lambda item: item[0])
        if bids:
            sell_bid, best_sell_exchange = max(bids, key=lambda item: item[0])
        if buy_ask is not None and sell_bid is not None:
            spread_abs = sell_bid - buy_ask
            mid = (sell_bid + buy_ask) / 2
            if mid > 0:
                spread_pct = spread_abs / mid * 100
        snapshot = PairAnalysisSnapshot(
            entries=entries,
            best_buy_exchange=best_buy_exchange,
            buy_ask=buy_ask,
            best_sell_exchange=best_sell_exchange,
            sell_bid=sell_bid,
            spread_abs=spread_abs,
            spread_pct=spread_pct,
            errors=errors,
        )
        self.updated.emit(snapshot)


class PairAnalysisWindow(QMainWindow):
    """Window to display per-pair analysis and realtime monitoring."""

    _history_limit = 20

    def __init__(
        self,
        symbol: str,
        exchanges: list[str],
        interval_ms: int = 1000,
    ) -> None:
        super().__init__()
        self._symbol = symbol
        self._exchanges = list(exchanges)
        self._interval_ms = interval_ms
        self._worker_thread: QThread | None = None
        self._worker: PairAnalysisWorker | None = None

        self.setWindowTitle(f"Анализ пары: {symbol}")
        self.resize(1100, 820)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self._build_ui()
        self._start_worker()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(self._build_header())
        layout.addWidget(self._build_parameters_group())
        layout.addWidget(self._build_summary_group())
        layout.addWidget(self._build_exchange_table())
        layout.addWidget(self._build_history_group())
        self.setCentralWidget(central)

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel("Пара:"))
        self._pair_label = QLabel(self._symbol)
        self._pair_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self._pair_label)
        layout.addStretch()
        self._start_button = QPushButton("Старт")
        self._stop_button = QPushButton("Стоп")
        self._refresh_button = QPushButton("Обновить")
        self._close_button = QPushButton("Закрыть")
        self._start_button.clicked.connect(self._start_worker)
        self._stop_button.clicked.connect(self._stop_worker)
        self._refresh_button.clicked.connect(self._refresh_worker)
        self._close_button.clicked.connect(self.close)
        self._stop_button.setEnabled(True)
        layout.addWidget(self._start_button)
        layout.addWidget(self._stop_button)
        layout.addWidget(self._refresh_button)
        layout.addWidget(self._close_button)
        return layout

    def _build_parameters_group(self) -> QGroupBox:
        group = QGroupBox("Параметры расчёта")
        layout = QFormLayout(group)
        self._budget_spin = QDoubleSpinBox()
        self._budget_spin.setRange(1.0, 1_000_000_000.0)
        self._budget_spin.setDecimals(2)
        self._budget_spin.setValue(1000.0)

        self._buy_fee_spin = QDoubleSpinBox()
        self._buy_fee_spin.setRange(0.0, 5.0)
        self._buy_fee_spin.setDecimals(3)
        self._buy_fee_spin.setValue(0.1)

        self._sell_fee_spin = QDoubleSpinBox()
        self._sell_fee_spin.setRange(0.0, 5.0)
        self._sell_fee_spin.setDecimals(3)
        self._sell_fee_spin.setValue(0.1)

        self._slippage_spin = QDoubleSpinBox()
        self._slippage_spin.setRange(0.0, 5.0)
        self._slippage_spin.setDecimals(3)
        self._slippage_spin.setValue(0.05)

        layout.addRow("Бюджет", self._budget_spin)
        layout.addRow("Комиссия покупка %", self._buy_fee_spin)
        layout.addRow("Комиссия продажа %", self._sell_fee_spin)
        layout.addRow("Slippage %", self._slippage_spin)
        return group

    def _build_summary_group(self) -> QGroupBox:
        group = QGroupBox("Итог")
        layout = QFormLayout(group)
        self._best_buy_label = QLabel("—")
        self._best_sell_label = QLabel("—")
        self._gross_spread_label = QLabel("—")
        self._net_spread_label = QLabel("—")
        self._net_profit_label = QLabel("—")
        layout.addRow("Best Buy:", self._best_buy_label)
        layout.addRow("Best Sell:", self._best_sell_label)
        layout.addRow("Gross spread % / $", self._gross_spread_label)
        layout.addRow("Net spread % / $", self._net_spread_label)
        layout.addRow("Net profit $", self._net_profit_label)
        return group

    def _build_exchange_table(self) -> QGroupBox:
        group = QGroupBox("Биржи")
        layout = QVBoxLayout(group)
        self._exchange_table = QTableWidget()
        self._exchange_table.setColumnCount(6)
        self._exchange_table.setHorizontalHeaderLabels(
            ["Биржа", "Bid", "Ask", "Спред %", "Объём 24ч", "Статус"]
        )
        self._exchange_table.setRowCount(len(self._exchanges))
        self._exchange_table.verticalHeader().setVisible(False)
        self._exchange_table.setAlternatingRowColors(True)
        self._exchange_table.horizontalHeader().setStretchLastSection(True)
        self._exchange_table.horizontalHeader().setDefaultSectionSize(140)
        for row, exchange in enumerate(self._exchanges):
            self._exchange_table.setItem(row, 0, QTableWidgetItem(exchange))
        layout.addWidget(self._exchange_table)
        return group

    def _build_history_group(self) -> QGroupBox:
        group = QGroupBox("История (последние 20 строк)")
        layout = QVBoxLayout(group)
        self._history_list = QListWidget()
        layout.addWidget(self._history_list)
        return group

    def _start_worker(self) -> None:
        if self._worker_thread and self._worker and self._worker_thread.isRunning():
            self._worker.start()
            self._start_button.setEnabled(False)
            self._stop_button.setEnabled(True)
            return
        self._worker = PairAnalysisWorker(
            symbol=self._symbol,
            exchanges=self._exchanges,
            interval_ms=self._interval_ms,
        )
        self._worker_thread = QThread(self)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.start)
        self._worker.updated.connect(self._on_snapshot)
        self._worker.stopped.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._on_worker_finished)
        self._worker_thread.start()
        self._start_button.setEnabled(False)
        self._stop_button.setEnabled(True)

    def _stop_worker(self) -> None:
        if self._worker:
            self._worker.stop()
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)

    def _on_worker_finished(self) -> None:
        if self._worker:
            self._worker.deleteLater()
        if self._worker_thread:
            self._worker_thread.deleteLater()
        self._worker = None
        self._worker_thread = None

    def _refresh_worker(self) -> None:
        if self._worker:
            self._worker.refresh()

    def _on_snapshot(self, snapshot: PairAnalysisSnapshot) -> None:
        self._update_table(snapshot.entries)
        self._update_summary(snapshot)

    def _update_table(self, entries: list[PairExchangeTicker]) -> None:
        entry_map = {entry.exchange: entry for entry in entries}
        for row, exchange in enumerate(self._exchanges):
            entry = entry_map.get(exchange)
            if entry is None:
                self._set_table_row(row, exchange, None, None, None, None, "—")
                continue
            spread_pct = None
            if entry.bid and entry.ask and entry.bid > 0 and entry.ask > 0:
                mid = (entry.bid + entry.ask) / 2
                if mid > 0:
                    spread_pct = (entry.ask - entry.bid) / mid * 100
            self._set_table_row(
                row,
                exchange,
                entry.bid,
                entry.ask,
                spread_pct,
                entry.volume_24h,
                entry.status,
            )

    def _set_table_row(
        self,
        row: int,
        exchange: str,
        bid: float | None,
        ask: float | None,
        spread_pct: float | None,
        volume_24h: float | None,
        status: str,
    ) -> None:
        self._exchange_table.setItem(row, 0, QTableWidgetItem(exchange))
        self._exchange_table.setItem(row, 1, QTableWidgetItem(_fmt_value(bid)))
        self._exchange_table.setItem(row, 2, QTableWidgetItem(_fmt_value(ask)))
        self._exchange_table.setItem(row, 3, QTableWidgetItem(_fmt_pct(spread_pct)))
        self._exchange_table.setItem(row, 4, QTableWidgetItem(_fmt_value(volume_24h)))
        self._exchange_table.setItem(row, 5, QTableWidgetItem(status))

    def _update_summary(self, snapshot: PairAnalysisSnapshot) -> None:
        self._best_buy_label.setText(_fmt_best(snapshot.best_buy_exchange, snapshot.buy_ask))
        self._best_sell_label.setText(
            _fmt_best(snapshot.best_sell_exchange, snapshot.sell_bid)
        )
        gross_pct = snapshot.spread_pct
        gross_abs = None
        if snapshot.buy_ask and snapshot.sell_bid:
            gross_abs = (snapshot.sell_bid / snapshot.buy_ask - 1) * self._budget_spin.value()
        self._gross_spread_label.setText(_fmt_pct_value(gross_pct, gross_abs))
        net_profit, net_spread_pct = self._calculate_net(snapshot)
        self._net_spread_label.setText(_fmt_pct_value(net_spread_pct, net_profit))
        self._net_profit_label.setText(_fmt_value(net_profit))
        self._append_history(snapshot, net_profit, net_spread_pct)

    def _calculate_net(
        self, snapshot: PairAnalysisSnapshot
    ) -> tuple[float | None, float | None]:
        if snapshot.buy_ask is None or snapshot.sell_bid is None:
            return None, None
        budget = self._budget_spin.value()
        buy_fee = self._buy_fee_spin.value() / 100
        sell_fee = self._sell_fee_spin.value() / 100
        slippage = self._slippage_spin.value() / 100
        buy_cost = budget * (1 + buy_fee + slippage)
        sell_gain = budget * (1 - sell_fee - slippage)
        if buy_cost <= 0:
            return None, None
        net_profit = (snapshot.sell_bid / snapshot.buy_ask) * sell_gain - buy_cost
        net_spread_pct = net_profit / buy_cost * 100
        return net_profit, net_spread_pct

    def _append_history(
        self,
        snapshot: PairAnalysisSnapshot,
        net_profit: float | None,
        net_spread_pct: float | None,
    ) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        buy_text = _fmt_best(snapshot.best_buy_exchange, snapshot.buy_ask)
        sell_text = _fmt_best(snapshot.best_sell_exchange, snapshot.sell_bid)
        net_pct_text = _fmt_pct(net_spread_pct)
        net_profit_text = _fmt_value(net_profit)
        line = (
            f"{timestamp} | buy@ {buy_text} | sell@ {sell_text} | "
            f"net {net_pct_text} | net$ {net_profit_text}"
        )
        self._add_history_line(line)

    def _add_history_line(self, line: str) -> None:
        self._history_list.insertItem(0, line)
        while self._history_list.count() > self._history_limit:
            self._history_list.takeItem(self._history_list.count() - 1)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._stop_worker()
        super().closeEvent(event)


def _fmt_value(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}%"


def _fmt_pct_value(pct: float | None, value: float | None) -> str:
    if pct is None and value is None:
        return "—"
    pct_text = _fmt_pct(pct)
    value_text = _fmt_value(value)
    return f"{pct_text} / {value_text}"


def _fmt_best(exchange: str | None, price: float | None) -> str:
    if exchange is None or price is None:
        return "—"
    return f"{exchange} @ {price:,.6f}".rstrip("0").rstrip(".")
