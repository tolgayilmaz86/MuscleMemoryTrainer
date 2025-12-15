"""About tab displaying application information and credits.

This module provides information about the application, version,
developer credits, and support links.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mmt_app.ui.utils import resource_path


class AboutTab(QWidget):
    """About tab with application info and developer credits.

    Displays:
    - Application name and version
    - Brief description
    - Developer information with GitHub link
    - Buy Me a Coffee support button
    """

    def __init__(
        self,
        *,
        app_name: str,
        version: str,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the About tab.

        Args:
            app_name: Name of the application.
            version: Current version string.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._app_name = app_name
        self._version = version
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the About tab UI."""
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        # App title and version
        title_label = QLabel(f"<h1>{self._app_name}</h1>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        version_label = QLabel(f"<h3>Version {self._version}</h3>")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        # Description
        description = QLabel(
            "<p style='font-size: 14px;'>"
            "A training tool for sim racing pedal muscle memory.<br>"
            "Practice throttle control, brake modulation, and trail braking<br>"
            "with real-time visual feedback."
            "</p>"
        )
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        layout.addWidget(description)

        layout.addSpacing(20)

        # Developer info
        dev_label = QLabel(
            "<p style='font-size: 13px;'>"
            "<b>Developed by:</b> Tolga Yılmaz"
            "</p>"
        )
        dev_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dev_label)

        # GitHub button
        github_button = QPushButton("GitHub")
        github_button.setFixedWidth(120)
        github_button.setCursor(Qt.CursorShape.PointingHandCursor)
        github_button.clicked.connect(self._open_github)
        github_button.setStyleSheet(
            """
            QPushButton {
                background-color: #24292e;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3c4146;
            }
            QPushButton:pressed {
                background-color: #1a1e22;
            }
            """
        )

        github_row = QHBoxLayout()
        github_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        github_row.addWidget(github_button)
        layout.addLayout(github_row)

        layout.addSpacing(30)

        # Support section
        support_label = QLabel(
            "<p style='font-size: 13px;'>"
            "<b>Support this project:</b>"
            "</p>"
        )
        support_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(support_label)

        # Buy Me a Coffee button
        bmc_button = QPushButton()
        bmc_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bmc_button.setFlat(True)
        bmc_button.clicked.connect(self._open_bmc)

        # Load the BMC button image
        bmc_pixmap = QPixmap(str(resource_path("bmc-button.png")))
        if not bmc_pixmap.isNull():
            # Scale to reasonable size while maintaining aspect ratio
            scaled_pixmap = bmc_pixmap.scaledToHeight(
                50, Qt.TransformationMode.SmoothTransformation
            )
            bmc_button.setIcon(scaled_pixmap)
            bmc_button.setIconSize(scaled_pixmap.size())
            bmc_button.setFixedSize(
                scaled_pixmap.width() + 10,
                scaled_pixmap.height() + 10,
            )
        else:
            # Fallback text if image not found
            bmc_button.setText("Buy Me a Coffee ☕")
            bmc_button.setStyleSheet(
                """
                QPushButton {
                    background-color: #FFDD00;
                    color: black;
                    border: none;
                    border-radius: 6px;
                    padding: 10px 20px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #FFE44D;
                }
                """
            )

        bmc_row = QHBoxLayout()
        bmc_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bmc_row.addWidget(bmc_button)
        layout.addLayout(bmc_row)

        # Add stretch to push everything to center-top
        layout.addStretch()

        # Footer
        footer = QLabel(
            "<p style='font-size: 11px; color: gray;'>"
            "© 2025 Tolga Yılmaz. MIT License."
            "</p>"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)

    def _open_github(self) -> None:
        """Open the GitHub profile in the default browser."""
        QDesktopServices.openUrl(QUrl("https://github.com/tolgayilmaz86/"))

    def _open_bmc(self) -> None:
        """Open the Buy Me a Coffee page in the default browser."""
        QDesktopServices.openUrl(QUrl("https://buymeacoffee.com/tlgylmz"))
