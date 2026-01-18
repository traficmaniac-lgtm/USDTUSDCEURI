"""Scanner mode window (UI scaffold only)."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Qt, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .models.scanner_table_model import ScannerRow, ScannerTableModel
from ..scanner.market_discovery import MarketDiscoveryResult, MarketDiscoveryService
from ..scanner.ticker_scan import TickerScanResult, TickerScanService


class ScannerWindow(QMainWindow):
    """Standalone window for the scanner mode UI."""

    _exchange_names = [
        "Binance",
        "OKX",
        "Bybit",
        "Gate.io",
        "KuCoin",
        "Kraken",
        "Coinbase",
        "Bitfinex",
        "Bitget",
        "HTX",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Сканер рынка")
        self.resize(1200, 820)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self._eligible_pairs: list[str] = []
        self._profit_rows: list[ScannerRow] = []
        self._scanning = False
        self._last_updated = "—"
        self._discovery_thread: QThread | None = None
        self._discovery_worker: MarketDiscoveryWorker | None = None
        self._discovery_request_id = 0
        self._ticker_thread: QThread | None = None
        self._ticker_worker: TickerScanWorker | None = None
        self._pair_exchanges: dict[str, list[str]] = {}
        self._selected_exchanges_count = 0

        self._build_ui()
        self._log("Окно сканера открыто")
        self._update_status()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self._build_settings_panel())
        layout.addLayout(self._build_controls())
        layout.addWidget(self._build_profit_panel())
        layout.addLayout(self._build_status_log())
        self.setCentralWidget(central)
        self._create_actions()

    def _create_actions(self) -> None:
        close_action = QAction("Закрыть", self)
        close_action.triggered.connect(self.close)
        self.addAction(close_action)

    def _build_settings_panel(self) -> QGroupBox:
        group = QGroupBox("Настройки")
        outer_layout = QVBoxLayout(group)

        grid_layout = QVBoxLayout()

        quote_layout = QHBoxLayout()
        quote_layout.addWidget(QLabel("Котируемые валюты:"))
        self._quote_usdt = QCheckBox("USDT")
        self._quote_usdc = QCheckBox("USDC")
        self._quote_usdt.setChecked(True)
        self._quote_usdc.setChecked(True)
        quote_layout.addWidget(self._quote_usdt)
        quote_layout.addWidget(self._quote_usdc)
        quote_layout.addStretch()
        grid_layout.addLayout(quote_layout)

        self._min_exchanges_spin = self._make_spinbox(1, 50, 5)
        grid_layout.addLayout(self._labeled_row("Мин. бирж на пару:", self._min_exchanges_spin))

        self._min_volume_spin = self._make_double_spinbox(0, 10_000_000, 200_000, decimals=0)
        grid_layout.addLayout(self._labeled_row("Мин. 24ч объём ($):", self._min_volume_spin))

        self._max_spread_spin = self._make_double_spinbox(0.0, 100.0, 1.0, decimals=2)
        grid_layout.addLayout(self._labeled_row("Макс. спред %:", self._max_spread_spin))

        self._opportunity_threshold_spin = self._make_double_spinbox(0.0, 100.0, 0.15, decimals=2)
        grid_layout.addLayout(self._labeled_row("Порог возможности %:", self._opportunity_threshold_spin))

        self._persistence_spin = self._make_spinbox(1, 10, 3)
        grid_layout.addLayout(self._labeled_row("Устойчивость K:", self._persistence_spin))

        self._max_pairs_spin = self._make_spinbox(10, 10_000, 300)
        grid_layout.addLayout(self._labeled_row("Макс. пар для скана:", self._max_pairs_spin))

        self._scan_interval_spin = self._make_spinbox(250, 10_000, 2000)
        self._scan_interval_spin.setSuffix(" мс")
        grid_layout.addLayout(self._labeled_row("Интервал скана (мс):", self._scan_interval_spin))

        outer_layout.addLayout(grid_layout)
        outer_layout.addWidget(self._build_exchanges_group())
        return group

    def _build_exchanges_group(self) -> QGroupBox:
        group = QGroupBox("Биржи")
        layout = QVBoxLayout(group)
        self._exchanges_list = QListWidget()
        for name in self._exchange_names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self._exchanges_list.addItem(item)
        layout.addWidget(self._exchanges_list)
        return group

    def _build_controls(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self._start_button = QPushButton("Старт")
        self._stop_button = QPushButton("Стоп")
        self._clear_button = QPushButton("Очистить")

        self._start_button.clicked.connect(self._start_scan)
        self._stop_button.clicked.connect(self._stop_scan)
        self._clear_button.clicked.connect(self._clear_scan)

        self._stop_button.setEnabled(False)

        layout.addWidget(self._start_button)
        layout.addWidget(self._stop_button)
        layout.addWidget(self._clear_button)
        layout.addStretch()
        return layout

    def _build_profit_panel(self) -> QGroupBox:
        group = QGroupBox("Профитные")
        layout = QVBoxLayout(group)
        self._profit_table_model = ScannerTableModel()
        self._profit_table_view = QTableView()
        self._profit_proxy_model = self._create_proxy_model(self._profit_table_model)
        self._profit_table_view.setModel(self._profit_proxy_model)
        self._profit_table_view.setSortingEnabled(True)
        self._profit_table_view.setAlternatingRowColors(True)
        self._profit_table_view.horizontalHeader().setStretchLastSection(True)
        self._profit_table_view.horizontalHeader().setDefaultSectionSize(130)
        self._profit_table_view.setSelectionBehavior(QTableView.SelectRows)
        self._profit_table_view.setSelectionMode(QTableView.ExtendedSelection)
        self._profit_table_view.doubleClicked.connect(self._open_analysis)
        layout.addWidget(self._profit_table_view)
        return group

    def _build_status_log(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        self._status_label = QLabel()
        layout.addWidget(self._status_label)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(500)
        layout.addWidget(self._log_view)
        return layout

    def _make_spinbox(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def _make_double_spinbox(
        self,
        minimum: float,
        maximum: float,
        value: float,
        decimals: int = 2,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(value)
        return spin

    def _labeled_row(self, text: str, widget: QWidget) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel(text))
        layout.addWidget(widget)
        layout.addStretch()
        return layout

    def _create_proxy_model(self, model: ScannerTableModel):
        from PySide6.QtCore import QSortFilterProxyModel

        proxy = QSortFilterProxyModel(self)
        proxy.setSourceModel(model)
        proxy.setSortCaseSensitivity(Qt.CaseInsensitive)
        proxy.setDynamicSortFilter(True)
        return proxy

    def _selected_quote_currencies(self) -> list[str]:
        currencies: list[str] = []
        if self._quote_usdt.isChecked():
            currencies.append("USDT")
        if self._quote_usdc.isChecked():
            currencies.append("USDC")
        return currencies or ["USDT"]

    def _selected_exchanges(self) -> list[str]:
        selected: list[str] = []
        for row in range(self._exchanges_list.count()):
            item = self._exchanges_list.item(row)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        return selected or [self._exchange_names[0]]

    def _start_scan(self) -> None:
        if self._scanning:
            return
        selected_exchanges = self._selected_exchanges()
        quotes = self._selected_quote_currencies()
        min_exchanges = self._min_exchanges_spin.value()
        self._selected_exchanges_count = len(selected_exchanges)
        self._eligible_pairs = []
        self._pair_exchanges = {}
        self._profit_rows = []
        self._profit_table_model.set_rows([])
        self._scanning = True
        self._start_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._log("Сканирование запущено")
        self._log(f"Загружаем рынки: биржи={len(selected_exchanges)}")
        self._update_status()
        self._start_market_discovery(selected_exchanges, quotes, min_exchanges)

    def _stop_scan(self) -> None:
        if not self._scanning:
            return
        self._cancel_market_discovery()
        self._stop_ticker_scan()
        self._scanning = False
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._log("Сканирование остановлено")
        self._update_status()

    def _clear_scan(self) -> None:
        self._cancel_market_discovery()
        self._stop_ticker_scan()
        self._eligible_pairs = []
        self._pair_exchanges = {}
        self._profit_rows = []
        self._profit_table_model.set_rows([])
        self._scanning = False
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._last_updated = "—"
        self._log("Данные очищены")
        self._update_status()

    def _open_analysis(self, index=None) -> None:
        if index is None:
            selection = self._profit_table_view.selectionModel()
            rows = selection.selectedRows() if selection else []
            if not rows:
                return
            proxy_index = rows[0]
        else:
            proxy_index = index
        source_index = self._profit_proxy_model.mapToSource(proxy_index)
        if not (0 <= source_index.row() < len(self._profit_rows)):
            return
        pair = self._profit_rows[source_index.row()].pair
        self._log(f"Открыть анализ: {pair}")
        QMessageBox.information(
            self,
            "Анализ пары",
            "Окно анализа будет добавлено на следующем этапе",
        )

    def _start_market_discovery(
        self,
        exchanges: list[str],
        quotes: list[str],
        min_exchanges: int,
    ) -> None:
        self._discovery_request_id += 1
        request_id = self._discovery_request_id
        self._discovery_worker = MarketDiscoveryWorker(
            request_id=request_id,
            exchanges=exchanges,
            quotes=quotes,
            min_exchanges=min_exchanges,
        )
        self._discovery_thread = QThread(self)
        self._discovery_worker.moveToThread(self._discovery_thread)
        self._discovery_thread.started.connect(self._discovery_worker.run)
        self._discovery_worker.log.connect(self._log)
        self._discovery_worker.finished.connect(self._on_discovery_finished)
        self._discovery_worker.failed.connect(self._on_discovery_failed)
        self._discovery_worker.finished.connect(self._discovery_thread.quit)
        self._discovery_worker.failed.connect(self._discovery_thread.quit)
        self._discovery_thread.finished.connect(self._discovery_worker.deleteLater)
        self._discovery_thread.finished.connect(self._discovery_thread.deleteLater)
        self._discovery_thread.start()

    def _cancel_market_discovery(self) -> None:
        if self._discovery_worker:
            self._discovery_worker.cancel()
        self._discovery_request_id += 1

    def _on_discovery_finished(self, request_id: int, result: MarketDiscoveryResult) -> None:
        if request_id != self._discovery_request_id:
            return
        for exchange, count in result.exchange_counts.items():
            self._log(f"Рынки загружены: {exchange}={count}")
        min_exchanges = self._min_exchanges_spin.value()
        self._log(
            f"Кандидаты: {len(result.eligible_pairs)} (мин. бирж={min_exchanges})"
        )
        self._pair_exchanges = result.pair_exchanges
        self._eligible_pairs = list(result.eligible_pairs)
        self._profit_rows = []
        self._profit_table_model.set_rows([])
        if self._scanning:
            min_exchanges = self._min_exchanges_spin.value()
            if not self._eligible_pairs:
                self._log("Скан цен не запущен: нет eligible пар")
            elif self._selected_exchanges_count < min_exchanges:
                self._log(
                    "Скан цен не запущен: выберите больше бирж "
                    f"(нужно >= {min_exchanges})"
                )
            else:
                self._start_ticker_scan()
        self._last_updated = datetime.now().strftime("%H:%M:%S")
        self._update_status()

    def _on_discovery_failed(self, request_id: int, message: str) -> None:
        if request_id != self._discovery_request_id:
            return
        self._log(f"Ошибка поиска рынков: {message}")
        self._stop_ticker_scan()
        self._scanning = False
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._update_status()

    def _start_ticker_scan(self) -> None:
        self._stop_ticker_scan()
        interval_ms = self._scan_interval_spin.value()
        max_pairs = self._max_pairs_spin.value()
        self._ticker_worker = TickerScanWorker(
            pair_exchanges=self._pair_exchanges,
            eligible_pairs=self._eligible_pairs,
            max_pairs=max_pairs,
            interval_ms=interval_ms,
        )
        self._ticker_thread = QThread(self)
        self._ticker_worker.moveToThread(self._ticker_thread)
        self._ticker_thread.started.connect(self._ticker_worker.start)
        self._ticker_worker.log.connect(self._log)
        self._ticker_worker.updated.connect(self._on_ticker_updated)
        self._ticker_worker.stopped.connect(self._ticker_thread.quit)
        self._ticker_thread.finished.connect(self._ticker_worker.deleteLater)
        self._ticker_thread.finished.connect(self._ticker_thread.deleteLater)
        self._ticker_thread.start()
        pairs_count = min(max_pairs, len(self._eligible_pairs))
        self._log(
            "Скан цен запущен: "
            f"pairs={pairs_count} exchanges={self._selected_exchanges_count}"
        )

    def _stop_ticker_scan(self) -> None:
        if self._ticker_worker:
            self._ticker_worker.stop()
        self._ticker_thread = None
        self._ticker_worker = None

    def _on_ticker_updated(self, result: TickerScanResult) -> None:
        if not self._scanning:
            return
        threshold = self._opportunity_threshold_spin.value()
        row_map = {row.pair: row for row in self._profit_rows}
        for update in result.updates:
            spread_pct = update.spread_pct
            if spread_pct is not None and spread_pct >= threshold:
                row = row_map.get(update.pair)
                if row is None:
                    row = ScannerRow(
                        pair=update.pair,
                        best_buy_exchange=update.best_buy_exchange,
                        buy_ask=update.buy_ask,
                        best_sell_exchange=update.best_sell_exchange,
                        sell_bid=update.sell_bid,
                        spread_abs=update.spread_abs,
                        spread_pct=update.spread_pct,
                        volume_24h=update.volume_24h,
                        stable_hits=None,
                        score=None,
                        status="LIVE",
                    )
                    self._profit_rows.append(row)
                    row_map[update.pair] = row
                else:
                    row.best_buy_exchange = update.best_buy_exchange
                    row.buy_ask = update.buy_ask
                    row.best_sell_exchange = update.best_sell_exchange
                    row.sell_bid = update.sell_bid
                    row.spread_abs = update.spread_abs
                    row.spread_pct = update.spread_pct
                    row.volume_24h = update.volume_24h
                    row.status = "LIVE"
            else:
                row = row_map.get(update.pair)
                if row:
                    row.best_buy_exchange = update.best_buy_exchange
                    row.buy_ask = update.buy_ask
                    row.best_sell_exchange = update.best_sell_exchange
                    row.sell_bid = update.sell_bid
                    row.spread_abs = update.spread_abs
                    row.spread_pct = update.spread_pct
                    row.volume_24h = update.volume_24h
                    row.status = "УГАСЛО"
        self._profit_table_model.set_rows(self._profit_rows)
        self._last_updated = datetime.now().strftime("%H:%M:%S")
        self._update_status()
        self._log(
            "Обновление: "
            f"ok={result.ok_count} fail={result.fail_count}"
        )

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_view.appendPlainText(f"[{timestamp}] {message}")

    def _update_status(self) -> None:
        scanning_state = "ВКЛ" if self._scanning else "ВЫКЛ"
        eligible = len(self._eligible_pairs)
        profit_count = len(self._profit_rows)
        self._status_label.setText(
            "Сканирование: "
            f"{scanning_state} | Eligible: {eligible} | "
            f"Профитные: {profit_count} | Обновлено: {self._last_updated}"
        )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._cancel_market_discovery()
        self._stop_ticker_scan()
        self._scanning = False
        self._update_status()
        super().closeEvent(event)


class MarketDiscoveryWorker(QObject):
    """Background worker for market discovery."""

    finished = Signal(int, MarketDiscoveryResult)
    failed = Signal(int, str)
    log = Signal(str)

    def __init__(
        self,
        request_id: int,
        exchanges: list[str],
        quotes: list[str],
        min_exchanges: int,
    ) -> None:
        super().__init__()
        self._request_id = request_id
        self._exchanges = exchanges
        self._quotes = quotes
        self._min_exchanges = min_exchanges
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            service = MarketDiscoveryService()
            result = service.discover(
                self._exchanges,
                self._quotes,
                self._min_exchanges,
                should_cancel=self._is_cancelled,
            )
        except Exception as exc:  # noqa: BLE001 - surface discovery errors in UI
            self.failed.emit(self._request_id, str(exc))
            return
        if self._cancelled:
            return
        self.finished.emit(self._request_id, result)

    def _is_cancelled(self) -> bool:
        return self._cancelled


class TickerScanWorker(QObject):
    """Background worker for ticker scanning."""

    updated = Signal(TickerScanResult)
    log = Signal(str)
    stopped = Signal()

    def __init__(
        self,
        pair_exchanges: dict[str, list[str]],
        eligible_pairs: list[str],
        max_pairs: int,
        interval_ms: int,
    ) -> None:
        super().__init__()
        self._pair_exchanges = pair_exchanges
        self._eligible_pairs = eligible_pairs
        self._max_pairs = max_pairs
        self._interval_ms = interval_ms
        self._timer: QTimer | None = None
        self._stopped = False

    def start(self) -> None:
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

    def _run_scan(self) -> None:
        if self._stopped:
            return
        try:
            service = TickerScanService()
            result = service.scan(
                self._pair_exchanges,
                self._max_pairs,
                pairs=self._eligible_pairs,
            )
        except Exception as exc:  # noqa: BLE001 - surface scan errors
            self.log.emit(f"Ошибка сканирования тикеров: {exc}")
            return
        for error in result.errors:
            self.log.emit(error)
        self.updated.emit(result)
