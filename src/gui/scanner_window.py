"""Scanner mode window (UI scaffold only)."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
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

    _base_assets = [
        "BTC",
        "ETH",
        "SOL",
        "XRP",
        "ADA",
        "DOGE",
        "TRX",
        "DOT",
        "AVAX",
        "MATIC",
        "TON",
        "ATOM",
        "LTC",
        "BCH",
        "LINK",
        "ETC",
        "NEAR",
        "APT",
        "ARB",
        "OP",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Scanner Mode")
        self.resize(1200, 820)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_fake_rows)
        self._rows: list[ScannerRow] = []
        self._scanning = False
        self._last_updated = "—"

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
        self._scan_interval_spin.valueChanged.connect(self._update_timer_interval)
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
        if self._timer.isActive():
            return
        self._rows = self._generate_fake_rows()
        self._table_model.set_rows(self._rows)
        self._timer.start(self._scan_interval_spin.value())
        self._scanning = True
        self._start_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._last_updated = datetime.now().strftime("%H:%M:%S")
        self._log("Start Scan clicked")
        self._update_status()

    def _stop_scan(self) -> None:
        if not self._timer.isActive():
            return
        self._timer.stop()
        self._scanning = False
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._log("Stop clicked")
        self._update_status()

    def _clear_scan(self) -> None:
        self._timer.stop()
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

    def _update_fake_rows(self) -> None:
        if not self._rows:
            return
        for index, row in enumerate(self._rows):
            spread_pct = max(0.01, row.spread_pct + random.uniform(-0.05, 0.08))
            score = max(0.0, min(100.0, row.score + random.uniform(-2.0, 2.5)))
            spread_abs = max(0.0, row.buy_ask * (spread_pct / 100))
            status = self._pick_status(spread_pct, score)
            self._rows[index] = replace(
                row,
                spread_pct=spread_pct,
                spread_abs=spread_abs,
                score=score,
                status=status,
            )
        self._table_model.notify_rows_updated()
        self._last_updated = datetime.now().strftime("%H:%M:%S")
        self._update_status()

    def _pick_status(self, spread_pct: float, score: float) -> str:
        if spread_pct > 1.0 or score > 70:
            return "HOT"
        if spread_pct > 0.5:
            return "TRACKING"
        return "WARM"

    def _generate_fake_rows(self) -> list[ScannerRow]:
        count = random.randint(10, 20)
        quotes = self._selected_quote_currencies()
        exchanges = self._selected_exchanges()
        rows: list[ScannerRow] = []
        for _ in range(count):
            base = random.choice(self._base_assets)
            quote = random.choice(quotes)
            pair = f"{base}/{quote}"
            if len(exchanges) > 1:
                buy_exchange, sell_exchange = random.sample(exchanges, k=2)
            else:
                buy_exchange = sell_exchange = exchanges[0]
            price = self._base_price_for_asset(base)
            buy_ask = price * random.uniform(0.995, 1.005)
            sell_bid = buy_ask * random.uniform(1.0005, 1.015)
            spread_abs = max(0.0, sell_bid - buy_ask)
            spread_pct = max(0.01, (spread_abs / buy_ask) * 100)
            volume = random.uniform(120_000, 8_500_000)
            stable_hits = random.randint(1, 6)
            score = random.uniform(15.0, 85.0)
            status = self._pick_status(spread_pct, score)
            rows.append(
                ScannerRow(
                    pair=pair,
                    best_buy_exchange=buy_exchange,
                    buy_ask=buy_ask,
                    best_sell_exchange=sell_exchange,
                    sell_bid=sell_bid,
                    spread_abs=spread_abs,
                    spread_pct=spread_pct,
                    volume_24h=volume,
                    stable_hits=stable_hits,
                    score=score,
                    status=status,
                )
            )
        return rows

    def _base_price_for_asset(self, base: str) -> float:
        if base in {"BTC"}:
            return random.uniform(25_000, 65_000)
        if base in {"ETH"}:
            return random.uniform(1_600, 4_500)
        if base in {"SOL", "LTC", "BCH"}:
            return random.uniform(40, 220)
        if base in {"AVAX", "DOT", "ATOM", "NEAR", "APT"}:
            return random.uniform(5, 60)
        if base in {"XRP", "ADA", "DOGE", "TRX"}:
            return random.uniform(0.08, 1.2)
        return random.uniform(0.5, 10)

    def _update_timer_interval(self) -> None:
        if self._timer.isActive():
            self._timer.start(self._scan_interval_spin.value())

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
        self._timer.stop()
        self._scanning = False
        self._update_status()
        super().closeEvent(event)
