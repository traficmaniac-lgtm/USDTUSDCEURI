"""Main window UI for the application."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QWidget, QVBoxLayout


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("USDTUSDCEURI")
        self._build_ui()

    def _build_ui(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        title = QLabel("USDT / USDC Analyzer")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("GUI is ready for дальнейшая логика арбитража")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.setCentralWidget(container)
