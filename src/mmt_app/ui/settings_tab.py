"""Settings tab for device configuration, calibration, and sound settings.

This module provides a centralized settings interface following the Single
Responsibility Principle - all device/calibration/sound configuration
lives here, separate from the main window orchestration.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
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
)
from mmt_app.input.hid_backend import HidSession, HidDeviceInfo, hid_available, enumerate_devices
from mmt_app.ui.utils import clamp_int, resource_path

if TYPE_CHECKING:
    from mmt_app.telemetry import TelemetrySample

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CALIBRATION_DURATION_MS: int = 2000
"""Duration (ms) for each calibration sample capture phase."""

_STEERING_CAPTURE_MS: int = 3000
"""Duration (ms) for each steering calibration stage."""

_DEFAULT_PEDALS_REPORT_LEN: int = 4
"""Default expected byte length for pedal HID reports."""

_DEFAULT_WHEEL_REPORT_LEN: int = 8
"""Default expected byte length for wheel HID reports."""

_DEFAULT_THROTTLE_OFFSET: int = 1
"""Default byte offset for throttle axis in pedal reports."""

_DEFAULT_BRAKE_OFFSET: int = 2
"""Default byte offset for brake axis in pedal reports."""

_DEFAULT_STEERING_OFFSET: int = 0
"""Default byte offset for steering axis in wheel reports."""

_DEFAULT_STEERING_CENTER: int = 128
"""Default center value for steering calibration (8-bit mid-point)."""

_DEFAULT_STEERING_RANGE: int = 900
"""Default wheel rotation in degrees (180-1080)."""

_MAX_READS_PER_TICK: int = 50
"""Maximum HID reads per tick to drain the buffer."""

_UI_SAVE_DEBOUNCE_MS: int = 500
"""Debounce interval (ms) for persisting UI settings."""

_DEFAULT_THROTTLE_TARGET: int = 60
"""Default throttle target percentage."""

_DEFAULT_BRAKE_TARGET: int = 40
"""Default brake target percentage."""

_DEFAULT_GRID_STEP: int = 10
"""Default grid step percentage."""


class SettingsTab(QWidget):
    """Settings tab managing device configuration, calibration, and sound settings.

    This class encapsulates all settings-related functionality:
    - HID device selection and connection (pedals/wheel)
    - Throttle/brake offset calibration with auto-detection
    - Steering center/range calibration wizard
    - Target sound configuration (throttle/brake hit sounds)
    - Update rate and display options

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
    ) -> None:
        """Initialize the settings tab.

        Args:
            parent: Parent widget.
            on_status_update: Callback invoked with status messages.
            on_targets_changed: Callback when throttle/brake targets change.
            on_grid_step_changed: Callback when grid step changes.
            on_update_rate_changed: Callback when update rate changes.
            on_steering_visible_changed: Callback when steering visibility changes.
        """
        super().__init__(parent)

        # Callbacks for MainWindow integration
        self._on_status_update = on_status_update or (lambda _: None)
        self._on_targets_changed = on_targets_changed or (lambda: None)
        self._on_grid_step_changed = on_grid_step_changed or (lambda _: None)
        self._on_update_rate_changed = on_update_rate_changed or (lambda _: None)
        self._on_steering_visible_changed = on_steering_visible_changed or (lambda _: None)

        # HID device sessions and state
        self._devices: list[HidDeviceInfo] = []
        self._pedals_device: HidDeviceInfo | None = None
        self._wheel_device: HidDeviceInfo | None = None
        self._pedals_session = HidSession()
        self._wheel_session = HidSession()

        # Initialize internal state
        self._init_calibration_state()
        self._init_steering_state()
        self._init_sound_state()
        self._setup_timers()

        # Build the UI
        self._build_ui()

        # Load persisted configuration
        self._load_persisted_config()

    # -------------------------------------------------------------------------
    # Public properties
    # -------------------------------------------------------------------------

    @property
    def pedals_session(self) -> HidSession:
        """Return the pedals HID session."""
        return self._pedals_session

    @property
    def wheel_session(self) -> HidSession:
        """Return the wheel HID session."""
        return self._wheel_session

    @property
    def pedals_report_len(self) -> int:
        """Return the configured pedals report length."""
        return self._pedals_report_len.value()

    @property
    def wheel_report_len(self) -> int:
        """Return the configured wheel report length."""
        return self._wheel_report_len.value()

    @property
    def throttle_offset(self) -> int:
        """Return the configured throttle byte offset."""
        return self._throttle_offset.value()

    @property
    def brake_offset(self) -> int:
        """Return the configured brake byte offset."""
        return self._brake_offset.value()

    @property
    def steering_offset(self) -> int:
        """Return the configured steering byte offset."""
        return self._steering_offset.value()

    @property
    def steering_center(self) -> int:
        """Return the calibrated steering center value."""
        return self._steering_center

    @property
    def steering_range(self) -> int:
        """Return the calibrated steering range value."""
        return self._steering_range

    @property
    def update_rate(self) -> int:
        """Return the configured update rate in Hz."""
        return self._update_rate_slider.value()

    @property
    def show_steering(self) -> bool:
        """Return whether steering trace should be visible."""
        return self._show_steering_checkbox.isChecked()

    @property
    def throttle_target(self) -> int:
        """Return the configured throttle target percentage."""
        return self._throttle_target_slider.value()

    @property
    def brake_target(self) -> int:
        """Return the configured brake target percentage."""
        return self._brake_target_slider.value()

    @property
    def grid_step(self) -> int:
        """Return the configured grid step percentage."""
        return self._grid_step_slider.value()

    # -------------------------------------------------------------------------
    # Initialization methods
    # -------------------------------------------------------------------------

    def _init_calibration_state(self) -> None:
        """Initialize calibration-related state variables."""
        self._calibration_device: str | None = None
        self._calibration_axis: str | None = None
        self._calibration_callback: Callable[[str, int, float], None] | None = None
        self._baseline_samples: list[bytes] = []
        self._active_samples: list[bytes] = []
        self._pending_pedal_wizard: list[str] = []

    def _init_steering_state(self) -> None:
        """Initialize steering calibration state variables."""
        self._steering_center: int = _DEFAULT_STEERING_CENTER
        self._steering_range: int = _DEFAULT_STEERING_RANGE
        self._steering_center_samples: list[int] = []
        self._steering_left_samples: list[int] = []
        self._steering_right_samples: list[int] = []
        self._steering_pending_stage: str | None = None
        self._steering_cal_stage: str | None = None
        self._steering_cal_dialog: QDialog | None = None
        self._steering_cal_label: QLabel | None = None
        self._steering_cal_start_btn: QPushButton | None = None

    def _init_sound_state(self) -> None:
        """Initialize sound playback state variables."""
        self._default_sound_path = resource_path("assets/target_hit.mp3")
        self._sound_checkboxes: dict[str, QCheckBox] = {}
        self._sound_files: dict[str, QLineEdit] = {}

        # Media player for target sounds
        self._media_player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._media_player.setAudioOutput(self._audio_output)

    def _setup_timers(self) -> None:
        """Configure internal timers for calibration and debouncing."""
        self._calibration_timer = QTimer(self)
        self._calibration_timer.setInterval(20)
        self._calibration_timer.timeout.connect(self._capture_calibration_sample)

        self._steering_cal_timer = QTimer(self)
        self._steering_cal_timer.setInterval(20)
        self._steering_cal_timer.timeout.connect(self._capture_steering_calibration_sample)

        self._ui_save_timer = QTimer(self)
        self._ui_save_timer.setSingleShot(True)
        self._ui_save_timer.setInterval(_UI_SAVE_DEBOUNCE_MS)
        self._ui_save_timer.timeout.connect(self._save_ui_settings)

    # -------------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the settings tab layout."""
        layout = QVBoxLayout(self)

        # Device selection group
        layout.addWidget(self._build_device_group())

        # Calibration group
        layout.addWidget(self._build_calibration_group())

        # Sound settings group
        layout.addWidget(self._build_sound_group())

        # Display settings group
        layout.addWidget(self._build_display_group())

        # Status label
        self._device_status = QLabel("Select devices above to start streaming.")
        layout.addWidget(self._device_status)

        layout.addStretch()

        # Page-level buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.apply_device_selection)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_current_mapping)

        btn_row.addWidget(apply_btn)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    def _build_device_group(self) -> QGroupBox:
        """Build the device selection group box."""
        group = QGroupBox("Device Selection")
        form = QFormLayout(group)

        # Pedals device combo
        self._pedals_device_combo = QComboBox()
        self._pedals_device_combo.setMinimumWidth(280)
        form.addRow("Pedals HID:", self._pedals_device_combo)

        # Pedals report length
        self._pedals_report_len = QSpinBox()
        self._pedals_report_len.setRange(1, 64)
        self._pedals_report_len.setValue(_DEFAULT_PEDALS_REPORT_LEN)
        form.addRow("Pedals report length:", self._pedals_report_len)

        # Wheel device combo
        self._wheel_device_combo = QComboBox()
        self._wheel_device_combo.setMinimumWidth(280)
        form.addRow("Wheel HID:", self._wheel_device_combo)

        # Wheel report length
        self._wheel_report_len = QSpinBox()
        self._wheel_report_len.setRange(1, 64)
        self._wheel_report_len.setValue(_DEFAULT_WHEEL_REPORT_LEN)
        form.addRow("Wheel report length:", self._wheel_report_len)

        # Refresh button row
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_devices)

        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()

        form.addRow("", btn_row)

        return group

    def _build_calibration_group(self) -> QGroupBox:
        """Build the calibration settings group box."""
        group = QGroupBox("Calibration")
        form = QFormLayout(group)

        # Throttle offset
        self._throttle_offset = QSpinBox()
        self._throttle_offset.setRange(0, 63)
        self._throttle_offset.setValue(_DEFAULT_THROTTLE_OFFSET)
        form.addRow("Throttle byte offset:", self._throttle_offset)

        # Brake offset
        self._brake_offset = QSpinBox()
        self._brake_offset.setRange(0, 63)
        self._brake_offset.setValue(_DEFAULT_BRAKE_OFFSET)
        form.addRow("Brake byte offset:", self._brake_offset)

        # Steering offset
        self._steering_offset = QSpinBox()
        self._steering_offset.setRange(0, 63)
        self._steering_offset.setValue(_DEFAULT_STEERING_OFFSET)
        form.addRow("Steering byte offset:", self._steering_offset)

        # Manual steering center/range spinboxes
        steering_manual_row = QWidget()
        steering_manual_layout = QHBoxLayout(steering_manual_row)
        steering_manual_layout.setContentsMargins(0, 0, 0, 0)

        self._steering_center_value_label = QLabel(f"{_DEFAULT_STEERING_CENTER}")
        self._steering_center_value_label.setMinimumWidth(30)

        set_center_btn = QPushButton("Set Center")
        set_center_btn.setToolTip("Hold wheel centered and click to capture center position")
        set_center_btn.clicked.connect(self._set_steering_center_from_wheel)

        steering_manual_layout.addWidget(QLabel("Center:"))
        steering_manual_layout.addWidget(self._steering_center_value_label)
        steering_manual_layout.addWidget(set_center_btn)
        steering_manual_layout.addStretch()

        form.addRow("Steering center:", steering_manual_row)

        # Steering range slider (degrees of wheel rotation)
        self._steering_range_slider = QSlider(Qt.Horizontal)
        self._steering_range_slider.setObjectName("steeringRangeSlider")
        self._steering_range_slider.setRange(180, 1080)
        self._steering_range_slider.setSingleStep(10)
        self._steering_range_slider.setPageStep(90)
        self._steering_range_slider.setTickInterval(90)
        self._steering_range_slider.setTickPosition(QSlider.TicksBelow)
        self._steering_range_slider.setValue(_DEFAULT_STEERING_RANGE)
        self._steering_range_slider.valueChanged.connect(self._on_steering_range_changed)

        self._steering_range_label = QLabel(f"{_DEFAULT_STEERING_RANGE}°")
        self._steering_range_label.setObjectName("steeringRangeValue")
        self._steering_range_label.setStyleSheet("color: #f97316;")
        self._steering_range_label.setMinimumWidth(52)
        self._steering_range_slider.valueChanged.connect(
            lambda v: self._steering_range_label.setText(f"{int(v)}°")
        )

        steering_range_row = QWidget()
        steering_range_layout = QHBoxLayout(steering_range_row)
        steering_range_layout.setContentsMargins(0, 0, 0, 0)
        steering_range_layout.addWidget(self._steering_range_slider, stretch=1)
        steering_range_layout.addWidget(self._steering_range_label)

        form.addRow("Wheel rotation:", steering_range_row)

        # Calibration buttons row
        cal_btn_row = QWidget()
        cal_btn_layout = QHBoxLayout(cal_btn_row)
        cal_btn_layout.setContentsMargins(0, 0, 0, 0)

        auto_pedal_btn = QPushButton("Auto Pedal Offsets")
        auto_pedal_btn.clicked.connect(self._start_pedal_offset_wizard)

        cal_steering_btn = QPushButton("Calibrate Steering")
        cal_steering_btn.clicked.connect(self.calibrate_steering_range)

        cal_btn_layout.addWidget(auto_pedal_btn)
        cal_btn_layout.addWidget(cal_steering_btn)
        cal_btn_layout.addStretch()

        form.addRow("", cal_btn_row)

        return group

    def _build_sound_group(self) -> QGroupBox:
        """Build the sound settings group box."""
        group = QGroupBox("Target Sounds")
        form = QFormLayout(group)

        form.addRow("Throttle:", self._build_sound_row(kind="throttle", label="Throttle"))
        form.addRow("Brake:", self._build_sound_row(kind="brake", label="Brake"))

        return group

    def _build_sound_row(self, *, kind: str, label: str) -> QWidget:
        """Construct a row with path display, browse button, and enable checkbox."""
        checkbox = QCheckBox(f"Play {label.lower()}")
        checkbox.setChecked(True)
        checkbox.stateChanged.connect(self._schedule_save_ui_settings)
        self._sound_checkboxes[kind] = checkbox

        line_edit = QLineEdit()
        line_edit.setPlaceholderText(f"Select {label.lower()} (mp3 / ogg / wav)")
        line_edit.setReadOnly(True)
        line_edit.setMinimumWidth(480)
        line_edit.textChanged.connect(self._schedule_save_ui_settings)
        self._sound_files[kind] = line_edit

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(lambda: self._browse_sound_file(kind))

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(line_edit, stretch=1)
        layout.addWidget(browse_btn)
        layout.addWidget(checkbox)
        return row

    def _build_display_group(self) -> QGroupBox:
        """Build the display settings group box."""
        group = QGroupBox("Display Settings")
        form = QFormLayout(group)

        # Throttle target slider
        self._throttle_target_slider = QSlider(Qt.Horizontal)
        self._throttle_target_slider.setObjectName("throttleTargetSlider")
        self._throttle_target_slider.setRange(0, 100)
        self._throttle_target_slider.setSingleStep(1)
        self._throttle_target_slider.setPageStep(5)
        self._throttle_target_slider.setTickInterval(10)
        self._throttle_target_slider.setTickPosition(QSlider.TicksBelow)
        self._throttle_target_slider.setValue(_DEFAULT_THROTTLE_TARGET)
        self._throttle_target_slider.valueChanged.connect(self._on_targets_changed_internal)
        self._throttle_target_slider.valueChanged.connect(self._schedule_save_ui_settings)

        self._throttle_target_label = QLabel(f"{_DEFAULT_THROTTLE_TARGET}%")
        self._throttle_target_label.setObjectName("throttleTargetValue")
        self._throttle_target_label.setStyleSheet("color: #22c55e;")
        self._throttle_target_label.setMinimumWidth(52)
        self._throttle_target_slider.valueChanged.connect(
            lambda v: self._throttle_target_label.setText(f"{int(v)}%")
        )

        throttle_row = QWidget()
        throttle_layout = QHBoxLayout(throttle_row)
        throttle_layout.setContentsMargins(0, 0, 0, 0)
        throttle_layout.addWidget(self._throttle_target_slider, stretch=1)
        throttle_layout.addWidget(self._throttle_target_label)

        form.addRow("Throttle target:", throttle_row)

        # Brake target slider
        self._brake_target_slider = QSlider(Qt.Horizontal)
        self._brake_target_slider.setObjectName("brakeTargetSlider")
        self._brake_target_slider.setRange(0, 100)
        self._brake_target_slider.setSingleStep(1)
        self._brake_target_slider.setPageStep(5)
        self._brake_target_slider.setTickInterval(10)
        self._brake_target_slider.setTickPosition(QSlider.TicksBelow)
        self._brake_target_slider.setValue(_DEFAULT_BRAKE_TARGET)
        self._brake_target_slider.valueChanged.connect(self._on_targets_changed_internal)
        self._brake_target_slider.valueChanged.connect(self._schedule_save_ui_settings)

        self._brake_target_label = QLabel(f"{_DEFAULT_BRAKE_TARGET}%")
        self._brake_target_label.setObjectName("brakeTargetValue")
        self._brake_target_label.setStyleSheet("color: #ef4444;")
        self._brake_target_label.setMinimumWidth(52)
        self._brake_target_slider.valueChanged.connect(
            lambda v: self._brake_target_label.setText(f"{int(v)}%")
        )

        brake_row = QWidget()
        brake_layout = QHBoxLayout(brake_row)
        brake_layout.setContentsMargins(0, 0, 0, 0)
        brake_layout.addWidget(self._brake_target_slider, stretch=1)
        brake_layout.addWidget(self._brake_target_label)

        form.addRow("Brake target:", brake_row)

        # Grid step slider (10-50%)
        self._grid_step_slider = QSlider(Qt.Horizontal)
        self._grid_step_slider.setRange(10, 50)
        self._grid_step_slider.setSingleStep(10)
        self._grid_step_slider.setPageStep(10)
        self._grid_step_slider.setTickInterval(10)
        self._grid_step_slider.setTickPosition(QSlider.TicksBelow)
        self._grid_step_slider.setValue(_DEFAULT_GRID_STEP)
        self._grid_step_slider.valueChanged.connect(self._on_grid_step_slider_changed)
        self._grid_step_slider.valueChanged.connect(self._schedule_save_ui_settings)

        self._grid_step_label = QLabel(f"{_DEFAULT_GRID_STEP}%")
        self._grid_step_label.setMinimumWidth(52)

        grid_row = QWidget()
        grid_layout = QHBoxLayout(grid_row)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.addWidget(self._grid_step_slider, stretch=1)
        grid_layout.addWidget(self._grid_step_label)

        form.addRow("Grid division:", grid_row)

        # Update rate slider
        self._update_rate_slider = QSlider(Qt.Horizontal)
        self._update_rate_slider.setRange(30, 120)
        self._update_rate_slider.setSingleStep(10)
        self._update_rate_slider.setPageStep(10)
        self._update_rate_slider.setTickInterval(10)
        self._update_rate_slider.setTickPosition(QSlider.TicksBelow)
        self._update_rate_slider.setValue(60)
        self._update_rate_slider.valueChanged.connect(self._on_update_rate_slider_changed)
        self._update_rate_slider.valueChanged.connect(self._schedule_save_ui_settings)

        self._update_rate_label = QLabel("60 Hz")
        self._update_rate_label.setMinimumWidth(52)

        rate_row = QWidget()
        rate_layout = QHBoxLayout(rate_row)
        rate_layout.setContentsMargins(0, 0, 0, 0)
        rate_layout.addWidget(self._update_rate_slider, stretch=1)
        rate_layout.addWidget(self._update_rate_label)

        form.addRow("Update rate:", rate_row)

        # Show steering checkbox
        self._show_steering_checkbox = QCheckBox("Show steering trace")
        self._show_steering_checkbox.setChecked(True)
        self._show_steering_checkbox.stateChanged.connect(self._on_steering_visible_changed_internal)
        self._show_steering_checkbox.stateChanged.connect(self._schedule_save_ui_settings)
        form.addRow("", self._show_steering_checkbox)

        return group

    # -------------------------------------------------------------------------
    # Device management
    # -------------------------------------------------------------------------

    def refresh_devices(self) -> None:
        """Refresh the list of available HID devices."""
        if not hid_available():
            self._set_status("hidapi not available. Install hidapi to enable device selection.")
            return

        self._devices = enumerate_devices()
        self._populate_device_combo(self._pedals_device_combo, self._devices, "(none)")
        self._populate_device_combo(self._wheel_device_combo, self._devices, "(none)")
        self._set_status(f"Found {len(self._devices)} HID device(s).")

    def _populate_device_combo(
        self, combo: QComboBox, devices: list[HidDeviceInfo], placeholder: str
    ) -> None:
        """Populate a device combo box with available devices."""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(placeholder, None)
        for idx, dev in enumerate(devices):
            label = f"{dev.product_string} (VID:{dev.device_id.vendor_id:04x} PID:{dev.device_id.product_id:04x})"
            combo.addItem(label, idx)
        combo.blockSignals(False)

    def apply_device_selection(self) -> None:
        """Open/close HID sessions based on current combo selections."""
        # Close existing sessions
        self._pedals_session.close()
        self._wheel_session.close()

        # Open pedals session
        pedals_idx = self._pedals_device_combo.currentData()
        if pedals_idx is not None and pedals_idx < len(self._devices):
            try:
                self._pedals_device = self._devices[pedals_idx]
                self._pedals_session.open(self._pedals_device)
                self._set_status(f"Pedals connected: {self._pedals_device_combo.currentText()}")
            except Exception as e:
                self._set_status(f"Failed to open pedals: {e}")
                self._pedals_device = None

        # Open wheel session
        wheel_idx = self._wheel_device_combo.currentData()
        if wheel_idx is not None and wheel_idx < len(self._devices):
            try:
                self._wheel_device = self._devices[wheel_idx]
                self._wheel_session.open(self._wheel_device)
                self._set_status(f"Wheel connected: {self._wheel_device_combo.currentText()}")
            except Exception as e:
                self._set_status(f"Failed to open wheel: {e}")
                self._wheel_device = None

        if pedals_idx is None and wheel_idx is None:
            self._set_status("No devices selected. Running in simulator mode.")

    def save_current_mapping(self) -> None:
        """Persist the current device configuration to config.ini."""
        pedals_cfg = None
        wheel_cfg = None
        
        if self._pedals_device:
            pedals_cfg = PedalsConfig(
                vendor_id=self._pedals_device.device_id.vendor_id,
                product_id=self._pedals_device.device_id.product_id,
                product_string=self._pedals_device.product_string,
                report_len=self._pedals_report_len.value(),
                throttle_offset=self._throttle_offset.value(),
                brake_offset=self._brake_offset.value(),
            )
        
        if self._wheel_device:
            wheel_cfg = WheelConfig(
                vendor_id=self._wheel_device.device_id.vendor_id,
                product_id=self._wheel_device.device_id.product_id,
                product_string=self._wheel_device.product_string,
                report_len=self._wheel_report_len.value(),
                steering_offset=self._steering_offset.value(),
                steering_center=self._steering_center,
                steering_range=self._steering_range,
            )
        
        save_input_profile(InputProfile(pedals=pedals_cfg, wheel=wheel_cfg, ui=None))
        self._set_status("Device configuration saved to config.ini.")

    def _load_persisted_config(self) -> None:
        """Load persisted device and UI configuration on startup."""
        self.refresh_devices()

        # Load device config
        try:
            profile = load_input_profile()
            self._apply_device_config(profile)
        except Exception:
            pass

    def _apply_device_config(self, profile: InputProfile) -> None:
        """Apply a loaded device configuration to UI controls."""
        pedals_cfg = profile.pedals
        wheel_cfg = profile.wheel
        
        # Pedals
        if pedals_cfg:
            self._pedals_report_len.setValue(pedals_cfg.report_len)
            self._throttle_offset.setValue(pedals_cfg.throttle_offset)
            self._brake_offset.setValue(pedals_cfg.brake_offset)
            self._select_device_by_vid_pid(
                self._pedals_device_combo, pedals_cfg.vendor_id, pedals_cfg.product_id
            )

        # Wheel
        if wheel_cfg:
            self._wheel_report_len.setValue(wheel_cfg.report_len)
            self._steering_offset.setValue(wheel_cfg.steering_offset)
            self._steering_center = wheel_cfg.steering_center
            self._steering_center_value_label.setText(str(wheel_cfg.steering_center))
            # Clamp steering range to slider bounds (180-1080 degrees)
            clamped_range = max(180, min(1080, wheel_cfg.steering_range))
            self._steering_range = clamped_range
            self._steering_range_slider.setValue(clamped_range)
            self._select_device_by_vid_pid(
                self._wheel_device_combo, wheel_cfg.vendor_id, wheel_cfg.product_id
            )

        self._update_steering_calibration_label()

        # Auto-apply if devices found
        if pedals_cfg or wheel_cfg:
            self.apply_device_selection()

    def _select_device_by_vid_pid(
        self, combo: QComboBox, vid: int, pid: int
    ) -> None:
        """Select a device in the combo by VID/PID match."""
        if vid == 0 and pid == 0:
            return
        for i in range(combo.count()):
            idx = combo.itemData(i)
            if idx is not None and idx < len(self._devices):
                dev = self._devices[idx]
                if dev.device_id.vendor_id == vid and dev.device_id.product_id == pid:
                    combo.setCurrentIndex(i)
                    return

    # -------------------------------------------------------------------------
    # Calibration methods
    # -------------------------------------------------------------------------

    def start_calibration(
        self,
        device: str,
        axis: str,
        *,
        on_complete: Callable[[str, int, float], None] | None = None,
    ) -> None:
        """Start the calibration procedure for a given axis.

        Args:
            device: Either 'pedals' or 'wheel'.
            axis: The axis name (e.g., 'throttle', 'brake', 'steering').
            on_complete: Callback invoked with (axis, offset, score) when done.
        """
        session = self._pedals_session if device == "pedals" else self._wheel_session
        if not session.is_open:
            self._set_status(f"Cannot calibrate {axis}: {device} device not connected.")
            return

        self._calibration_device = device
        self._calibration_axis = axis
        self._calibration_callback = on_complete
        self._baseline_samples = []
        self._active_samples = []

        self._set_status(f"Calibrating {axis}: release all pedals/wheel for 2 seconds...")
        self._calibration_timer.start()
        QTimer.singleShot(_CALIBRATION_DURATION_MS, self._switch_to_active_capture)

    def _switch_to_active_capture(self) -> None:
        """Transition from baseline capture to active capture."""
        self._set_status(
            f"Now press/move the {self._calibration_axis} input for 2 seconds..."
        )
        QTimer.singleShot(_CALIBRATION_DURATION_MS, self._finish_calibration)

    def _finish_calibration(self) -> None:
        """Complete calibration and compute the best offset."""
        self._calibration_timer.stop()

        axis = self._calibration_axis
        device = self._calibration_device
        callback = self._calibration_callback

        self._calibration_device = None
        self._calibration_axis = None
        self._calibration_callback = None

        if not self._baseline_samples or not self._active_samples:
            self._set_status(f"{axis} calibration failed: not enough samples.")
            return

        offset, score = self._compute_best_offset(
            self._baseline_samples, self._active_samples
        )

        # Apply the detected offset
        if device == "pedals":
            if axis == "throttle":
                self._throttle_offset.setValue(offset)
            elif axis == "brake":
                self._brake_offset.setValue(offset)
        elif device == "wheel" and axis == "steering":
            self._steering_offset.setValue(offset)

        self._set_status(
            f"{axis.capitalize()} offset detected at byte {offset} (score: {score:.1f})."
        )

        if callback:
            callback(axis, offset, score)

    def _capture_calibration_sample(self) -> None:
        """Capture a single calibration sample from the active device."""
        session = (
            self._pedals_session
            if self._calibration_device == "pedals"
            else self._wheel_session
        )
        if not session.is_open:
            return

        report_len = (
            self._pedals_report_len.value()
            if self._calibration_device == "pedals"
            else self._wheel_report_len.value()
        )
        report = session.read_latest_report(
            report_len=report_len, max_reads=_MAX_READS_PER_TICK
        )
        if report is None:
            return

        # First phase: baseline; second phase: active
        if self._active_samples:
            self._active_samples.append(report)
        else:
            self._baseline_samples.append(report)

    def _compute_best_offset(
        self, baseline: list[bytes], active: list[bytes]
    ) -> tuple[int, float]:
        """Find the byte offset with the largest variance difference.

        Returns:
            A tuple of (best_offset, score).
        """
        if not baseline or not active:
            return (0, 0.0)

        min_len = min(len(b) for b in baseline + active)
        best_offset = 0
        best_score = 0.0

        for offset in range(min_len):
            baseline_vals = [b[offset] for b in baseline]
            active_vals = [a[offset] for a in active]

            baseline_var = self._variance(baseline_vals)
            active_var = self._variance(active_vals)

            # Score is how much more variance exists in active vs baseline
            score = active_var - baseline_var
            if score > best_score:
                best_score = score
                best_offset = offset

        return (best_offset, best_score)

    @staticmethod
    def _variance(values: list[int]) -> float:
        """Compute the variance of a list of integers."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / len(values)

    def _start_pedal_offset_wizard(self) -> None:
        """Run a two-step wizard to auto-detect throttle/brake offsets."""
        if not self._pedals_session.is_open:
            self._set_status("Select a pedals HID device first.")
            return
        if self._calibration_device or self._calibration_axis:
            self._set_status("Calibration already running. Please wait.")
            return

        self._pending_pedal_wizard = ["throttle", "brake"]
        self._set_status("Auto-detecting pedal offsets: keep pedals released...")
        self._run_next_pedal_wizard_step()

    def _run_next_pedal_wizard_step(self) -> None:
        """Execute the next step in the pedal calibration wizard."""
        if not self._pending_pedal_wizard:
            self._set_status("Pedal offsets detected. Click Save to persist.")
            try:
                self.save_current_mapping()
            except Exception:
                pass
            return

        axis = self._pending_pedal_wizard.pop(0)
        self._set_status(
            f"Calibrating {axis}: keep the other pedal released. Press and hold when prompted."
        )
        self.start_calibration(
            "pedals", axis, on_complete=self._on_pedal_wizard_step_complete
        )

    def _on_pedal_wizard_step_complete(
        self, axis: str, offset: int, score: float
    ) -> None:
        """Handle completion of a single pedal wizard step."""
        self._set_status(
            f"{axis.capitalize()} offset detected at byte {offset} (score {score:.1f})."
        )
        QTimer.singleShot(300, self._run_next_pedal_wizard_step)

    # -------------------------------------------------------------------------
    # Steering calibration
    # -------------------------------------------------------------------------

    def calibrate_steering_range(self) -> None:
        """Calibrate steering center/range (for different wheel rotation angles)."""
        if not self._wheel_session.is_open:
            self._set_status("Select a wheel HID device first.")
            return
        if self._steering_offset.value() >= self._wheel_report_len.value():
            self._set_status("Adjust steering offset/length first.")
            return

        self._steering_center_samples = []
        self._steering_left_samples = []
        self._steering_right_samples = []
        self._steering_pending_stage = "center"

        dlg = QDialog(self)
        dlg.setWindowTitle("Steering Calibration")
        label = QLabel("Step 1 of 3: Leave wheel centered.\nClick Start when ready.")
        label.setWordWrap(True)
        start_btn = QPushButton("Start")
        cancel_btn = QPushButton("Cancel")
        start_btn.clicked.connect(self._start_pending_steering_stage)
        cancel_btn.clicked.connect(lambda: self._cancel_steering_calibration(dialog=dlg))

        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(start_btn)
        btns.addWidget(cancel_btn)

        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addLayout(btns)
        dlg.setLayout(layout)

        self._steering_cal_dialog = dlg
        self._steering_cal_label = label
        self._steering_cal_start_btn = start_btn
        self._steering_cal_dialog.show()

    def _start_pending_steering_stage(self) -> None:
        """Begin capture for the current pending stage (center/left/right)."""
        stage = self._steering_pending_stage
        if not stage:
            return

        self._steering_cal_stage = stage
        stage_texts = {
            "center": "Capturing center... keep wheel still for 3s.",
            "left": "Capturing full left... hold for 3s.",
            "right": "Capturing full right... hold for 3s.",
        }

        if stage == "center":
            self._steering_center_samples = []
        elif stage == "left":
            self._steering_left_samples = []
        else:
            self._steering_right_samples = []

        self._set_steering_dialog_text(stage_texts.get(stage, ""))
        if self._steering_cal_start_btn:
            self._steering_cal_start_btn.setEnabled(False)

        self._steering_cal_timer.start(20)
        QTimer.singleShot(_STEERING_CAPTURE_MS, self._complete_steering_stage)

    def _set_steering_dialog_text(self, text: str) -> None:
        """Update the steering calibration dialog text."""
        if self._steering_cal_label:
            self._steering_cal_label.setText(text)

    def _complete_steering_stage(self) -> None:
        """Stop current stage and advance to next step or finish."""
        self._steering_cal_timer.stop()
        stage = self._steering_cal_stage
        self._steering_cal_stage = None

        if stage == "center":
            self._steering_pending_stage = "left"
            self._set_steering_dialog_text(
                "Step 2 of 3: Turn wheel full left. Click Start when ready."
            )
        elif stage == "left":
            self._steering_pending_stage = "right"
            self._set_steering_dialog_text(
                "Step 3 of 3: Turn wheel full right. Click Start when ready."
            )
        elif stage == "right":
            self._steering_pending_stage = None
            self._finish_steering_range_calibration()
            self._close_steering_cal_dialog()
            return

        if self._steering_cal_start_btn:
            self._steering_cal_start_btn.setEnabled(True)

    def _cancel_steering_calibration(self, dialog: QDialog | None = None) -> None:
        """Abort steering calibration and cleanup dialog/timers."""
        self._steering_cal_timer.stop()
        self._steering_pending_stage = None
        self._steering_cal_stage = None
        self._close_steering_cal_dialog(dialog)
        self._set_status("Steering calibration canceled.")

    def _close_steering_cal_dialog(self, dialog: QDialog | None = None) -> None:
        """Close and clean up the steering calibration dialog."""
        dlg = dialog or self._steering_cal_dialog
        if dlg is not None:
            try:
                dlg.close()
            except Exception:
                pass
        self._steering_cal_dialog = None
        self._steering_cal_label = None
        self._steering_cal_start_btn = None

    def _capture_steering_calibration_sample(self) -> None:
        """Capture a steering sample during calibration."""
        if not self._wheel_session.is_open or not self._steering_cal_stage:
            return

        report = self._wheel_session.read_latest_report(
            report_len=self._wheel_report_len.value(),
            max_reads=_MAX_READS_PER_TICK,
        )
        if not report:
            return

        s_off = self._steering_offset.value()
        if s_off >= len(report):
            return

        value = int(report[s_off])
        if self._steering_cal_stage == "center":
            self._steering_center_samples.append(value)
        elif self._steering_cal_stage == "left":
            self._steering_left_samples.append(value)
        elif self._steering_cal_stage == "right":
            self._steering_right_samples.append(value)

    def _finish_steering_range_calibration(self) -> None:
        """Complete steering range calibration and save results."""
        self._steering_cal_timer.stop()
        self._steering_cal_stage = None

        if not self._steering_center_samples or not (
            self._steering_left_samples or self._steering_right_samples
        ):
            self._set_status("Steering calibration failed: not enough data.")
            return

        center = int(
            sum(self._steering_center_samples)
            / max(1, len(self._steering_center_samples))
        )

        self._steering_center = center
        self._steering_center_value_label.setText(str(center))
        self._update_steering_calibration_label()

        try:
            self.save_current_mapping()
            self._set_status(
                f"Steering calibrated: center={center}. Saved to config.ini."
            )
        except Exception:
            self._set_status(
                f"Steering calibrated: center={center}. Click Save to persist."
            )

    def _update_steering_calibration_label(self) -> None:
        """Refresh the steering center/range label in settings."""
        if hasattr(self, "_steering_center_label"):
            self._steering_center_label.setText(
                f"Center: {int(self._steering_center)} | Rotation: {int(self._steering_range)}°"
            )

    def _set_steering_center_from_wheel(self) -> None:
        """Read current steering position from wheel and set as center."""
        if not self._wheel_session.is_open:
            self._set_status("Wheel not connected. Apply device selection first.")
            return

        report = self._wheel_session.read_latest_report(
            report_len=self._wheel_report_len.value(),
            max_reads=_MAX_READS_PER_TICK,
        )
        if not report:
            self._set_status("Could not read from wheel. Try again.")
            return

        s_off = self._steering_offset.value()
        if s_off >= len(report):
            self._set_status("Steering offset out of range.")
            return

        center = int(report[s_off])
        self._steering_center = center
        self._steering_center_value_label.setText(str(center))
        self._update_steering_calibration_label()

        try:
            self.save_current_mapping()
            self._set_status(f"Steering center set to {center}. Saved.")
        except Exception:
            self._set_status(f"Steering center set to {center}. Click Save to persist.")

    def _on_steering_range_changed(self, value: int) -> None:
        """Handle steering range slider changes (wheel rotation degrees)."""
        self._steering_range = value
        self._update_steering_calibration_label()
        try:
            self.save_current_mapping()
        except Exception:
            pass  # Will be saved on next manual save

    # -------------------------------------------------------------------------
    # Sound management
    # -------------------------------------------------------------------------

    def sound_enabled(self, kind: str) -> bool:
        """Return whether a given target sound is enabled."""
        checkbox = self._sound_checkboxes.get(kind)
        return checkbox.isChecked() if checkbox else False

    def resolve_sound_path(self, kind: str) -> str:
        """Get the stored sound path, falling back to the default."""
        line_edit = self._sound_files.get(kind)
        if line_edit:
            return line_edit.text().strip() or str(self._default_sound_path)
        return str(self._default_sound_path)

    def play_target_sound(self, kind: str) -> None:
        """Play the selected sound for the given target if the file looks valid."""
        path = Path(self.resolve_sound_path(kind))
        if not path.exists() or path.suffix.lower() not in {".mp3", ".wav", ".ogg"}:
            return

        try:
            self._media_player.stop()
            self._media_player.setSource(QUrl.fromLocalFile(str(path)))
            self._audio_output.setVolume(1.0)
            self._media_player.play()
        except Exception:
            pass

    def _browse_sound_file(self, kind: str) -> None:
        """Open a file dialog to choose a sound file for throttle/brake targets."""
        start_dir = Path(self.resolve_sound_path(kind)).expanduser().parent
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {kind} target sound",
            str(start_dir),
            "Audio Files (*.mp3 *.wav *.ogg);;All Files (*.*)",
        )
        if file_path:
            self._set_sound_file(kind, file_path, trigger_save=True)

    def _set_sound_file(
        self, kind: str, path: Path | str, *, trigger_save: bool
    ) -> None:
        """Update the line edit for a sound file and optionally persist."""
        path = Path(path).expanduser()
        line_edit = self._sound_files.get(kind)
        if line_edit:
            line_edit.blockSignals(True)
            line_edit.setText(str(path))
            line_edit.blockSignals(False)
        if trigger_save:
            self._schedule_save_ui_settings()

    def apply_sound_settings(
        self,
        *,
        throttle_enabled: bool,
        throttle_path: str | None,
        brake_enabled: bool,
        brake_path: str | None,
    ) -> None:
        """Apply persisted sound enable/path settings to UI controls."""
        self._sound_checkboxes["throttle"].setChecked(throttle_enabled)
        self._sound_checkboxes["brake"].setChecked(brake_enabled)
        self._set_sound_file(
            "throttle", throttle_path or self._default_sound_path, trigger_save=False
        )
        self._set_sound_file(
            "brake", brake_path or self._default_sound_path, trigger_save=False
        )

    # -------------------------------------------------------------------------
    # Display settings callbacks
    # -------------------------------------------------------------------------

    def _on_update_rate_slider_changed(self, hz: int) -> None:
        """Handle update rate slider changes."""
        # Snap to 10 Hz increments
        hz = max(30, min(120, (hz // 10) * 10))
        if hz != self._update_rate_slider.value():
            self._update_rate_slider.blockSignals(True)
            self._update_rate_slider.setValue(hz)
            self._update_rate_slider.blockSignals(False)
        self._update_rate_label.setText(f"{hz} Hz")
        self._on_update_rate_changed(hz)

    def _on_steering_visible_changed_internal(self, state: int) -> None:
        """Handle steering visibility checkbox changes."""
        visible = state == Qt.Checked.value
        self._on_steering_visible_changed(visible)

    def _on_targets_changed_internal(self) -> None:
        """Handle throttle/brake target slider changes."""
        self._on_targets_changed()

    def _on_grid_step_slider_changed(self, value: int) -> None:
        """Handle grid step slider changes."""
        # Snap to 10% increments
        step = max(10, min(50, (value // 10) * 10))
        if step != value:
            self._grid_step_slider.blockSignals(True)
            self._grid_step_slider.setValue(step)
            self._grid_step_slider.blockSignals(False)
        self._grid_step_label.setText(f"{step}%")
        self._on_grid_step_changed(step)

    def set_update_rate(self, hz: int, *, update_slider: bool = False) -> None:
        """Set the update rate and optionally sync the slider."""
        hz = clamp_int(hz, 30, 120)
        if update_slider:
            self._update_rate_slider.blockSignals(True)
            self._update_rate_slider.setValue(hz)
            self._update_rate_slider.blockSignals(False)
        self._update_rate_label.setText(f"{hz} Hz")

    def set_show_steering(self, visible: bool, *, update_checkbox: bool = False) -> None:
        """Set steering visibility and optionally sync the checkbox."""
        if update_checkbox:
            self._show_steering_checkbox.blockSignals(True)
            self._show_steering_checkbox.setChecked(visible)
            self._show_steering_checkbox.blockSignals(False)

    def set_throttle_target(self, value: int) -> None:
        """Set the throttle target percentage."""
        value = clamp_int(value, 0, 100)
        self._throttle_target_slider.blockSignals(True)
        self._throttle_target_slider.setValue(value)
        self._throttle_target_slider.blockSignals(False)
        self._throttle_target_label.setText(f"{value}%")

    def set_brake_target(self, value: int) -> None:
        """Set the brake target percentage."""
        value = clamp_int(value, 0, 100)
        self._brake_target_slider.blockSignals(True)
        self._brake_target_slider.setValue(value)
        self._brake_target_slider.blockSignals(False)
        self._brake_target_label.setText(f"{value}%")

    def set_grid_step(self, step_percent: int) -> None:
        """Set the grid step percentage."""
        step = max(10, min(50, (step_percent // 10) * 10))
        self._grid_step_slider.blockSignals(True)
        self._grid_step_slider.setValue(step)
        self._grid_step_slider.blockSignals(False)
        self._grid_step_label.setText(f"{step}%")

    # -------------------------------------------------------------------------
    # UI settings persistence
    # -------------------------------------------------------------------------

    def _schedule_save_ui_settings(self) -> None:
        """Debounce UI settings save to avoid excessive writes."""
        self._ui_save_timer.start(_UI_SAVE_DEBOUNCE_MS)

    def _save_ui_settings(self) -> None:
        """Persist UI-related settings (targets, grid, sounds, update rate, steering visibility)."""
        cfg = UiConfig(
            throttle_target=self._throttle_target_slider.value(),
            brake_target=self._brake_target_slider.value(),
            grid_step_percent=self._grid_step_slider.value(),
            update_hz=self._update_rate_slider.value(),
            show_steering=self._show_steering_checkbox.isChecked(),
            throttle_sound_enabled=self.sound_enabled("throttle"),
            throttle_sound_path=self.resolve_sound_path("throttle"),
            brake_sound_enabled=self.sound_enabled("brake"),
            brake_sound_path=self.resolve_sound_path("brake"),
        )
        save_ui_config(cfg)

    # -------------------------------------------------------------------------
    # Status helper
    # -------------------------------------------------------------------------

    def _set_status(self, message: str) -> None:
        """Update the status label and notify the callback."""
        self._device_status.setText(message)
        self._on_status_update(message)

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    def close_sessions(self) -> None:
        """Close all HID sessions (call on application exit)."""
        self._pedals_session.close()
        self._wheel_session.close()
