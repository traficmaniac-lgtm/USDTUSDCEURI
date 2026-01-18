"""Pair analysis window with realtime monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import time

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QProgressBar,
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
    scan_started = Signal()
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

    def pause(self) -> None:
        if self._timer:
            self._timer.stop()

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
        self.scan_started.emit()
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
        opportunity_threshold: float,
        interval_ms: int = 1000,
    ) -> None:
        super().__init__()
        self._symbol = symbol
        self._exchanges = list(exchanges)
        self._opportunity_threshold = opportunity_threshold
        self._interval_ms = interval_ms
        self._worker_thread: QThread | None = None
        self._worker: PairAnalysisWorker | None = None
        self._bad_updates_streak = 0
        self._analysis_status = "ПАУЗА"
        self._slow_update = False
        self._refresh_started_ts: float | None = None

        self.setWindowTitle(f"Анализ пары: {symbol}")
        self.resize(1100, 820)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self._build_ui()
        self._set_analysis_status("ПАУЗА")

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
        self._status_title = QLabel("Статус:")
        self._status_label = QLabel("ПАУЗА")
        self._status_label.setStyleSheet("font-weight: 600; color: #666666;")
        layout.addSpacing(16)
        layout.addWidget(self._status_title)
        layout.addWidget(self._status_label)
        layout.addSpacing(16)
        self._refresh_progress = QProgressBar()
        self._refresh_progress.setRange(0, 0)
        self._refresh_progress.setMaximumWidth(120)
        self._refresh_progress.setVisible(False)
        self._last_update_title = QLabel("Последнее обновление:")
        self._last_update_label = QLabel("—")
        self._latency_title = QLabel("Задержка:")
        self._latency_label = QLabel("—")
        layout.addWidget(self._refresh_progress)
        layout.addWidget(self._last_update_title)
        layout.addWidget(self._last_update_label)
        layout.addSpacing(8)
        layout.addWidget(self._latency_title)
        layout.addWidget(self._latency_label)
        layout.addStretch()
        self._start_button = QPushButton("Старт")
        self._stop_button = QPushButton("Стоп")
        self._refresh_button = QPushButton("Обновить")
        self._close_button = QPushButton("Закрыть")
        self._start_button.clicked.connect(self._start_worker)
        self._stop_button.clicked.connect(self._pause_worker)
        self._refresh_button.clicked.connect(self._refresh_worker)
        self._close_button.clicked.connect(self.close)
        self._stop_button.setEnabled(False)
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
        self._exchange_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._exchange_table.customContextMenuRequested.connect(
            self._show_exchange_context_menu
        )
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
            self._bad_updates_streak = 0
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
        self._worker.scan_started.connect(self._on_scan_started)
        self._worker.stopped.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._on_worker_finished)
        self._worker_thread.start()
        self._start_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._bad_updates_streak = 0

    def _pause_worker(self) -> None:
        if self._worker:
            self._worker.pause()
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._set_analysis_status("ПАУЗА")

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
        else:
            self._start_worker()
            if self._worker:
                self._worker.pause()

    def _on_snapshot(self, snapshot: PairAnalysisSnapshot) -> None:
        self._finalize_refresh()
        if not self._has_valid_data(snapshot):
            self._bad_updates_streak += 1
            self._set_analysis_status("ОШИБКА")
            self._append_error_history()
            if self._bad_updates_streak >= 5:
                self._auto_pause_for_bad_data()
            return
        self._bad_updates_streak = 0
        self._update_table(
            snapshot.entries, snapshot.best_buy_exchange, snapshot.best_sell_exchange
        )
        self._update_summary(snapshot)
        self._update_status_from_spread(snapshot.spread_pct)
        self._append_history(snapshot)

    def _on_scan_started(self) -> None:
        self._refresh_started_ts = time.monotonic()
        self._refresh_progress.setVisible(True)

    def _finalize_refresh(self) -> None:
        now = time.monotonic()
        latency_ms = None
        if self._refresh_started_ts is not None:
            latency_ms = (now - self._refresh_started_ts) * 1000
        self._refresh_progress.setVisible(False)
        self._last_update_label.setText(datetime.now().strftime("%H:%M:%S"))
        if latency_ms is None:
            self._latency_label.setText("—")
            self._slow_update = False
        else:
            self._latency_label.setText(f"{latency_ms:.0f} ms")
            self._slow_update = latency_ms > 4000

    def _update_table(
        self,
        entries: list[PairExchangeTicker],
        best_buy_exchange: str | None,
        best_sell_exchange: str | None,
    ) -> None:
        entry_map = {entry.exchange: entry for entry in entries}
        for row, exchange in enumerate(self._exchanges):
            background = None
            if exchange == best_buy_exchange:
                background = QColor(220, 245, 224)
            elif exchange == best_sell_exchange:
                background = QColor(227, 241, 255)
            entry = entry_map.get(exchange)
            if entry is None:
                self._set_table_row(row, exchange, None, None, None, None, "—", background)
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
                background,
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
        background: QColor | None,
    ) -> None:
        items = [
            QTableWidgetItem(exchange),
            QTableWidgetItem(_fmt_value(bid)),
            QTableWidgetItem(_fmt_value(ask)),
            QTableWidgetItem(_fmt_pct(spread_pct)),
            QTableWidgetItem(_fmt_value(volume_24h)),
            QTableWidgetItem(status),
        ]
        for column, item in enumerate(items):
            if background is not None:
                item.setBackground(background)
            self._exchange_table.setItem(row, column, item)

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
        self._style_net_profit_label(net_profit)

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

    def _append_history(self, snapshot: PairAnalysisSnapshot) -> None:
        net_profit, net_spread_pct = self._calculate_net(snapshot)
        timestamp = datetime.now().strftime("%H:%M:%S")
        buy_text = _fmt_exchange_price(snapshot.best_buy_exchange, snapshot.buy_ask)
        sell_text = _fmt_exchange_price(snapshot.best_sell_exchange, snapshot.sell_bid)
        gross_text = _fmt_pct(snapshot.spread_pct)
        net_pct_text = _fmt_pct(net_spread_pct)
        net_profit_text = _fmt_value(net_profit)
        line = (
            f"{timestamp} | BUY {buy_text} | SELL {sell_text} | "
            f"gross {gross_text} | net {net_pct_text} | net$ {net_profit_text}"
        )
        self._add_history_line(line)

    def _add_history_line(self, line: str) -> None:
        self._history_list.insertItem(0, line)
        while self._history_list.count() > self._history_limit:
            self._history_list.takeItem(self._history_list.count() - 1)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._stop_worker()
        super().closeEvent(event)

    def _set_analysis_status(self, status: str) -> None:
        self._analysis_status = status
        color = "#666666"
        if status == "LIVE":
            color = "#1b7f2a"
        elif status == "УГАСЛО":
            color = "#7a7a7a"
        elif status == "ОШИБКА":
            color = "#b00020"
        elif status == "ПАУЗА":
            color = "#666666"
        status_text = status
        if self._slow_update:
            status_text = f"{status} · Долго… (возможен rate-limit)"
        self._status_label.setText(status_text)
        self._status_label.setStyleSheet(f"font-weight: 600; color: {color};")

    def _update_status_from_spread(self, spread_pct: float | None) -> None:
        if spread_pct is None:
            self._set_analysis_status("ОШИБКА")
            return
        if spread_pct >= self._opportunity_threshold:
            self._set_analysis_status("LIVE")
        else:
            self._set_analysis_status("УГАСЛО")

    def _has_valid_data(self, snapshot: PairAnalysisSnapshot) -> bool:
        valid_exchanges = sum(
            1
            for entry in snapshot.entries
            if entry.bid is not None
            and entry.ask is not None
            and entry.bid > 0
            and entry.ask > 0
        )
        if valid_exchanges < 2:
            return False
        if snapshot.buy_ask is None or snapshot.sell_bid is None:
            return False
        return True

    def _append_error_history(self) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._add_history_line(f"{timestamp} | ОШИБКА: недостаточно данных")

    def _auto_pause_for_bad_data(self) -> None:
        self._pause_worker()
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._add_history_line(
            f"{timestamp} | Авто-пауза: нет валидных данных 5 обновлений"
        )

    def _style_net_profit_label(self, net_profit: float | None) -> None:
        if net_profit is None:
            self._net_profit_label.setStyleSheet("color: #666666;")
            return
        if net_profit > 0:
            self._net_profit_label.setStyleSheet("font-weight: 600; color: #1b7f2a;")
        elif net_profit < 0:
            self._net_profit_label.setStyleSheet("color: #b00020;")
        else:
            self._net_profit_label.setStyleSheet("color: #666666;")

    def _show_exchange_context_menu(self, position) -> None:
        index = self._exchange_table.indexAt(position)
        if not index.isValid():
            return
        row = index.row()
        menu = QMenu(self)
        copy_action = QAction("Копировать строку", self)
        copy_action.triggered.connect(lambda: self._copy_exchange_row(row))
        menu.addAction(copy_action)
        menu.exec(self._exchange_table.viewport().mapToGlobal(position))

    def _copy_exchange_row(self, row: int) -> None:
        exchange_item = self._exchange_table.item(row, 0)
        bid_item = self._exchange_table.item(row, 1)
        ask_item = self._exchange_table.item(row, 2)
        exchange = exchange_item.text() if exchange_item else "—"
        bid = bid_item.text() if bid_item else "—"
        ask = ask_item.text() if ask_item else "—"
        text = f"{exchange} | bid: {bid} | ask: {ask}"
        QGuiApplication.clipboard().setText(text)


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


def _fmt_exchange_price(exchange: str | None, price: float | None) -> str:
    if exchange is None or price is None:
        return "—"
    price_text = f"{price:,.6f}".rstrip("0").rstrip(".")
    return f"{exchange}@{price_text}"
