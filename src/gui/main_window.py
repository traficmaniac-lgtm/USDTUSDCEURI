"""Main window UI for the application."""

from __future__ import annotations

from datetime import datetime
from loguru import logger
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .models.quotes_table_model import QuotesTableModel
from .services.ccxt_price_provider import CcxtPriceProvider
from .services.quote_generator import FakeQuoteService
from .widgets.exchange_selector import ExchangeSelectorDialog
from .widgets.log_panel import LogPanel


class LogEmitter(QObject):
    """Qt-friendly log emitter for loguru."""

    message = Signal(str, str)


class QuoteFetchSignals(QObject):
    """Signals for quote fetching worker."""

    finished = Signal(list)
    error = Signal(str)


class QuoteFetchWorker(QRunnable):
    """Background worker for fetching quotes."""

    def __init__(
        self,
        provider: CcxtPriceProvider,
        fallback: FakeQuoteService,
        pair: str,
        exchanges: list[str],
    ) -> None:
        super().__init__()
        self._provider = provider
        self._fallback = fallback
        self._pair = pair
        self._exchanges = exchanges
        self.signals = QuoteFetchSignals()

    def run(self) -> None:
        try:
            quotes = self._provider.fetch_quotes(self._pair, self._exchanges)
        except Exception as exc:
            quotes = self._fallback.generate(self._pair, self._exchanges)
            self.signals.error.emit(str(exc))
        self.signals.finished.emit(quotes)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("USDTUSDCEURI")
        self.resize(1200, 800)
        self._price_provider = CcxtPriceProvider()
        self._exchanges = self._price_provider.supported_exchanges()
        self._selected_exchanges = set(self._exchanges)
        self._quote_service = FakeQuoteService()
        self._updates_count = 0
        self._errors_count = 0
        self._last_update = "—"
        self._last_requested_exchanges: list[str] = []
        self._last_requested_pair = ""
        self._log_single_fetch = False
        self._last_rollup_log_at: datetime | None = None
        self._status_by_exchange: dict[str, str] = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_quotes)
        self._thread_pool = QThreadPool(self)
        self._fetch_in_progress = False
        self._log_emitter = LogEmitter()
        self._build_ui()
        self._setup_logging()
        self._set_status("Idle")
        logger.info("Application started")
        self._refresh_quotes()

    def _build_ui(self) -> None:
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.addLayout(self._build_top_bar())
        main_layout.addWidget(self._build_table())
        main_layout.addLayout(self._build_bottom_area())
        self.setCentralWidget(central)
        self._create_menus()

    def _build_top_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        pair_label = QLabel("Pair:")
        self._pair_combo = QComboBox()
        self._pair_combo.addItems(["USDT/USDC", "BTC/USDT", "ETH/USDT", "SOL/USDT"])
        self._pair_combo.setCurrentText("USDT/USDC")

        self._exchange_button = QPushButton("Select Exchanges")
        self._exchange_button.clicked.connect(self._open_exchange_dialog)
        self._exchange_summary = QLabel(self._exchange_summary_text())

        interval_label = QLabel("Update interval:")
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(250, 10000)
        self._interval_spin.setValue(1000)
        self._interval_spin.setSuffix(" ms")
        self._interval_spin.valueChanged.connect(self._update_interval)

        self._start_button = QPushButton("Start")
        self._stop_button = QPushButton("Stop")
        self._refresh_button = QPushButton("Test 1 fetch")
        self._start_button.clicked.connect(self._start_stream)
        self._stop_button.clicked.connect(self._stop_stream)
        self._refresh_button.clicked.connect(self._refresh_once)
        self._stop_button.setEnabled(False)

        self._status_label = QLabel("Idle")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setMinimumWidth(90)

        layout.addWidget(pair_label)
        layout.addWidget(self._pair_combo)
        layout.addSpacing(12)
        layout.addWidget(self._exchange_button)
        layout.addWidget(self._exchange_summary)
        layout.addSpacing(12)
        layout.addWidget(interval_label)
        layout.addWidget(self._interval_spin)
        layout.addStretch()
        layout.addWidget(self._start_button)
        layout.addWidget(self._stop_button)
        layout.addWidget(self._refresh_button)
        layout.addWidget(self._status_label)
        return layout

    def _build_table(self) -> QTableView:
        self._table_model = QuotesTableModel()
        self._table_view = QTableView()
        self._table_view.setModel(self._table_model)
        self._table_view.setSortingEnabled(True)
        self._table_view.setAlternatingRowColors(True)
        self._table_view.horizontalHeader().setStretchLastSection(True)
        self._table_view.horizontalHeader().setDefaultSectionSize(140)
        self._table_view.setSelectionBehavior(QTableView.SelectRows)
        self._table_view.setSelectionMode(QTableView.SingleSelection)
        return self._table_view

    def _build_bottom_area(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        self._log_panel = LogPanel()
        layout.addWidget(self._log_panel, stretch=2)

        counters_layout = QHBoxLayout()
        self._active_label = QLabel()
        self._updates_label = QLabel()
        self._errors_label = QLabel()
        self._last_update_label = QLabel()
        counters_layout.addWidget(self._active_label)
        counters_layout.addWidget(self._updates_label)
        counters_layout.addWidget(self._errors_label)
        counters_layout.addWidget(self._last_update_label)
        counters_layout.addStretch()
        layout.addLayout(counters_layout)
        self._update_counters()
        return layout

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        settings_menu = self.menuBar().addMenu("Settings")
        open_logs_action = QAction("Open logs folder", self)
        open_logs_action.triggered.connect(self._open_logs_folder)
        settings_menu.addAction(open_logs_action)

        help_menu = self.menuBar().addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _setup_logging(self) -> None:
        def sink(message: str) -> None:
            record = message.record
            self._log_emitter.message.emit(record["level"].name, record["message"])

        logger.add(sink, level="INFO")
        self._log_emitter.message.connect(self._log_panel.append_log)

    def _start_stream(self) -> None:
        if self._timer.isActive():
            return
        logger.info(
            "Start clicked | symbol={} | exchanges={} | interval={} ms",
            self._pair_combo.currentText(),
            sorted(self._selected_exchanges),
            self._interval_spin.value(),
        )
        self._timer.start(self._interval_spin.value())
        self._start_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._set_status("Running")
        logger.info("Streaming started")

    def _stop_stream(self) -> None:
        if not self._timer.isActive():
            return
        self._timer.stop()
        self._start_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._set_status("Idle")
        logger.info("Streaming stopped")

    def _refresh_once(self) -> None:
        self._log_single_fetch = True
        self._refresh_quotes(exchanges=["Binance"])
        logger.info("Manual refresh triggered (Binance)")

    def _refresh_quotes(self, exchanges: list[str] | None = None) -> None:
        if self._fetch_in_progress:
            return
        pair = self._pair_combo.currentText()
        exchanges = exchanges or list(self._selected_exchanges)
        self._last_requested_pair = pair
        self._last_requested_exchanges = exchanges
        self._updates_count += 1
        self._fetch_in_progress = True
        worker = QuoteFetchWorker(self._price_provider, self._quote_service, pair, exchanges)
        worker.signals.finished.connect(self._handle_quotes)
        worker.signals.error.connect(self._handle_fetch_error)
        self._thread_pool.start(worker)

    def _handle_quotes(self, quotes: list[dict[str, object]]) -> None:
        normalized = self._normalize_quotes(quotes, self._last_requested_exchanges)
        if self._log_single_fetch:
            statuses = [str(item.get("status", "")) for item in normalized]
            has_numbers = any(
                float(item.get("bid", 0.0)) or float(item.get("ask", 0.0)) or float(item.get("last", 0.0))
                for item in normalized
            )
            logger.info("Test 1 fetch result | status={} | has_numbers={}", statuses, has_numbers)
            self._log_single_fetch = False
        self._log_status_changes(normalized)
        self._log_rollup(normalized)
        self._table_model.update_quotes(normalized)
        self._errors_count = sum(
            1 for quote in normalized if str(quote.get("status", "")).lower() in {"error", "no_symbol"}
        )
        self._last_update = datetime.now().strftime("%H:%M:%S")
        self._update_counters()
        self._fetch_in_progress = False

    def _handle_fetch_error(self, message: str) -> None:
        logger.warning("Falling back to fake quotes: {}", message)

    def _update_interval(self) -> None:
        if self._timer.isActive():
            self._timer.start(self._interval_spin.value())
        logger.info("Update interval set to {} ms", self._interval_spin.value())

    def _open_exchange_dialog(self) -> None:
        dialog = ExchangeSelectorDialog(self._exchanges, self._selected_exchanges, self)
        if dialog.exec():
            self._selected_exchanges = set(dialog.selected_exchanges())
            self._exchange_summary.setText(self._exchange_summary_text())
            logger.info("Selected {} exchanges", len(self._selected_exchanges))
            self._refresh_quotes()

    def _exchange_summary_text(self) -> str:
        count = len(self._selected_exchanges)
        return f"{count} selected"

    def _normalize_quotes(
        self,
        quotes: list[dict[str, object]],
        exchanges: list[str],
    ) -> list[dict[str, object]]:
        normalized: list[dict[str, object]] = []
        for item in quotes:
            normalized.append(self._normalize_quote_item(item))

        if not normalized:
            return [
                {
                    "exchange": exchange,
                    "bid": 0.0,
                    "ask": 0.0,
                    "last": 0.0,
                    "spread": 0.0,
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "status": "ERROR",
                    "error": "No data",
                }
                for exchange in exchanges
            ]

        seen = {str(item.get("exchange", "")) for item in normalized}
        missing = [exchange for exchange in exchanges if exchange not in seen]
        if missing:
            timestamp = datetime.now().strftime("%H:%M:%S")
            normalized.extend(
                {
                    "exchange": exchange,
                    "bid": 0.0,
                    "ask": 0.0,
                    "last": 0.0,
                    "spread": 0.0,
                    "timestamp": timestamp,
                    "status": "ERROR",
                    "error": "No data",
                }
                for exchange in missing
            )
        return normalized

    def _normalize_quote_item(self, item: dict[str, object]) -> dict[str, object]:
        exchange = (
            item.get("exchange")
            or item.get("exchange_name")
            or item.get("market")
            or item.get("name")
            or ""
        )
        bid = item.get("bid")
        if bid is None:
            bid = item.get("bidPrice") or item.get("b")
        ask = item.get("ask")
        if ask is None:
            ask = item.get("askPrice") or item.get("a")
        last = item.get("last")
        if last is None:
            last = item.get("price") or item.get("lastPrice") or item.get("c")
        spread = item.get("spread")
        if spread is None and bid is not None and ask is not None:
            try:
                spread = float(ask) - float(bid)
            except (TypeError, ValueError):
                spread = 0.0
        timestamp = item.get("timestamp") or item.get("time") or datetime.now().strftime("%H:%M:%S")
        status = item.get("status") or item.get("state") or "ERROR"
        return {
            "exchange": str(exchange),
            "bid": float(bid or 0.0),
            "ask": float(ask or 0.0),
            "last": float(last or 0.0),
            "spread": float(spread or 0.0),
            "timestamp": str(timestamp),
            "status": str(status),
            "error": item.get("error"),
        }

    def _update_counters(self) -> None:
        self._active_label.setText(f"Active exchanges: {len(self._selected_exchanges)}")
        self._updates_label.setText(f"Updates: {self._updates_count}")
        self._errors_label.setText(f"Errors: {self._errors_count}")
        self._last_update_label.setText(f"Last update: {self._last_update}")

    def _log_rollup(self, quotes: list[dict[str, object]]) -> None:
        now = datetime.now()
        if self._last_rollup_log_at and (now - self._last_rollup_log_at).total_seconds() < 5:
            return
        ok_count = 0
        no_symbol_count = 0
        error_count = 0
        for quote in quotes:
            status = str(quote.get("status", "")).upper()
            if status == "OK":
                ok_count += 1
            elif status == "NO_SYMBOL":
                no_symbol_count += 1
            elif status in {"ERROR", "TIMEOUT"}:
                error_count += 1
        logger.info(
            "Quote summary | OK={} | NO_SYMBOL={} | ERROR/TIMEOUT={}",
            ok_count,
            no_symbol_count,
            error_count,
        )
        self._last_rollup_log_at = now

    def _log_status_changes(self, quotes: list[dict[str, object]]) -> None:
        for quote in quotes:
            exchange = str(quote.get("exchange", ""))
            status = str(quote.get("status", ""))
            if not exchange:
                continue
            previous = self._status_by_exchange.get(exchange)
            if previous == status:
                continue
            self._status_by_exchange[exchange] = status
            message = str(quote.get("error") or "")
            if status.upper() in {"ERROR", "TIMEOUT", "NO_SYMBOL"}:
                logger.warning("Status change | {}: {} -> {} | {}", exchange, previous, status, message)
            else:
                logger.info("Status change | {}: {} -> {} | {}", exchange, previous, status, message)

    def _set_status(self, status: str) -> None:
        styles = {
            "Idle": "background-color: #edf2f7; color: #2d3748; padding: 4px; border-radius: 4px;",
            "Running": "background-color: #c6f6d5; color: #22543d; padding: 4px; border-radius: 4px;",
            "Error": "background-color: #fed7d7; color: #742a2a; padding: 4px; border-radius: 4px;",
        }
        self._status_label.setText(status)
        self._status_label.setStyleSheet(styles.get(status, ""))

    def _open_logs_folder(self) -> None:
        QMessageBox.information(self, "Logs", "Logs folder is not configured yet.")

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "About",
            "USDTUSDCEURI\nGUI scaffold for price sniffing and analytics.",
        )
