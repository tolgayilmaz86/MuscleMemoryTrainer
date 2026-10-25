"""Settings tab for wheel/pedal setup, sound settings and display options.

This module provides a centralized settings interface that composes
specialized widgets following the Single Responsibility Principle.

The SettingsTab acts as a facade, delegating to:
- InputBindingsGroup: Which controller axis drives throttle, brake and steering
- SoundSettingsGroup: Target sound configuration
- DisplaySettingsGroup: Chart display options
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QLabel,
    QVBoxLayout,
    QWidget,
)

from mmt_app.config import (
    UiConfig,
    ensure_config_exists,
    load_ui_config,
    save_ui_config,
)
from mmt_app.input.bindings import ROLES, InputMapper, load_bindings
from mmt_app.input.controllers import InputHub
from mmt_app.ui.display_settings import DisplaySettingsGroup
from mmt_app.ui.input_setup import InputBindingsGroup
from mmt_app.ui.sound_manager import SoundManager
from mmt_app.ui.sound_settings import SoundSettingsGroup

_UI_SAVE_DEBOUNCE_MS: int = 500
"""Debounce interval (ms) for persisting UI settings."""


class SettingsTab(QWidget):
    """Settings tab composing input, sound, and display widgets.

    This class acts as a facade, providing a unified interface while
    delegating to specialized components for each concern.

    Attributes:
        inputs: Reads throttle/brake/steering from the bound controller axes.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_status_update: Callable[[str], None] | None = None,
        on_targets_changed: Callable[[], None] | None = None,
        on_grid_step_changed: Callable[[int], None] | None = None,
        on_update_rate_changed: Callable[[int], None] | None = None,
        on_steering_visible_changed: Callable[[bool], None] | None = None,
        on_watermark_visible_changed: Callable[[bool], None] | None = None,
        on_inputs_changed: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the settings tab.

        Args:
            parent: Parent widget.
            on_status_update: Callback invoked with status messages.
            on_targets_changed: Callback when throttle/brake targets change.
            on_grid_step_changed: Callback when grid step changes.
            on_update_rate_changed: Callback when update rate changes.
            on_steering_visible_changed: Callback when steering visibility changes.
            on_watermark_visible_changed: Callback when watermark visibility changes.
            on_inputs_changed: Callback when bindings change or controllers come and go.
        """
        super().__init__(parent)

        # Store callbacks
        self._on_status_update = on_status_update or (lambda _: None)
        self._on_targets_changed = on_targets_changed or (lambda: None)

        # Controllers and bindings
        ensure_config_exists()
        self._hub = InputHub()
        self._hub.refresh()
        self._inputs = InputMapper(self._hub, load_bindings())

        # Create sound manager
        self._sound_manager = SoundManager()

        # Create UI components
        self._input_bindings = InputBindingsGroup(
            self._inputs,
            parent=self,
            on_status_update=self._set_status,
            on_bindings_changed=on_inputs_changed,
        )

        self._sound_settings = SoundSettingsGroup(
            parent=self,
            sound_manager=self._sound_manager,
            on_settings_changed=self._schedule_save_ui_settings,
        )

        self._display_settings = DisplaySettingsGroup(
            parent=self,
            on_targets_changed=on_targets_changed,
            on_grid_step_changed=on_grid_step_changed,
            on_update_rate_changed=on_update_rate_changed,
            on_steering_visible_changed=on_steering_visible_changed,
            on_watermark_visible_changed=on_watermark_visible_changed,
            on_settings_changed=self._schedule_save_ui_settings,
        )

        # Setup save debounce timer
        self._ui_save_timer = QTimer(self)
        self._ui_save_timer.setSingleShot(True)
        self._ui_save_timer.setInterval(_UI_SAVE_DEBOUNCE_MS)
        self._ui_save_timer.timeout.connect(self._save_ui_settings)

        # Build layout
        self._build_ui()

    # -------------------------------------------------------------------------
    # Public properties - Inputs
    # -------------------------------------------------------------------------

    @property
    def inputs(self) -> InputMapper:
        """Return the mapper that reads the bound wheel/pedal axes."""
        return self._inputs

    # -------------------------------------------------------------------------
    # Public properties - Display (delegated)
    # -------------------------------------------------------------------------

    @property
    def update_rate(self) -> int:
        """Return the configured update rate in Hz."""
        return self._display_settings.update_rate

    @property
    def show_steering(self) -> bool:
        """Return whether steering trace should be visible."""
        return self._display_settings.show_steering

    @property
    def show_watermark(self) -> bool:
        """Return whether watermark should be visible on charts."""
        return self._display_settings.show_watermark

    @property
    def throttle_target(self) -> int:
        """Return the configured throttle target percentage."""
        return self._display_settings.throttle_target

    @property
    def brake_target(self) -> int:
        """Return the configured brake target percentage."""
        return self._display_settings.brake_target

    @property
    def grid_step(self) -> int:
        """Return the configured grid step percentage."""
        return self._display_settings.grid_step

    # -------------------------------------------------------------------------
    # Public methods - Inputs
    # -------------------------------------------------------------------------

    def open_input_setup(self, roles: Sequence[str] = ROLES) -> None:
        """Run the guided wheel & pedal setup."""
        self._input_bindings.open_setup(roles)

    def rescan_devices(self) -> None:
        """Look for newly connected wheels and pedals."""
        self._input_bindings.rescan()

    def close_sessions(self) -> None:
        """Close all controllers (call on application exit)."""
        self._hub.close()

    def flush_pending_saves(self) -> None:
        """Write any debounced settings immediately (call on application exit)."""
        if self._ui_save_timer.isActive():
            self._ui_save_timer.stop()
            self._save_ui_settings()

    # -------------------------------------------------------------------------
    # Public methods - Sound (delegated)
    # -------------------------------------------------------------------------

    def sound_enabled(self, kind: str) -> bool:
        """Return whether a given target sound is enabled."""
        return self._sound_settings.sound_enabled(kind)

    def resolve_sound_path(self, kind: str) -> str:
        """Get the stored sound path, falling back to the default."""
        return self._sound_settings.resolve_sound_path(kind)

    def custom_sound_path(self, kind: str) -> str | None:
        """Get the user-selected sound path, or None when using the default."""
        return self._sound_settings.custom_sound_path(kind)

    def play_target_sound(self, kind: str) -> None:
        """Play the selected sound for the given target."""
        self._sound_settings.play_target_sound(kind)

    def apply_sound_settings(
        self,
        *,
        throttle_enabled: bool,
        throttle_path: str | None,
        brake_enabled: bool,
        brake_path: str | None,
    ) -> None:
        """Apply persisted sound enable/path settings to UI controls."""
        self._sound_settings.apply_sound_settings(
            throttle_enabled=throttle_enabled,
            throttle_path=throttle_path,
            brake_enabled=brake_enabled,
            brake_path=brake_path,
        )

    # -------------------------------------------------------------------------
    # Public methods - Display setters (delegated)
    # -------------------------------------------------------------------------

    def set_update_rate(self, hz: int, *, update_slider: bool = False) -> None:
        """Set the update rate and optionally sync the slider."""
        self._display_settings.set_update_rate(hz, update_slider=update_slider)

    def set_show_steering(self, visible: bool, *, update_checkbox: bool = False) -> None:
        """Set steering visibility and optionally sync the checkbox."""
        self._display_settings.set_show_steering(visible, update_checkbox=update_checkbox)

    def set_show_watermark(self, visible: bool, *, update_checkbox: bool = False) -> None:
        """Set watermark visibility and optionally sync the checkbox."""
        self._display_settings.set_show_watermark(visible, update_checkbox=update_checkbox)

    def set_throttle_target(self, value: int) -> None:
        """Set the throttle target percentage."""
        self._display_settings.set_throttle_target(value)

    def set_brake_target(self, value: int) -> None:
        """Set the brake target percentage."""
        self._display_settings.set_brake_target(value)

    def set_grid_step(self, step_percent: int) -> None:
        """Set the grid step percentage."""
        self._display_settings.set_grid_step(step_percent)

    # -------------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the settings tab layout."""
        layout = QVBoxLayout(self)

        # Add component widgets
        layout.addWidget(self._input_bindings)
        layout.addWidget(self._sound_settings)
        layout.addWidget(self._display_settings)

        # Status label
        self._device_status = QLabel("")
        layout.addWidget(self._device_status)

        layout.addStretch()

        autosave_hint = QLabel("Changes are saved automatically.")
        autosave_hint.setObjectName("hintLabel")
        layout.addWidget(autosave_hint)

    # -------------------------------------------------------------------------
    # Configuration persistence
    # -------------------------------------------------------------------------

    def _schedule_save_ui_settings(self) -> None:
        """Debounce UI settings save to avoid excessive writes."""
        self._ui_save_timer.start(_UI_SAVE_DEBOUNCE_MS)

    def _save_ui_settings(self) -> None:
        """Persist UI-related settings.

        Fields owned by the main window (window size, last tab) are carried
        over from the existing config instead of being reset to defaults.
        """
        settings = dict(
            throttle_target=self._display_settings.throttle_target,
            brake_target=self._display_settings.brake_target,
            grid_step_percent=self._display_settings.grid_step,
            update_hz=self._display_settings.update_rate,
            show_steering=self._display_settings.show_steering,
            show_watermark=self._display_settings.show_watermark,
            throttle_sound_enabled=self._sound_settings.sound_enabled("throttle"),
            throttle_sound_path=self._sound_settings.custom_sound_path("throttle"),
            brake_sound_enabled=self._sound_settings.sound_enabled("brake"),
            brake_sound_path=self._sound_settings.custom_sound_path("brake"),
        )
        existing = load_ui_config()
        cfg = replace(existing, **settings) if existing else UiConfig(**settings)
        save_ui_config(cfg)

    # -------------------------------------------------------------------------
    # Status helper
    # -------------------------------------------------------------------------

    def _set_status(self, message: str) -> None:
        """Update the status label and notify the callback."""
        self._device_status.setText(message)
        self._on_status_update(message)

    # -------------------------------------------------------------------------
    # Internal widget access (for tests)
    # -------------------------------------------------------------------------

    @property
    def _throttle_target_slider(self):
        """Expose throttle target slider for tests."""
        return self._display_settings._throttle_target_slider

    @property
    def _brake_target_slider(self):
        """Expose brake target slider for tests."""
        return self._display_settings._brake_target_slider

    @property
    def _grid_step_slider(self):
        """Expose grid step slider for tests."""
        return self._display_settings._grid_step_slider
