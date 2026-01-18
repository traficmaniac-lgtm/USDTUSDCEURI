"""Scanner mode window (UI scaffold only)."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QObject, Qt, QThread, Signal
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
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .models.scanner_table_model import ScannerRow, ScannerTableModel
from ..scanner.market_discovery import MarketDiscoveryResult, MarketDiscoveryService


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
        self.setWindowTitle("Scanner Mode")
        self.resize(1200, 820)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self._rows: list[ScannerRow] = []
        self._scanning = False
        self._last_updated = "—"
        self._discovery_thread: QThread | None = None
        self._discovery_worker: MarketDiscoveryWorker | None = None
        self._discovery_request_id = 0

        self._build_ui()
        self._log("Scanner window opened")
        self._update_status()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self._build_settings_panel())
        layout.addLayout(self._build_controls())
        layout.addWidget(self._build_table())
        layout.addLayout(self._build_status_log())
        self.setCentralWidget(central)
        self._create_actions()

    def _create_actions(self) -> None:
        close_action = QAction("Close", self)
        close_action.triggered.connect(self.close)
        self.addAction(close_action)

    def _build_settings_panel(self) -> QGroupBox:
        group = QGroupBox("Settings")
        outer_layout = QVBoxLayout(group)

        grid_layout = QVBoxLayout()

        quote_layout = QHBoxLayout()
        quote_layout.addWidget(QLabel("Quote currencies:"))
        self._quote_usdt = QCheckBox("USDT")
        self._quote_usdc = QCheckBox("USDC")
        self._quote_usdt.setChecked(True)
        self._quote_usdc.setChecked(True)
        quote_layout.addWidget(self._quote_usdt)
        quote_layout.addWidget(self._quote_usdc)
        quote_layout.addStretch()
        grid_layout.addLayout(quote_layout)

        self._min_exchanges_spin = self._make_spinbox(1, 50, 5)
        grid_layout.addLayout(self._labeled_row("Min exchanges per pair:", self._min_exchanges_spin))

        self._min_volume_spin = self._make_double_spinbox(0, 10_000_000, 200_000, decimals=0)
        grid_layout.addLayout(self._labeled_row("Min 24h volume ($):", self._min_volume_spin))

        self._max_spread_spin = self._make_double_spinbox(0.0, 100.0, 1.0, decimals=2)
        grid_layout.addLayout(self._labeled_row("Max intrabook spread %:", self._max_spread_spin))

        self._opportunity_threshold_spin = self._make_double_spinbox(0.0, 100.0, 0.15, decimals=2)
        grid_layout.addLayout(self._labeled_row("Opportunity threshold %:", self._opportunity_threshold_spin))

        self._persistence_spin = self._make_spinbox(1, 10, 3)
        grid_layout.addLayout(self._labeled_row("Persistence K:", self._persistence_spin))

        self._max_pairs_spin = self._make_spinbox(10, 10_000, 300)
        grid_layout.addLayout(self._labeled_row("Max pairs to scan:", self._max_pairs_spin))

        self._scan_interval_spin = self._make_spinbox(250, 10_000, 2000)
        self._scan_interval_spin.setSuffix(" ms")
        grid_layout.addLayout(self._labeled_row("Scan interval (ms):", self._scan_interval_spin))

        outer_layout.addLayout(grid_layout)
        outer_layout.addWidget(self._build_exchanges_group())
        return group

    def _build_exchanges_group(self) -> QGroupBox:
        group = QGroupBox("Exchanges")
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
        self._start_button = QPushButton("Start Scan")
        self._stop_button = QPushButton("Stop")
        self._clear_button = QPushButton("Clear")
        self._watchlist_button = QPushButton("Add to Watchlist")

        self._start_button.clicked.connect(self._start_scan)
        self._stop_button.clicked.connect(self._stop_scan)
        self._clear_button.clicked.connect(self._clear_scan)
        self._watchlist_button.clicked.connect(self._add_to_watchlist)

        self._stop_button.setEnabled(False)

        layout.addWidget(self._start_button)
        layout.addWidget(self._stop_button)
        layout.addWidget(self._clear_button)
        layout.addWidget(self._watchlist_button)
        layout.addStretch()
        return layout

    def _build_table(self) -> QTableView:
        self._table_model = ScannerTableModel()
        self._table_view = QTableView()
        self._proxy_model = self._create_proxy_model(self._table_model)
        self._table_view.setModel(self._proxy_model)
        self._table_view.setSortingEnabled(True)
        self._table_view.setAlternatingRowColors(True)
        self._table_view.horizontalHeader().setStretchLastSection(True)
        self._table_view.horizontalHeader().setDefaultSectionSize(130)
        self._table_view.setSelectionBehavior(QTableView.SelectRows)
        self._table_view.setSelectionMode(QTableView.ExtendedSelection)
        return self._table_view

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
        self._rows = []
        self._table_model.set_rows([])
        self._scanning = True
        self._start_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._log("Start Scan clicked")
        self._log(f"Loading markets for {len(selected_exchanges)} exchanges...")
        self._update_status()
        self._start_market_discovery(selected_exchanges, quotes, min_exchanges)

    def _stop_scan(self) -> None:
        if not self._scanning:
            return
        self._cancel_market_discovery()
        self._scanning = False
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._log("Stop clicked")
        self._update_status()

    def _clear_scan(self) -> None:
        self._cancel_market_discovery()
        self._rows = []
        self._table_model.set_rows([])
        self._scanning = False
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._last_updated = "—"
        self._log("Clear clicked")
        self._update_status()

    def _add_to_watchlist(self) -> None:
        selection = self._table_view.selectionModel()
        rows = selection.selectedRows() if selection else []
        pairs: list[str] = []
        for proxy_index in rows:
            source_index = self._proxy_model.mapToSource(proxy_index)
            if 0 <= source_index.row() < len(self._rows):
                pairs.append(self._rows[source_index.row()].pair)
        self._log(f"Add to Watchlist clicked: {len(rows)} rows")
        if pairs:
            self._log(f"Selected pairs: {', '.join(pairs)}")

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
            self._log(f"Markets loaded: {exchange}={count}")
        min_exchanges = self._min_exchanges_spin.value()
        self._log(f"Eligible pairs: {len(result.eligible_pairs)} (min exchanges={min_exchanges})")
        self._rows = [
            ScannerRow(
                pair=pair,
                best_buy_exchange=None,
                buy_ask=None,
                best_sell_exchange=None,
                sell_bid=None,
                spread_abs=None,
                spread_pct=None,
                volume_24h=None,
                stable_hits=None,
                score=None,
                status=f"eligible ({len(result.pair_exchanges.get(pair, []))})",
            )
            for pair in result.eligible_pairs
        ]
        self._table_model.set_rows(self._rows)
        self._scanning = False
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._last_updated = datetime.now().strftime("%H:%M:%S")
        self._update_status()

    def _on_discovery_failed(self, request_id: int, message: str) -> None:
        if request_id != self._discovery_request_id:
            return
        self._log(f"Market discovery error: {message}")
        self._scanning = False
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._update_status()

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_view.appendPlainText(f"[{timestamp}] {message}")

    def _update_status(self) -> None:
        scanning_state = "ON" if self._scanning else "OFF"
        candidates = len(self._rows)
        self._status_label.setText(
            f"Scanning: {scanning_state} | Candidates: {candidates} | Updated: {self._last_updated}"
        )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._cancel_market_discovery()
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
