"""Scanner mode window (UI scaffold only)."""

from __future__ import annotations

from datetime import datetime
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .models.scanner_table_model import ScannerRow, ScannerTableModel
from .pair_analysis_window import PairAnalysisWindow
from ..core.update_controller import get_update_controller
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
        self._discovery_job = None
        self._discovery_request_id = 0
        self._scan_job = None
        self._pair_exchanges: dict[str, list[str]] = {}
        self._selected_exchanges_count = 0
        self._analysis_windows: dict[str, PairAnalysisWindow] = {}
        self._last_scan_ts: float | None = None
        self._last_scan_duration_ms: float | None = None
        self._heartbeat_timer: QTimer | None = None
        self._discovery_total_exchanges = 0
        self._scan_timer: QTimer | None = None
        self._scan_run_id = 0
        self._scan_in_flight = False
        self._stage = "STOP"
        self._heartbeat_phase = 0
        self._scan_backoff_s = 0.0
        self._last_scan_ok = 0
        self._last_scan_fail = 0
        self._next_scan_eta_s: float | None = None
        self._update_controller = get_update_controller()

        self._build_ui()
        self._start_heartbeat_timer()
        self._log("Окно сканера открыто")
        self._update_status()
        self._set_stage_stopped()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(self._build_toolbar())
        layout.addWidget(self._build_profit_panel(), stretch=3)
        layout.addLayout(self._build_status_log(), stretch=1)
        self.setCentralWidget(central)
        self._build_settings_dock()
        self._create_actions()

    def _create_actions(self) -> None:
        close_action = QAction("Закрыть", self)
        close_action.triggered.connect(self.close)
        self.addAction(close_action)

    def _build_settings_panel(self) -> QWidget:
        panel = QWidget()
        outer_layout = QVBoxLayout(panel)

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
        outer_layout.addStretch()
        return panel

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

    def _build_toolbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self._settings_toggle_button = QPushButton("⚙ Настройки")
        self._settings_toggle_button.setCheckable(True)
        self._settings_toggle_button.toggled.connect(self._toggle_settings_dock)
        self._start_button = QPushButton("Старт")
        self._stop_button = QPushButton("Стоп")
        self._clear_button = QPushButton("Очистить")

        self._start_button.clicked.connect(self._start_scan)
        self._stop_button.clicked.connect(self._stop_scan)
        self._clear_button.clicked.connect(self._clear_scan)

        self._stop_button.setEnabled(False)

        layout.addWidget(self._settings_toggle_button)
        layout.addWidget(self._start_button)
        layout.addWidget(self._stop_button)
        layout.addWidget(self._clear_button)
        layout.addStretch()
        return layout

    def _build_settings_dock(self) -> None:
        self._settings_dock = QDockWidget("Настройки", self)
        self._settings_dock.setWidget(self._build_settings_panel())
        self._settings_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._settings_dock.visibilityChanged.connect(self._sync_settings_toggle)
        self.addDockWidget(Qt.RightDockWidgetArea, self._settings_dock)
        self._settings_dock.setVisible(False)

    def _toggle_settings_dock(self, visible: bool) -> None:
        if hasattr(self, "_settings_dock"):
            self._settings_dock.setVisible(visible)

    def _sync_settings_toggle(self, visible: bool) -> None:
        if hasattr(self, "_settings_toggle_button"):
            self._settings_toggle_button.setChecked(visible)

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
        status_layout = QHBoxLayout()
        self._status_label = QLabel()
        self._stage_label = QLabel()
        self._heartbeat_label = QLabel()
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setVisible(False)
        status_layout.addWidget(self._status_label)
        status_layout.addSpacing(12)
        status_layout.addWidget(self._stage_label)
        status_layout.addSpacing(12)
        status_layout.addWidget(self._progress_bar)
        status_layout.addSpacing(12)
        status_layout.addWidget(self._heartbeat_label)
        status_layout.addStretch()
        layout.addLayout(status_layout)

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
        self._bump_scan_run()
        selected_exchanges = self._selected_exchanges()
        quotes = self._selected_quote_currencies()
        min_exchanges = self._min_exchanges_spin.value()
        self._selected_exchanges_count = len(selected_exchanges)
        self._discovery_total_exchanges = len(selected_exchanges)
        self._eligible_pairs = []
        self._pair_exchanges = {}
        self._profit_rows = []
        self._profit_table_model.set_rows([])
        self._scanning = True
        self._last_scan_ts = None
        self._start_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._log("Сканирование запущено")
        self._log(f"Загружаем рынки: биржи={len(selected_exchanges)}")
        self._set_stage_discovery(0, self._discovery_total_exchanges)
        self._update_status()
        self._start_market_discovery(selected_exchanges, quotes, min_exchanges)

    def _stop_scan(self) -> None:
        if not self._scanning:
            return
        self._bump_scan_run()
        self._cancel_market_discovery()
        self._stop_ticker_scan()
        self._scanning = False
        self._last_scan_ts = None
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._set_stage_stopped()
        self._log("Сканирование остановлено")
        self._update_status()

    def _clear_scan(self) -> None:
        self._bump_scan_run()
        self._cancel_market_discovery()
        self._stop_ticker_scan()
        self._eligible_pairs = []
        self._pair_exchanges = {}
        self._profit_rows = []
        self._profit_table_model.set_rows([])
        self._scanning = False
        self._last_scan_ts = None
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._last_updated = "—"
        self._set_stage_stopped()
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
        existing = self._analysis_windows.get(pair)
        if existing and not existing.isHidden():
            existing.raise_()
            existing.activateWindow()
            return
        selected_exchanges = self._selected_exchanges()
        threshold = self._opportunity_threshold_spin.value()
        window = PairAnalysisWindow(pair, selected_exchanges, threshold)
        window.destroyed.connect(lambda: self._analysis_windows.pop(pair, None))
        self._analysis_windows[pair] = window
        self._log(f"Открыто окно анализа: {pair}")
        window.show()

    def _start_market_discovery(
        self,
        exchanges: list[str],
        quotes: list[str],
        min_exchanges: int,
    ) -> None:
        self._discovery_request_id += 1
        request_id = self._discovery_request_id
        self._discovery_job = self._update_controller.submit(
            key="scanner-discovery",
            run_id=request_id,
            task=lambda: MarketDiscoveryService().discover(
                exchanges,
                quotes,
                min_exchanges,
            ),
        )
        if not self._discovery_job:
            self._log("Market discovery already in progress")
            return
        self._discovery_job.succeeded.connect(self._on_discovery_finished)
        self._discovery_job.failed.connect(self._on_discovery_failed)

    def _cancel_market_discovery(self) -> None:
        self._discovery_request_id += 1
        self._update_controller.clear_key("scanner-discovery")

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
                self._set_stage_stopped()
            elif self._selected_exchanges_count < min_exchanges:
                self._log(
                    "Скан цен не запущен: выберите больше бирж "
                    f"(нужно >= {min_exchanges})"
                )
                self._set_stage_stopped()
            else:
                self._set_stage_scanning()
                self._start_ticker_scan()
        self._last_updated = datetime.now().strftime("%H:%M:%S")
        self._update_status()

    def _on_discovery_failed(self, request_id: int, message: str) -> None:
        if request_id != self._discovery_request_id:
            return
        self._log(f"Ошибка поиска рынков: {message}")
        self._stop_ticker_scan()
        self._scanning = False
        self._last_scan_ts = None
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._set_stage_stopped()
        self._update_status()

    def _start_ticker_scan(self) -> None:
        self._stop_ticker_scan()
        interval_ms = self._scan_interval_spin.value()
        max_pairs = self._max_pairs_spin.value()
        max_intrabook_spread_pct = self._max_spread_spin.value()
        if self._scan_timer is None:
            self._scan_timer = QTimer(self)
            self._scan_timer.timeout.connect(self._trigger_ticker_scan)
        self._scan_timer.setInterval(interval_ms)
        self._scan_timer.start()
        self._trigger_ticker_scan()
        pairs_count = min(max_pairs, len(self._eligible_pairs))
        self._log(
            "Скан цен запущен: "
            f"pairs={pairs_count} exchanges={self._selected_exchanges_count}"
        )

    def _stop_ticker_scan(self) -> None:
        self._scan_job = None
        self._scan_in_flight = False
        self._scan_backoff_s = 0.0
        if self._scan_timer:
            self._scan_timer.stop()

    def _trigger_ticker_scan(self) -> None:
        if not self._scanning or self._scan_in_flight:
            return
        self._scan_in_flight = True
        scan_started = time.monotonic()
        self._scan_job = self._update_controller.submit(
            key="scanner-scan",
            run_id=self._scan_run_id,
            task=lambda: TickerScanService().scan(
                self._pair_exchanges,
                self._max_pairs_spin.value(),
                pairs=self._eligible_pairs,
                max_intrabook_spread_pct=self._max_spread_spin.value(),
            ),
        )
        if not self._scan_job:
            self._scan_in_flight = False
            return
        self._scan_job.succeeded.connect(
            lambda run_id, result: self._on_ticker_updated(run_id, result, scan_started)
        )
        self._scan_job.failed.connect(
            lambda run_id, message: self._on_ticker_failed(run_id, message, scan_started)
        )

    def _on_ticker_updated(
        self, run_id: int, result: TickerScanResult, scan_started: float
    ) -> None:
        self._scan_in_flight = False
        if not self._scanning or run_id != self._scan_run_id:
            return
        scan_latency_ms = (time.monotonic() - scan_started) * 1000
        self._last_scan_duration_ms = scan_latency_ms
        self._last_scan_ok = result.ok_count
        self._last_scan_fail = result.fail_count
        self._adjust_scan_backoff(result.fail_count)
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
        self._last_scan_ts = time.monotonic()
        self._last_updated = datetime.now().strftime("%H:%M:%S")
        self._update_status()
        for error in result.errors:
            self._log(error)
        self._log(
            "Update: "
            f"pairs={result.pair_count} ok={result.ok_count} "
            f"skipped={result.skipped_count} fail={result.fail_count}"
        )

    def _on_ticker_failed(
        self, run_id: int, message: str, scan_started: float
    ) -> None:
        self._scan_in_flight = False
        if run_id != self._scan_run_id:
            return
        scan_latency_ms = (time.monotonic() - scan_started) * 1000
        self._last_scan_duration_ms = scan_latency_ms
        self._last_scan_ok = 0
        self._last_scan_fail += 1
        self._adjust_scan_backoff(1)
        self._log(f"Ошибка сканирования тикеров: {message}")

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_view.appendPlainText(f"[{timestamp}] {message}")

    def _update_status(self) -> None:
        eligible = len(self._eligible_pairs)
        profit_count = len(self._profit_rows)
        live_count = sum(1 for row in self._profit_rows if row.status == "LIVE")
        latency_text = "—"
        slow_flag = ""
        if self._last_scan_duration_ms is not None:
            latency_text = f"{self._last_scan_duration_ms:.0f} ms"
            if self._last_scan_duration_ms > 5000:
                slow_flag = " | Slow / rate-limit"
        next_tick = "—"
        if self._scan_timer:
            remaining = self._scan_timer.remainingTime()
            if remaining >= 0:
                next_tick = f"{remaining / 1000:.1f} s"
        self._status_label.setText(
            f"Updated: {self._last_updated} | "
            f"Eligible: {eligible} | Профитные: {profit_count} | LIVE: {live_count} | "
            f"ok={self._last_scan_ok} fail={self._last_scan_fail} | "
            f"latency={latency_text} | next={next_tick}{slow_flag}"
        )

    def _start_heartbeat_timer(self) -> None:
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(500)
        self._heartbeat_timer.timeout.connect(self._update_heartbeat)
        self._heartbeat_timer.start()
        self._update_heartbeat()

    def _update_heartbeat(self) -> None:
        if not self._scanning or self._last_scan_ts is None:
            self._heartbeat_label.setText("Heartbeat: —")
            return
        elapsed = time.monotonic() - self._last_scan_ts
        interval = self._scan_interval_spin.value() / 1000
        if elapsed > max(interval * 2, 2.5):
            self._heartbeat_label.setText("Heartbeat: …")
            return
        self._heartbeat_phase = (self._heartbeat_phase + 1) % 3
        dots = "●" * (self._heartbeat_phase + 1)
        self._heartbeat_label.setText(f"Heartbeat: {dots}")

    def _set_stage_discovery(self, current: int, total: int) -> None:
        self._stage = "DISCOVERY"
        total_text = total if total > 0 else "—"
        self._stage_label.setText(f"Stage: DISCOVERY ({current}/{total_text})")
        self._progress_bar.setVisible(True)

    def _set_stage_scanning(self) -> None:
        self._stage = "SCAN"
        self._stage_label.setText("Stage: SCAN")
        self._progress_bar.setVisible(True)

    def _set_stage_stopped(self) -> None:
        self._stage = "STOP"
        self._stage_label.setText("Stage: STOP")
        self._progress_bar.setVisible(False)

    def _on_discovery_progress(self, current: int, total: int) -> None:
        self._set_stage_discovery(current, total)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._bump_scan_run()
        self._cancel_market_discovery()
        self._stop_ticker_scan()
        self._scanning = False
        self._last_scan_ts = None
        self._set_stage_stopped()
        self._update_status()
        super().closeEvent(event)

    def _bump_scan_run(self) -> None:
        self._scan_run_id += 1
        self._scan_in_flight = False

    def _adjust_scan_backoff(self, fail_count: int) -> None:
        if fail_count > 0:
            self._scan_backoff_s = 2.0 if self._scan_backoff_s == 0 else min(
                self._scan_backoff_s * 2, 8.0
            )
        else:
            self._scan_backoff_s = 0.0
        if self._scan_timer:
            base_ms = self._scan_interval_spin.value()
            next_ms = int(base_ms + self._scan_backoff_s * 1000)
            self._scan_timer.setInterval(next_ms)
            self._next_scan_eta_s = next_ms / 1000
            if self._scan_backoff_s > 0:
                self._log(
                    f"Backoff активирован: {self._scan_backoff_s:.0f}s "
                    f"(interval={next_ms} ms)"
                )
