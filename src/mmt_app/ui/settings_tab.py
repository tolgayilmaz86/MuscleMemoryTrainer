"""Settings tab for device configuration, calibration, and sound settings.

This module provides a centralized settings interface following the Single
Responsibility Principle - all device/calibration/sound configuration
lives here, separate from the main window orchestration.
"""

from __future__ import annotations

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
    DEFAULT_PEDALS_REPORT_LEN,
    DEFAULT_WHEEL_REPORT_LEN,
    DEFAULT_THROTTLE_OFFSET,
    DEFAULT_BRAKE_OFFSET,
    DEFAULT_STEERING_OFFSET,
    DEFAULT_STEERING_CENTER,
    DEFAULT_STEERING_RANGE,
    DEFAULT_STEERING_HALF_RANGE,
    DEFAULT_STEERING_16BIT,
    DEFAULT_THROTTLE_TARGET,
    DEFAULT_BRAKE_TARGET,
    DEFAULT_GRID_STEP_PERCENT,
    DEFAULT_UPDATE_HZ,
    DEFAULT_SHOW_STEERING,
    DEFAULT_SHOW_WATERMARK,
)
from mmt_app.input.hid_backend import HidSession, HidDeviceInfo, hid_available, enumerate_devices
from mmt_app.input.calibration import (
    CalibrationState,
    SteeringCalibrationState,
    compute_best_offset,
    variance,
    detect_report_length,
    read_steering_value,
    CALIBRATION_DURATION_MS,
    STEERING_CAPTURE_MS,
    MAX_READS_PER_TICK,
)
from mmt_app.input.device_mgr import (
    DeviceManager,
    format_device_label,
)
from mmt_app.embedded_sound import get_embedded_sound_path
from mmt_app.ui.utils import clamp_int

if TYPE_CHECKING:
    from mmt_app.telemetry import TelemetrySample

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_UI_SAVE_DEBOUNCE_MS: int = 500
"""Debounce interval (ms) for persisting UI settings."""


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

        # Callbacks for MainWindow integration
        self._on_status_update = on_status_update or (lambda _: None)
        self._on_targets_changed = on_targets_changed or (lambda: None)
        self._on_grid_step_changed = on_grid_step_changed or (lambda _: None)
        self._on_update_rate_changed = on_update_rate_changed or (lambda _: None)
        self._on_steering_visible_changed = on_steering_visible_changed or (lambda _: None)
        self._on_watermark_visible_changed = on_watermark_visible_changed or (lambda _: None)

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
    def steering_16bit(self) -> bool:
        """Return whether 16-bit steering mode is enabled."""
        return self._steering_16bit.isChecked()

    @property
    def steering_center(self) -> int:
        """Return the calibrated steering center value."""
        return self._steering_center

    @property
    def steering_range(self) -> int:
        """Return the calibrated steering range value (wheel rotation degrees)."""
        return self._steering_range

    @property
    def steering_half_range(self) -> int:
        """Return the calibrated steering half-range (raw value from center to full lock)."""
        return self._steering_half_range

    @property
    def update_rate(self) -> int:
        """Return the configured update rate in Hz."""
        return self._update_rate_slider.value()

    @property
    def show_steering(self) -> bool:
        """Return whether steering trace should be visible."""
        return self._show_steering_checkbox.isChecked()

    @property
    def show_watermark(self) -> bool:
        """Return whether watermark should be visible on charts."""
        return self._show_watermark_checkbox.isChecked()

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
        self._calibration_state = CalibrationState()
        self._pending_pedal_wizard: list[str] = []
        # Active calibration tracking
        self._calibration_device: str | None = None
        self._calibration_axis: str | None = None
        self._calibration_callback: Callable | None = None
        self._calibration_phase: str = "baseline"  # "baseline" or "active"
        # Setup wizard state
        self._setup_wizard_dialog: QDialog | None = None
        self._setup_wizard_label: QLabel | None = None
        self._setup_wizard_step: int = 0
        self._setup_wizard_steps: list[dict] = []

    def _init_steering_state(self) -> None:
        """Initialize steering calibration state variables."""
        self._steering_center: int = DEFAULT_STEERING_CENTER
        self._steering_range: int = DEFAULT_STEERING_RANGE
        self._steering_half_range: int = DEFAULT_STEERING_HALF_RANGE
        self._steering_state = SteeringCalibrationState(
            center=DEFAULT_STEERING_CENTER,
            range_degrees=DEFAULT_STEERING_RANGE,
        )
        self._steering_cal_dialog: QDialog | None = None
        self._steering_cal_label: QLabel | None = None
        self._steering_cal_start_btn: QPushButton | None = None

    def _init_sound_state(self) -> None:
        """Initialize sound playback state variables."""
        self._default_sound_path = get_embedded_sound_path()
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

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_current_mapping)
        btn_row.addWidget(save_btn)

        btn_row.addStretch()

        layout.addLayout(btn_row)

    def _build_device_group(self) -> QGroupBox:
        """Build the device selection group box."""
        group = QGroupBox("Device Selection")
        form = QFormLayout(group)

        # Pedals device combo
        self._pedals_device_combo = QComboBox()
        self._pedals_device_combo.setMinimumWidth(280)
        form.addRow("Pedals HID:", self._pedals_device_combo)

        # Wheel device combo
        self._wheel_device_combo = QComboBox()
        self._wheel_device_combo.setMinimumWidth(280)
        form.addRow("Wheel HID:", self._wheel_device_combo)

        # Button row: Refresh and Connect
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_devices)
        btn_layout.addWidget(refresh_btn)

        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self.connect_devices)
        btn_layout.addWidget(connect_btn)

        btn_layout.addStretch()

        form.addRow("", btn_row)

        return group

    def _build_calibration_group(self) -> QGroupBox:
        """Build the calibration settings group box."""
        group = QGroupBox("Calibration")
        layout = QVBoxLayout(group)

        # Setup wizard and set center buttons - prominent at top
        wizard_row = QWidget()
        wizard_layout = QHBoxLayout(wizard_row)
        wizard_layout.setContentsMargins(0, 0, 0, 0)

        setup_wizard_btn = QPushButton("🔧 Input Setup Wizard")
        setup_wizard_btn.setToolTip("Auto-detect pedal and wheel settings - recommended for first-time setup")
        setup_wizard_btn.clicked.connect(self._start_input_setup_wizard)
        setup_wizard_btn.setMinimumHeight(32)

        calibrate_steering_btn = QPushButton("🔄 Calibrate Steering")
        calibrate_steering_btn.setToolTip("Full calibration: turn wheel fully left, then right to find center")
        calibrate_steering_btn.clicked.connect(self.calibrate_steering_range)
        calibrate_steering_btn.setMinimumHeight(32)

        wizard_layout.addWidget(setup_wizard_btn)
        wizard_layout.addWidget(calibrate_steering_btn)
        wizard_layout.addStretch()
        layout.addWidget(wizard_row)

        # User-friendly settings
        form = QFormLayout()
        layout.addLayout(form)

        # Steering range slider (degrees of wheel rotation)
        self._steering_range_slider = QSlider(Qt.Horizontal)
        self._steering_range_slider.setObjectName("steeringRangeSlider")
        self._steering_range_slider.setRange(180, 1080)
        self._steering_range_slider.setSingleStep(10)
        self._steering_range_slider.setPageStep(90)
        self._steering_range_slider.setTickInterval(90)
        self._steering_range_slider.setTickPosition(QSlider.TicksBelow)
        self._steering_range_slider.setValue(DEFAULT_STEERING_RANGE)
        self._steering_range_slider.valueChanged.connect(self._on_steering_range_changed)

        self._steering_range_label = QLabel(f"{DEFAULT_STEERING_RANGE}°")
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

        # Advanced settings (collapsible)
        self._advanced_checkbox = QCheckBox("Show advanced settings")
        self._advanced_checkbox.setChecked(False)
        self._advanced_checkbox.stateChanged.connect(self._toggle_advanced_settings)
        layout.addWidget(self._advanced_checkbox)

        self._advanced_widget = QWidget()
        advanced_form = QFormLayout(self._advanced_widget)
        advanced_form.setContentsMargins(0, 0, 0, 0)

        # Pedals report length
        self._pedals_report_len = QSpinBox()
        self._pedals_report_len.setRange(1, 64)
        self._pedals_report_len.setValue(DEFAULT_PEDALS_REPORT_LEN)
        advanced_form.addRow("Pedals report length:", self._pedals_report_len)

        # Wheel report length
        self._wheel_report_len = QSpinBox()
        self._wheel_report_len.setRange(1, 64)
        self._wheel_report_len.setValue(DEFAULT_WHEEL_REPORT_LEN)
        advanced_form.addRow("Wheel report length:", self._wheel_report_len)

        # Throttle offset
        self._throttle_offset = QSpinBox()
        self._throttle_offset.setRange(0, 63)
        self._throttle_offset.setValue(DEFAULT_THROTTLE_OFFSET)
        advanced_form.addRow("Throttle byte offset:", self._throttle_offset)

        # Brake offset
        self._brake_offset = QSpinBox()
        self._brake_offset.setRange(0, 63)
        self._brake_offset.setValue(DEFAULT_BRAKE_OFFSET)
        advanced_form.addRow("Brake byte offset:", self._brake_offset)

        # Steering offset
        self._steering_offset = QSpinBox()
        self._steering_offset.setRange(0, 63)
        self._steering_offset.setValue(DEFAULT_STEERING_OFFSET)
        advanced_form.addRow("Steering byte offset:", self._steering_offset)

        # Steering 16-bit mode
        self._steering_16bit = QCheckBox("16-bit steering (2 bytes, little-endian)")
        self._steering_16bit.setChecked(DEFAULT_STEERING_16BIT)
        self._steering_16bit.setToolTip(
            "Enable if your wheel uses 16-bit steering values (most racing wheels do).\n"
            "When enabled, reads 2 bytes starting at the steering offset."
        )
        advanced_form.addRow("", self._steering_16bit)

        self._advanced_widget.setVisible(False)
        layout.addWidget(self._advanced_widget)

        return group

    def _toggle_advanced_settings(self, state: int) -> None:
        """Toggle visibility of advanced calibration settings."""
        self._advanced_widget.setVisible(state == Qt.Checked.value)

    def _build_sound_group(self) -> QGroupBox:
        """Build the sound settings group box."""
        group = QGroupBox("Target Sounds")
        form = QFormLayout(group)

        form.addRow("Throttle:  ", self._build_sound_row(kind="throttle", label="Throttle"))
        form.addRow("Brake:", self._build_sound_row(kind="brake", label="Brake"))

        return group

    def _build_sound_row(self, *, kind: str, label: str) -> QWidget:
        """Construct a row with path display, browse button, and enable checkbox."""
        checkbox = QCheckBox("Activate")
        checkbox.setChecked(True)
        checkbox.stateChanged.connect(self._schedule_save_ui_settings)
        self._sound_checkboxes[kind] = checkbox

        line_edit = QLineEdit()
        line_edit.setPlaceholderText(f"Select {label.lower()} (mp3 / ogg / wav)")
        line_edit.setReadOnly(True)
        line_edit.setMinimumWidth(480)
        line_edit.textChanged.connect(self._schedule_save_ui_settings)
        self._sound_files[kind] = line_edit

        browse_btn = QPushButton("📂")
        browse_btn.setToolTip("Browse for sound file")
        browse_btn.setFlat(True)
        browse_btn.setStyleSheet(
            "QPushButton { font-size: 24px; background: transparent; border: none; padding: 0px; }"
            "QPushButton:hover { background: transparent; }"
            "QPushButton:pressed { background: transparent; }"
        )
        browse_btn.setCursor(Qt.PointingHandCursor)
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
        self._throttle_target_slider.setValue(DEFAULT_THROTTLE_TARGET)
        self._throttle_target_slider.valueChanged.connect(self._on_targets_changed_internal)
        self._throttle_target_slider.valueChanged.connect(self._schedule_save_ui_settings)

        self._throttle_target_label = QLabel(f"{DEFAULT_THROTTLE_TARGET}%")
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
        self._brake_target_slider.setValue(DEFAULT_BRAKE_TARGET)
        self._brake_target_slider.valueChanged.connect(self._on_targets_changed_internal)
        self._brake_target_slider.valueChanged.connect(self._schedule_save_ui_settings)

        self._brake_target_label = QLabel(f"{DEFAULT_BRAKE_TARGET}%")
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
        self._grid_step_slider.setValue(DEFAULT_GRID_STEP_PERCENT)
        self._grid_step_slider.valueChanged.connect(self._on_grid_step_slider_changed)
        self._grid_step_slider.valueChanged.connect(self._schedule_save_ui_settings)

        self._grid_step_label = QLabel(f"{DEFAULT_GRID_STEP_PERCENT}%")
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

        # Show watermark checkbox
        self._show_watermark_checkbox = QCheckBox("Show braking watermark on charts")
        self._show_watermark_checkbox.setChecked(True)
        self._show_watermark_checkbox.stateChanged.connect(self._on_watermark_visible_changed_internal)
        self._show_watermark_checkbox.stateChanged.connect(self._schedule_save_ui_settings)
        form.addRow("", self._show_watermark_checkbox)

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

    def connect_devices(self) -> None:
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
        
        # Get pedals device info from connected device or combo selection
        pedals_dev = self._pedals_device
        if not pedals_dev:
            pedals_idx = self._pedals_device_combo.currentData()
            if pedals_idx is not None and pedals_idx < len(self._devices):
                pedals_dev = self._devices[pedals_idx]
        
        if pedals_dev:
            pedals_cfg = PedalsConfig(
                vendor_id=pedals_dev.device_id.vendor_id,
                product_id=pedals_dev.device_id.product_id,
                product_string=pedals_dev.product_string,
                report_len=self._pedals_report_len.value(),
                throttle_offset=self._throttle_offset.value(),
                brake_offset=self._brake_offset.value(),
            )
        
        # Get wheel device info from connected device or combo selection
        wheel_dev = self._wheel_device
        if not wheel_dev:
            wheel_idx = self._wheel_device_combo.currentData()
            if wheel_idx is not None and wheel_idx < len(self._devices):
                wheel_dev = self._devices[wheel_idx]
        
        if wheel_dev:
            wheel_cfg = WheelConfig(
                vendor_id=wheel_dev.device_id.vendor_id,
                product_id=wheel_dev.device_id.product_id,
                product_string=wheel_dev.product_string,
                report_len=self._wheel_report_len.value(),
                steering_offset=self._steering_offset.value(),
                steering_center=self._steering_center,
                steering_range=self._steering_range,
                steering_half_range=self._steering_half_range,
                steering_16bit=self._steering_16bit.isChecked(),
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
            self._steering_16bit.setChecked(wheel_cfg.steering_16bit)
            self._steering_center = wheel_cfg.steering_center
            self._steering_half_range = wheel_cfg.steering_half_range
            # Clamp steering range to slider bounds (180-1080 degrees)
            clamped_range = max(180, min(1080, wheel_cfg.steering_range))
            self._steering_range = clamped_range
            self._steering_range_slider.setValue(clamped_range)
            self._select_device_by_vid_pid(
                self._wheel_device_combo, wheel_cfg.vendor_id, wheel_cfg.product_id
            )

        self._update_steering_calibration_label()

        # Auto-connect if devices found
        if pedals_cfg or wheel_cfg:
            self.connect_devices()

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
        self._calibration_phase = "baseline"
        self._baseline_samples = []
        self._active_samples = []

        self._set_status(f"Calibrating {axis}: keep input RELEASED for 2 seconds...")
        self._calibration_timer.start()
        QTimer.singleShot(CALIBRATION_DURATION_MS, self._switch_to_active_capture)

    def _switch_to_active_capture(self) -> None:
        """Transition from baseline capture to active capture."""
        self._calibration_phase = "active"
        self._set_status(
            f"Now PRESS/MOVE the {self._calibration_axis} for 2 seconds..."
        )
        QTimer.singleShot(CALIBRATION_DURATION_MS, self._finish_calibration)

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
        # Try non-blocking first for devices that send continuous reports
        report = session.read_latest_report(
            report_len=report_len, max_reads=MAX_READS_PER_TICK
        )
        # Fall back to blocking read for devices that only send on change
        if report is None:
            report = session.read_report(report_len=report_len, timeout_ms=15)
        if report is None:
            return

        # Append to correct sample list based on current phase
        if self._calibration_phase == "active":
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
    # Input Setup Wizard
    # -------------------------------------------------------------------------

    def _start_input_setup_wizard(self) -> None:
        """Start the comprehensive input setup wizard."""
        if not self._pedals_session.is_open and not self._wheel_session.is_open:
            self._set_status("Select pedals and/or wheel HID device first, then click Connect.")
            return
        if self._calibration_device or self._calibration_axis:
            self._set_status("Calibration already running. Please wait.")
            return

        # Build wizard steps based on connected devices
        self._setup_wizard_steps = []
        
        if self._pedals_session.is_open:
            self._setup_wizard_steps.append({
                "type": "detect_report_len",
                "device": "pedals",
                "title": "Detecting Pedals",
                "instruction": "Keep all pedals RELEASED.\n\nDetecting report length...",
            })
            self._setup_wizard_steps.append({
                "type": "detect_axis",
                "device": "pedals",
                "axis": "throttle",
                "title": "Throttle Pedal",
                "instruction": "Keep brake RELEASED.\n\nSlowly press and release THROTTLE several times.",
            })
            self._setup_wizard_steps.append({
                "type": "detect_axis",
                "device": "pedals",
                "axis": "brake",
                "title": "Brake Pedal",
                "instruction": "Keep throttle RELEASED.\n\nSlowly press and release BRAKE several times.",
            })

        if self._wheel_session.is_open:
            self._setup_wizard_steps.append({
                "type": "detect_report_len",
                "device": "wheel",
                "title": "Detecting Wheel",
                "instruction": "Keep wheel CENTERED and still.\n\nDetecting report length...",
            })
            self._setup_wizard_steps.append({
                "type": "detect_axis",
                "device": "wheel",
                "axis": "steering",
                "title": "Steering Wheel",
                "instruction": "Slowly turn wheel LEFT and RIGHT several times.\n\nFull rotation not required.",
            })
            self._setup_wizard_steps.append({
                "type": "set_center",
                "device": "wheel",
                "title": "Steering Center",
                "instruction": "Hold wheel perfectly CENTERED.\n\nClick Next when ready.",
            })

        if not self._setup_wizard_steps:
            self._set_status("No devices connected.")
            return

        self._setup_wizard_step = 0
        self._show_setup_wizard_dialog()

    def _show_setup_wizard_dialog(self) -> None:
        """Show or update the setup wizard dialog."""
        if self._setup_wizard_dialog is None:
            self._setup_wizard_dialog = QDialog(self)
            self._setup_wizard_dialog.setWindowTitle("Input Setup Wizard")
            self._setup_wizard_dialog.setModal(True)
            self._setup_wizard_dialog.setMinimumWidth(400)
            self._setup_wizard_dialog.setMinimumHeight(200)

            layout = QVBoxLayout(self._setup_wizard_dialog)

            self._setup_wizard_label = QLabel()
            self._setup_wizard_label.setAlignment(Qt.AlignCenter)
            self._setup_wizard_label.setWordWrap(True)
            self._setup_wizard_label.setStyleSheet("font-size: 14px; padding: 20px;")
            layout.addWidget(self._setup_wizard_label)

            layout.addStretch()

            btn_layout = QHBoxLayout()
            
            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(self._cancel_setup_wizard)
            btn_layout.addWidget(cancel_btn)
            
            btn_layout.addStretch()
            
            self._setup_wizard_next_btn = QPushButton("Next")
            self._setup_wizard_next_btn.clicked.connect(self._advance_setup_wizard)
            btn_layout.addWidget(self._setup_wizard_next_btn)

            layout.addLayout(btn_layout)

            self._setup_wizard_dialog.rejected.connect(self._cancel_setup_wizard)

        self._run_current_wizard_step()
        self._setup_wizard_dialog.show()

    def _run_current_wizard_step(self) -> None:
        """Execute the current wizard step."""
        if self._setup_wizard_step >= len(self._setup_wizard_steps):
            self._finish_setup_wizard()
            return

        step = self._setup_wizard_steps[self._setup_wizard_step]
        step_num = self._setup_wizard_step + 1
        total = len(self._setup_wizard_steps)
        
        self._setup_wizard_dialog.setWindowTitle(
            f"Input Setup Wizard - Step {step_num}/{total}: {step['title']}"
        )
        self._setup_wizard_label.setText(step["instruction"])

        step_type = step["type"]
        
        if step_type == "detect_report_len":
            self._setup_wizard_next_btn.setEnabled(False)
            self._setup_wizard_next_btn.setText("Detecting...")
            QTimer.singleShot(500, lambda: self._detect_report_length(step))
        elif step_type == "detect_axis":
            self._setup_wizard_next_btn.setEnabled(False)
            self._setup_wizard_next_btn.setText("Detecting...")
            self._start_axis_detection(step)
        elif step_type == "set_center":
            self._setup_wizard_next_btn.setEnabled(True)
            self._setup_wizard_next_btn.setText("Next")

    def _detect_report_length(self, step: dict) -> None:
        """Auto-detect the report length for a device."""
        device = step["device"]
        session = self._pedals_session if device == "pedals" else self._wheel_session
        
        if not session.is_open:
            self._setup_wizard_label.setText("Device not connected!")
            QTimer.singleShot(1000, self._advance_setup_wizard)
            return

        # Try reading with max length to see actual report size
        max_len = 64
        samples = []
        for _ in range(20):
            # Try non-blocking first
            report = session.read_latest_report(report_len=max_len, max_reads=5)
            # Fall back to blocking read for devices that only send on change
            if not report:
                report = session.read_report(report_len=max_len, timeout_ms=50)
            if report:
                samples.append(len(report))

        if samples:
            # Use the most common report length
            report_len = max(set(samples), key=samples.count)
            if device == "pedals":
                self._pedals_report_len.setValue(report_len)
            else:
                self._wheel_report_len.setValue(report_len)
            self._setup_wizard_label.setText(
                f"Report length detected: {report_len} bytes\n\nContinuing..."
            )
        else:
            self._setup_wizard_label.setText("Could not detect report length.\nUsing default.")

        QTimer.singleShot(1000, self._advance_setup_wizard)

    def _start_axis_detection(self, step: dict) -> None:
        """Start detecting an axis offset."""
        device = step["device"]
        axis = step["axis"]
        
        self.start_calibration(
            device, axis, on_complete=self._on_wizard_axis_detected
        )

    def _on_wizard_axis_detected(self, axis: str, offset: int, score: float) -> None:
        """Handle axis detection completion in wizard."""
        if score > 100:
            self._setup_wizard_label.setText(
                f"✓ {axis.capitalize()} detected at byte {offset}\n\nContinuing..."
            )
        else:
            self._setup_wizard_label.setText(
                f"⚠ {axis.capitalize()} detected at byte {offset}\n(low confidence - try again if needed)\n\nContinuing..."
            )
        QTimer.singleShot(1500, self._advance_setup_wizard)

    def _advance_setup_wizard(self) -> None:
        """Move to the next wizard step."""
        step = self._setup_wizard_steps[self._setup_wizard_step] if self._setup_wizard_step < len(self._setup_wizard_steps) else None
        
        # Handle set_center step - capture center now
        if step and step["type"] == "set_center":
            self._capture_steering_center_for_wizard()

        self._setup_wizard_step += 1
        self._run_current_wizard_step()

    def _capture_steering_center_for_wizard(self) -> None:
        """Capture steering center position during wizard."""
        if not self._wheel_session.is_open:
            return

        report = self._wheel_session.read_latest_report(
            report_len=self._wheel_report_len.value(),
            max_reads=MAX_READS_PER_TICK,
        )
        if not report:
            return

        s_off = self._steering_offset.value()
        is_16bit = self._steering_16bit.isChecked()
        
        if is_16bit:
            if s_off + 1 >= len(report):
                return
            center = report[s_off] | (report[s_off + 1] << 8)
        else:
            if s_off >= len(report):
                return
            center = int(report[s_off])
        
        self._steering_center = center

    def _finish_setup_wizard(self) -> None:
        """Complete the setup wizard."""
        if self._setup_wizard_dialog:
            self._setup_wizard_dialog.close()
            self._setup_wizard_dialog = None

        try:
            self.save_current_mapping()
            self._set_status("Input setup complete! Settings saved.")
        except Exception:
            self._set_status("Input setup complete! Click Save to persist.")

    def _cancel_setup_wizard(self) -> None:
        """Cancel the setup wizard."""
        self._calibration_timer.stop()
        self._calibration_device = None
        self._calibration_axis = None
        
        if self._setup_wizard_dialog:
            self._setup_wizard_dialog.close()
            self._setup_wizard_dialog = None
        
        self._set_status("Setup wizard canceled.")

    # -------------------------------------------------------------------------
    # Steering calibration
    # -------------------------------------------------------------------------

    def calibrate_steering_range(self) -> None:
        """Calibrate steering center by capturing full left and right positions."""
        if not self._wheel_session.is_open:
            self._set_status("Wheel not connected. Click Connect first.")
            return
        if self._steering_offset.value() >= self._wheel_report_len.value():
            self._set_status("Invalid steering offset. Check advanced settings.")
            return

        self._steering_left_samples = []
        self._steering_right_samples = []
        self._steering_pending_stage = "left"

        dlg = QDialog(self)
        dlg.setWindowTitle("Steering Calibration")
        dlg.setMinimumWidth(350)
        dlg.setMinimumHeight(150)
        dlg.setModal(True)
        
        label = QLabel(
            "Step 1 of 2: Turn wheel fully LEFT and hold.\n\n"
            "Click Start when ready."
        )
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumHeight(80)
        label.setStyleSheet("font-size: 13px; padding: 10px;")
        
        start_btn = QPushButton("Start")
        start_btn.setMinimumWidth(80)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(80)
        start_btn.clicked.connect(self._start_pending_steering_stage)
        cancel_btn.clicked.connect(lambda: self._cancel_steering_calibration(dialog=dlg))

        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(start_btn)
        btns.addWidget(cancel_btn)
        btns.addStretch()

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        layout.addWidget(label)
        layout.addStretch()
        layout.addLayout(btns)
        dlg.setLayout(layout)

        self._steering_cal_dialog = dlg
        self._steering_cal_label = label
        self._steering_cal_start_btn = start_btn
        self._steering_cal_dialog.show()
        self._set_status("Steering calibration started...")

    def _start_pending_steering_stage(self) -> None:
        """Begin capture for the current pending stage (left/right)."""
        stage = self._steering_pending_stage
        if not stage:
            return

        self._steering_cal_stage = stage
        stage_texts = {
            "left": "Capturing full LEFT position...\n\nHold steady for 3 seconds.",
            "right": "Capturing full RIGHT position...\n\nHold steady for 3 seconds.",
        }

        if stage == "left":
            self._steering_left_samples = []
        else:
            self._steering_right_samples = []

        self._set_steering_dialog_text(stage_texts.get(stage, ""))
        if self._steering_cal_start_btn:
            self._steering_cal_start_btn.setEnabled(False)

        self._steering_cal_timer.start(20)
        QTimer.singleShot(STEERING_CAPTURE_MS, self._complete_steering_stage)

    def _set_steering_dialog_text(self, text: str) -> None:
        """Update the steering calibration dialog text."""
        if self._steering_cal_label:
            self._steering_cal_label.setText(text)

    def _complete_steering_stage(self) -> None:
        """Stop current stage and advance to next step or finish."""
        self._steering_cal_timer.stop()
        stage = self._steering_cal_stage
        self._steering_cal_stage = None

        if stage == "left":
            self._steering_pending_stage = "right"
            self._set_steering_dialog_text(
                "Step 2 of 2: Turn wheel fully RIGHT and hold.\n\n"
                "Click Start when ready."
            )
            if self._steering_cal_start_btn:
                self._steering_cal_start_btn.setEnabled(True)
        elif stage == "right":
            self._steering_pending_stage = None
            self._finish_steering_range_calibration()
            self._close_steering_cal_dialog()
            return

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
            max_reads=MAX_READS_PER_TICK,
        )
        if not report:
            return

        s_off = self._steering_offset.value()
        is_16bit = self._steering_16bit.isChecked()
        
        if is_16bit:
            # 16-bit little-endian
            if s_off + 1 >= len(report):
                return
            value = report[s_off] | (report[s_off + 1] << 8)
        else:
            # 8-bit
            if s_off >= len(report):
                return
            value = int(report[s_off])
        
        if self._steering_cal_stage == "left":
            self._steering_left_samples.append(value)
        elif self._steering_cal_stage == "right":
            self._steering_right_samples.append(value)

    def _finish_steering_range_calibration(self) -> None:
        """Complete steering calibration by computing center and half-range from left/right extremes."""
        self._steering_cal_timer.stop()
        self._steering_cal_stage = None

        if not self._steering_left_samples or not self._steering_right_samples:
            self._set_status("Calibration failed: not enough data captured.")
            return

        # Get average of left and right positions
        left_avg = sum(self._steering_left_samples) / len(self._steering_left_samples)
        right_avg = sum(self._steering_right_samples) / len(self._steering_right_samples)
        
        # Center is midpoint between left and right extremes
        center = int((left_avg + right_avg) / 2)
        
        # Half-range is the distance from center to either extreme
        # Use the average of both sides in case they're slightly asymmetric
        half_range = int(abs(right_avg - left_avg) / 2)
        # Ensure a minimum to avoid division by zero
        half_range = max(half_range, 100)

        self._steering_center = center
        self._steering_half_range = half_range
        self._update_steering_calibration_label()

        try:
            self.save_current_mapping()
            self._set_status(f"Steering calibrated. Center: {center}, Half-range: {half_range}")
        except Exception:
            self._set_status(f"Calibration complete (center={center}, range={half_range}). Click Save to persist.")

    def _update_steering_calibration_label(self) -> None:
        """Refresh the steering center/range label in settings."""
        if hasattr(self, "_steering_center_label"):
            self._steering_center_label.setText(
                f"Center: {int(self._steering_center)} | Rotation: {int(self._steering_range)}°"
            )

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
        
        # Fall back to embedded default sound if user file not found
        if not path.exists():
            path = self._default_sound_path
        
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

    def _on_watermark_visible_changed_internal(self, state: int) -> None:
        """Handle watermark visibility checkbox changes."""
        visible = state == Qt.Checked.value
        self._on_watermark_visible_changed(visible)

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

    def set_show_watermark(self, visible: bool, *, update_checkbox: bool = False) -> None:
        """Set watermark visibility and optionally sync the checkbox."""
        if update_checkbox:
            self._show_watermark_checkbox.blockSignals(True)
            self._show_watermark_checkbox.setChecked(visible)
            self._show_watermark_checkbox.blockSignals(False)

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
        """Persist UI-related settings (targets, grid, sounds, update rate, steering/watermark visibility)."""
        cfg = UiConfig(
            throttle_target=self._throttle_target_slider.value(),
            brake_target=self._brake_target_slider.value(),
            grid_step_percent=self._grid_step_slider.value(),
            update_hz=self._update_rate_slider.value(),
            show_steering=self._show_steering_checkbox.isChecked(),
            show_watermark=self._show_watermark_checkbox.isChecked(),
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
