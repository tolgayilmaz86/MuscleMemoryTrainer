"""Sound settings widget for target sound configuration.

Provides UI controls for enabling and selecting sound files
for throttle/brake target notifications.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

from mmt_app.ui.sound_manager import SoundManager


class SoundSettingsGroup(QGroupBox):
    """Widget for sound-related settings.

    Provides controls for:
    - Enabling/disabling throttle and brake sounds
    - Selecting custom sound files for each type
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        sound_manager: SoundManager,
        on_settings_changed: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the sound settings group.

        Args:
            parent: Parent widget.
            sound_manager: Sound manager instance for playback.
            on_settings_changed: Callback for any setting change (for persistence).
        """
        super().__init__("Target Sounds", parent)

        self._sound_manager = sound_manager
        self._on_settings_changed = on_settings_changed or (lambda: None)
        self._checkboxes: dict[str, QCheckBox] = {}
        self._line_edits: dict[str, QLineEdit] = {}

        self._build_ui()

    # -------------------------------------------------------------------------
    # Public interface
    # -------------------------------------------------------------------------

    def sound_enabled(self, kind: str) -> bool:
        """Return whether a given target sound is enabled."""
        checkbox = self._checkboxes.get(kind)
        return checkbox.isChecked() if checkbox else False

    def resolve_sound_path(self, kind: str) -> str:
        """Get the stored sound path, falling back to the default."""
        return self._sound_manager.get_path(kind)

    def custom_sound_path(self, kind: str) -> str | None:
        """Get the user-selected sound path, or None when using the default."""
        return self._sound_manager.custom_path(kind)

    def play_target_sound(self, kind: str) -> None:
        """Play the selected sound for the given target."""
        self._sound_manager.play(kind)

    def apply_sound_settings(
        self,
        *,
        throttle_enabled: bool,
        throttle_path: str | None,
        brake_enabled: bool,
        brake_path: str | None,
    ) -> None:
        """Apply persisted sound enable/path settings to UI controls."""
        # Update checkboxes
        if "throttle" in self._checkboxes:
            self._checkboxes["throttle"].setChecked(throttle_enabled)
        if "brake" in self._checkboxes:
            self._checkboxes["brake"].setChecked(brake_enabled)

        # Update sound manager and line edits
        self._sound_manager.apply_settings(
            throttle_enabled=throttle_enabled,
            throttle_path=throttle_path,
            brake_enabled=brake_enabled,
            brake_path=brake_path,
        )
        self._set_sound_file("throttle", throttle_path, trigger_save=False)
        self._set_sound_file("brake", brake_path, trigger_save=False)

    def get_sound_settings(self) -> dict[str, bool | str | None]:
        """Get current sound settings for persistence (paths are None for the default)."""
        return {
            "throttle_sound_enabled": self.sound_enabled("throttle"),
            "throttle_sound_path": self.custom_sound_path("throttle"),
            "brake_sound_enabled": self.sound_enabled("brake"),
            "brake_sound_path": self.custom_sound_path("brake"),
        }

    # -------------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the sound settings layout."""
        form = QFormLayout(self)

        form.addRow("Throttle:  ", self._build_sound_row(kind="throttle", label="Throttle"))
        form.addRow("Brake:", self._build_sound_row(kind="brake", label="Brake"))

    def _build_sound_row(self, *, kind: str, label: str) -> QWidget:
        """Construct a row with path display, browse button, and enable checkbox."""
        checkbox = QCheckBox("Activate")
        checkbox.setChecked(True)
        checkbox.stateChanged.connect(lambda: self._on_checkbox_changed(kind))
        checkbox.stateChanged.connect(self._on_settings_changed)
        self._checkboxes[kind] = checkbox

        line_edit = QLineEdit()
        line_edit.setPlaceholderText("Default beep (built-in)")
        line_edit.setReadOnly(True)
        line_edit.setMinimumWidth(360)
        line_edit.textChanged.connect(self._on_settings_changed)
        self._line_edits[kind] = line_edit

        preview_btn = self._icon_button("▶", f"Play the {label.lower()} target sound")
        preview_btn.clicked.connect(lambda: self._sound_manager.preview(kind))

        browse_btn = self._icon_button("📂", "Choose a sound file (mp3 / ogg / wav)")
        browse_btn.clicked.connect(lambda: self._browse_sound_file(kind))

        reset_btn = self._icon_button("↺", "Use the default beep")
        reset_btn.clicked.connect(lambda: self._set_sound_file(kind, None, trigger_save=True))

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(line_edit, stretch=1)
        layout.addWidget(preview_btn)
        layout.addWidget(browse_btn)
        layout.addWidget(reset_btn)
        layout.addWidget(checkbox)
        return row

    @staticmethod
    def _icon_button(text: str, tooltip: str) -> QPushButton:
        """Create a flat, borderless icon button for a sound row."""
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.setFlat(True)
        button.setStyleSheet(
            "QPushButton { font-size: 20px; color: #94a3b8; background: transparent;"
            " border: none; padding: 0px 2px; }"
            "QPushButton:hover { color: #38bdf8; background: transparent; }"
            "QPushButton:pressed { background: transparent; }"
        )
        button.setCursor(Qt.PointingHandCursor)
        return button

    # -------------------------------------------------------------------------
    # Internal callbacks
    # -------------------------------------------------------------------------

    def _on_checkbox_changed(self, kind: str) -> None:
        """Handle checkbox state change."""
        checkbox = self._checkboxes.get(kind)
        if checkbox:
            self._sound_manager.set_enabled(kind, checkbox.isChecked())

    def _browse_sound_file(self, kind: str) -> None:
        """Open a file dialog to choose a sound file for throttle/brake targets."""
        current = self.custom_sound_path(kind)
        start_dir = Path(current).parent if current else Path.home()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {kind} target sound",
            str(start_dir),
            "Audio Files (*.mp3 *.wav *.ogg);;All Files (*.*)",
        )
        if file_path:
            self._set_sound_file(kind, file_path, trigger_save=True)

    def _set_sound_file(
        self, kind: str, path: Path | str | None, *, trigger_save: bool
    ) -> None:
        """Update the line edit for a sound file and optionally persist.

        A None (or built-in) path selects the default beep and clears the field.
        """
        self._sound_manager.set_path(kind, path)
        line_edit = self._line_edits.get(kind)
        if line_edit:
            line_edit.blockSignals(True)
            line_edit.setText(self._sound_manager.custom_path(kind) or "")
            line_edit.blockSignals(False)
        if trigger_save:
            self._on_settings_changed()
