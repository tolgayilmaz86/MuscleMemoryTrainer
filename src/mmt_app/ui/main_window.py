from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

class MainWindow(QMainWindow):
    def __init__(self, *, app_name: str, version: str) -> None:
        super().__init__()
        self.app_name = app_name
        self.version = version
        self.setWindowTitle(f"{self.app_name} • v{self.version}")

        self.status_label = QLabel("Ready to train.")
        self.status_label.setObjectName("statusLabel")
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Session log will appear here.")

        self.start_button = QPushButton("Start Session")
        self.start_button.clicked.connect(self.on_start_clicked)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.log_view, stretch=1)
        layout.addWidget(self.start_button, alignment=Qt.AlignRight)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        self._write_welcome()

    def _write_welcome(self) -> None:
        self._append_log(
            "Welcome! Customize this window in src/mmt_app/ui/main_window.py "
            "and use resource_path() for assets."
        )

    def _append_log(self, text: str) -> None:
        self.log_view.append(f"[{datetime.now():%H:%M:%S}] {text}")

    def on_start_clicked(self) -> None:
        self.status_label.setText("Session started.")
        self._append_log("Session started.")
