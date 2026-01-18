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
        self._refresh_button = QPushButton("Refresh")
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
        self._refresh_quotes()
        logger.info("Manual refresh triggered")

    def _refresh_quotes(self) -> None:
        if self._fetch_in_progress:
            return
        pair = self._pair_combo.currentText()
        exchanges = list(self._selected_exchanges)
        self._fetch_in_progress = True
        worker = QuoteFetchWorker(self._price_provider, self._quote_service, pair, exchanges)
        worker.signals.finished.connect(self._handle_quotes)
        worker.signals.error.connect(self._handle_fetch_error)
        self._thread_pool.start(worker)

    def _handle_quotes(self, quotes: list[dict[str, object]]) -> None:
        self._table_model.update_quotes(quotes)
        self._updates_count += 1
        self._errors_count = sum(1 for quote in quotes if str(quote.get("status", "")).lower() == "error")
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

    def _update_counters(self) -> None:
        self._active_label.setText(f"Active exchanges: {len(self._selected_exchanges)}")
        self._updates_label.setText(f"Updates: {self._updates_count}")
        self._errors_label.setText(f"Errors: {self._errors_count}")
        self._last_update_label.setText(f"Last update: {self._last_update}")

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
