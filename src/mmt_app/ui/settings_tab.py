"""Settings tab for device configuration, calibration, and sound settings.

This module provides a centralized settings interface that composes
specialized widgets following the Single Responsibility Principle.

The SettingsTab acts as a facade, delegating to:
- DeviceSelector: HID device selection and connection
- CalibrationSettingsGroup: Calibration parameters and wizards
- SoundSettingsGroup: Target sound configuration
- DisplaySettingsGroup: Chart display options
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mmt_app.config import (
    InputProfile,
    PedalsConfig,
    WheelConfig,
    UiConfig,
    load_input_profile,
    save_input_profile,
    save_ui_config,
    DEFAULT_STEERING_CENTER,
    DEFAULT_STEERING_RANGE,
    DEFAULT_STEERING_HALF_RANGE,
)
from mmt_app.input.hid_backend import HidSession

from mmt_app.ui.device_selector import DeviceSelector
from mmt_app.ui.calibration_settings import CalibrationSettingsGroup
from mmt_app.ui.sound_settings import SoundSettingsGroup
from mmt_app.ui.sound_manager import SoundManager
from mmt_app.ui.display_settings import DisplaySettingsGroup
from mmt_app.ui.steering_calibration_wizard import (
    SteeringCalibrationWizard,
    SteeringCalibrationResult,
)
from mmt_app.ui.input_setup_wizard import InputSetupWizard, InputSetupResult

if TYPE_CHECKING:
    from mmt_app.telemetry import TelemetrySample


_UI_SAVE_DEBOUNCE_MS: int = 500
"""Debounce interval (ms) for persisting UI settings."""


class SettingsTab(QWidget):
    """Settings tab composing device, calibration, sound, and display widgets.

    This class acts as a facade, providing a unified interface while
    delegating to specialized components for each concern.

    Attributes:
        pedals_session: HID session for the pedals device.
        wheel_session: HID session for the wheel device.
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
        """
        super().__init__(parent)

        # Store callbacks
        self._on_status_update = on_status_update or (lambda _: None)
        self._on_targets_changed = on_targets_changed or (lambda: None)

        # Initialize steering state
        self._steering_center: int = DEFAULT_STEERING_CENTER
        self._steering_range: int = DEFAULT_STEERING_RANGE
        self._steering_half_range: int = DEFAULT_STEERING_HALF_RANGE

        # Create sound manager
        self._sound_manager = SoundManager()

        # Create UI components
        self._device_selector = DeviceSelector(
            parent=self,
            on_status_update=self._set_status,
        )

        self._calibration_settings = CalibrationSettingsGroup(
            parent=self,
            on_setup_wizard=self._start_input_setup_wizard,
            on_calibrate_steering=self._start_steering_calibration,
            on_steering_range_changed=self._on_steering_range_changed,
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

        # Load persisted configuration
        self._load_persisted_config()

    # -------------------------------------------------------------------------
    # Public properties - HID sessions (delegated)
    # -------------------------------------------------------------------------

    @property
    def pedals_session(self) -> HidSession:
        """Return the pedals HID session."""
        return self._device_selector.pedals_session

    @property
    def wheel_session(self) -> HidSession:
        """Return the wheel HID session."""
        return self._device_selector.wheel_session

    # -------------------------------------------------------------------------
    # Public properties - Calibration (delegated)
    # -------------------------------------------------------------------------

    @property
    def pedals_report_len(self) -> int:
        """Return the configured pedals report length."""
        return self._calibration_settings.pedals_report_len

    @property
    def wheel_report_len(self) -> int:
        """Return the configured wheel report length."""
        return self._calibration_settings.wheel_report_len

    @property
    def throttle_offset(self) -> int:
        """Return the configured throttle byte offset."""
        return self._calibration_settings.throttle_offset

    @property
    def brake_offset(self) -> int:
        """Return the configured brake byte offset."""
        return self._calibration_settings.brake_offset

    @property
    def steering_offset(self) -> int:
        """Return the configured steering byte offset."""
        return self._calibration_settings.steering_offset

    @property
    def steering_bits(self) -> int:
        """Return the steering bit depth (8, 16, or 32)."""
        return self._calibration_settings.steering_bits

    @property
    def steering_center(self) -> int:
        """Return the calibrated steering center value."""
        return self._steering_center

    @property
    def steering_range(self) -> int:
        """Return the steering range (wheel rotation degrees)."""
        return self._calibration_settings.steering_range

    @property
    def steering_half_range(self) -> int:
        """Return the calibrated steering half-range."""
        return self._steering_half_range

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
    # Public methods - Device management (delegated)
    # -------------------------------------------------------------------------

    def refresh_devices(self) -> None:
        """Refresh the list of available HID devices."""
        self._device_selector.refresh_devices()

    def connect_devices(self) -> None:
        """Open/close HID sessions based on current combo selections."""
        self._device_selector.connect_devices()

    def close_sessions(self) -> None:
        """Close all HID sessions (call on application exit)."""
        self._device_selector.close_sessions()

    # -------------------------------------------------------------------------
    # Public methods - Sound (delegated)
    # -------------------------------------------------------------------------

    def sound_enabled(self, kind: str) -> bool:
        """Return whether a given target sound is enabled."""
        return self._sound_settings.sound_enabled(kind)

    def resolve_sound_path(self, kind: str) -> str:
        """Get the stored sound path, falling back to the default."""
        return self._sound_settings.resolve_sound_path(kind)

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
        layout.addWidget(self._device_selector)
        layout.addWidget(self._calibration_settings)
        layout.addWidget(self._sound_settings)
        layout.addWidget(self._display_settings)

        # Status label
        self._device_status = QLabel("Select devices above to start streaming.")
        layout.addWidget(self._device_status)

        layout.addStretch()

        # Save button
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_current_mapping)
        btn_row.addWidget(save_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    # -------------------------------------------------------------------------
    # Configuration persistence
    # -------------------------------------------------------------------------

    def save_current_mapping(self) -> None:
        """Persist the current device configuration to config.ini."""
        pedals_cfg = None
        wheel_cfg = None

        # Get pedals device info
        pedals_dev = self._device_selector.pedals_device
        if not pedals_dev:
            pedals_dev = self._device_selector.get_selected_pedals_device()

        if pedals_dev:
            pedals_cfg = PedalsConfig(
                vendor_id=pedals_dev.device_id.vendor_id,
                product_id=pedals_dev.device_id.product_id,
                product_string=pedals_dev.product_string,
                report_len=self._calibration_settings.pedals_report_len,
                throttle_offset=self._calibration_settings.throttle_offset,
                brake_offset=self._calibration_settings.brake_offset,
            )

        # Get wheel device info
        wheel_dev = self._device_selector.wheel_device
        if not wheel_dev:
            wheel_dev = self._device_selector.get_selected_wheel_device()

        if wheel_dev:
            wheel_cfg = WheelConfig(
                vendor_id=wheel_dev.device_id.vendor_id,
                product_id=wheel_dev.device_id.product_id,
                product_string=wheel_dev.product_string,
                report_len=self._calibration_settings.wheel_report_len,
                steering_offset=self._calibration_settings.steering_offset,
                steering_center=self._steering_center,
                steering_range=self._calibration_settings.steering_range,
                steering_half_range=self._steering_half_range,
                steering_bits=self._calibration_settings.steering_bits,
            )

        save_input_profile(InputProfile(pedals=pedals_cfg, wheel=wheel_cfg, ui=None))
        self._set_status("Device configuration saved to config.ini.")

    def _load_persisted_config(self) -> None:
        """Load persisted device and UI configuration on startup."""
        self._device_selector.refresh_devices()

        try:
            profile = load_input_profile()
            self._apply_device_config(profile)
        except Exception:
            pass

    def _apply_device_config(self, profile: InputProfile) -> None:
        """Apply a loaded device configuration to UI controls."""
        pedals_cfg = profile.pedals
        wheel_cfg = profile.wheel

        if pedals_cfg:
            self._calibration_settings.set_pedals_report_len(pedals_cfg.report_len)
            self._calibration_settings.set_throttle_offset(pedals_cfg.throttle_offset)
            self._calibration_settings.set_brake_offset(pedals_cfg.brake_offset)
            self._device_selector.select_device_by_vid_pid(
                "pedals", pedals_cfg.vendor_id, pedals_cfg.product_id
            )

        if wheel_cfg:
            self._calibration_settings.set_wheel_report_len(wheel_cfg.report_len)
            self._calibration_settings.set_steering_offset(wheel_cfg.steering_offset)
            self._calibration_settings.set_steering_bits(wheel_cfg.steering_bits)
            self._steering_center = wheel_cfg.steering_center
            self._steering_half_range = wheel_cfg.steering_half_range
            self._calibration_settings.set_steering_range(wheel_cfg.steering_range)
            self._steering_range = max(180, min(1080, wheel_cfg.steering_range))
            self._device_selector.select_device_by_vid_pid(
                "wheel", wheel_cfg.vendor_id, wheel_cfg.product_id
            )

        # Auto-connect if devices found
        if pedals_cfg or wheel_cfg:
            self._device_selector.connect_devices()

    def _schedule_save_ui_settings(self) -> None:
        """Debounce UI settings save to avoid excessive writes."""
        self._ui_save_timer.start(_UI_SAVE_DEBOUNCE_MS)

    def _save_ui_settings(self) -> None:
        """Persist UI-related settings."""
        sound_settings = self._sound_settings.get_sound_settings()

        cfg = UiConfig(
            throttle_target=self._display_settings.throttle_target,
            brake_target=self._display_settings.brake_target,
            grid_step_percent=self._display_settings.grid_step,
            update_hz=self._display_settings.update_rate,
            show_steering=self._display_settings.show_steering,
            show_watermark=self._display_settings.show_watermark,
            throttle_sound_enabled=sound_settings["throttle_sound_enabled"],
            throttle_sound_path=sound_settings["throttle_sound_path"],
            brake_sound_enabled=sound_settings["brake_sound_enabled"],
            brake_sound_path=sound_settings["brake_sound_path"],
        )
        save_ui_config(cfg)

    # -------------------------------------------------------------------------
    # Calibration wizards
    # -------------------------------------------------------------------------

    def _start_input_setup_wizard(self) -> None:
        """Start the comprehensive input setup wizard."""
        if not self.pedals_session.is_open and not self.wheel_session.is_open:
            self._set_status("Select pedals and/or wheel HID device first, then click Connect.")
            return

        wizard = InputSetupWizard(
            parent=self,
            pedals_session=self.pedals_session,
            wheel_session=self.wheel_session,
            get_pedals_report_len=lambda: self._calibration_settings.pedals_report_len,
            get_wheel_report_len=lambda: self._calibration_settings.wheel_report_len,
            get_steering_offset=lambda: self._calibration_settings.steering_offset,
            get_steering_bits=lambda: self._calibration_settings.steering_bits,
            on_axis_detected=self._on_axis_detected,
            on_report_len_detected=self._on_report_len_detected,
            on_steering_center_captured=self._on_steering_center_captured,
            on_complete=self._on_setup_wizard_complete,
            on_status_update=self._set_status,
        )
        wizard.show()

    def _on_axis_detected(self, device: str, axis: str, offset: int, score: float) -> None:
        """Handle axis detection from setup wizard."""
        if axis == "throttle":
            self._calibration_settings.set_throttle_offset(offset)
        elif axis == "brake":
            self._calibration_settings.set_brake_offset(offset)
        elif axis == "steering":
            self._calibration_settings.set_steering_offset(offset)

    def _on_report_len_detected(self, device: str, length: int) -> None:
        """Handle report length detection from setup wizard."""
        if device == "pedals":
            self._calibration_settings.set_pedals_report_len(length)
        else:
            self._calibration_settings.set_wheel_report_len(length)

    def _on_steering_center_captured(self, center: int) -> None:
        """Handle steering center capture from setup wizard."""
        self._steering_center = center

    def _on_setup_wizard_complete(self, result: InputSetupResult) -> None:
        """Handle setup wizard completion."""
        try:
            self.save_current_mapping()
        except Exception:
            pass

    def _start_steering_calibration(self) -> None:
        """Start the steering calibration wizard."""
        if not self.wheel_session.is_open:
            self._set_status("Wheel not connected. Click Connect first.")
            return

        wizard = SteeringCalibrationWizard(
            parent=self,
            wheel_session=self.wheel_session,
            on_complete=self._on_steering_calibration_complete,
            on_status_update=self._set_status,
        )
        wizard.show()

    def _on_steering_calibration_complete(self, result: SteeringCalibrationResult) -> None:
        """Handle steering calibration completion."""
        self._calibration_settings.set_wheel_report_len(result.report_len)
        self._calibration_settings.set_steering_offset(result.offset)
        self._calibration_settings.set_steering_bits(result.bits)
        self._steering_center = result.center
        self._steering_half_range = result.half_range

        try:
            self.save_current_mapping()
        except Exception:
            pass

    def _on_steering_range_changed(self, value: int) -> None:
        """Handle steering range slider changes."""
        self._steering_range = value
        try:
            self.save_current_mapping()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Status helper
    # -------------------------------------------------------------------------

    def _set_status(self, message: str) -> None:
        """Update the status label and notify the callback."""
        self._device_status.setText(message)
        self._on_status_update(message)

    # -------------------------------------------------------------------------
    # Backward-compatible internal widget access (for tests)
    # -------------------------------------------------------------------------

    @property
    def _pedals_report_len(self):
        """Expose pedals report length spinbox for tests."""
        return self._calibration_settings._pedals_report_len

    @property
    def _wheel_report_len(self):
        """Expose wheel report length spinbox for tests."""
        return self._calibration_settings._wheel_report_len

    @property
    def _throttle_offset(self):
        """Expose throttle offset spinbox for tests."""
        return self._calibration_settings._throttle_offset

    @property
    def _brake_offset(self):
        """Expose brake offset spinbox for tests."""
        return self._calibration_settings._brake_offset

    @property
    def _steering_offset(self):
        """Expose steering offset spinbox for tests."""
        return self._calibration_settings._steering_offset

    @property
    def _steering_range_slider(self):
        """Expose steering range slider for tests."""
        return self._calibration_settings._steering_range_slider

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
