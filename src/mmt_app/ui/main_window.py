"""Main window for the Muscle Memory Trainer application.

Design notes:
- UI code stays here; input I/O lives in `mmt_app.input.*` modules.
- Calibration uses a simple "press to bind" heuristic (see `mmt_app.input.calibration`).
- Mappings are persisted to `config.ini` via `mmt_app.config`.
"""

import math
import sys
from pathlib import Path
from random import random
from typing import List, Optional

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QProgressBar,
    QSlider,
    QSpinBox,
    QStyle,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QDialog,
)

from ..config import InputProfile, PedalsConfig, UiConfig, WheelConfig, load_input_profile, save_input_profile, save_ui_config
from ..input.calibration import detect_changing_byte
from ..input.hid_backend import HidDeviceInfo, HidSession, enumerate_devices, hid_available
from ..telemetry import TelemetrySample
from .telemetry_chart import TelemetryChart
from .static_brake_tab import StaticBrakeTab
from .active_brake_tab import ActiveBrakeTab


def _resource_path(*parts: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base_path.joinpath("resources", *parts)

MAX_REPORT_LEN = 1024
MAX_READS_PER_TICK = 50


class MainWindow(QMainWindow):
    """
    Telemetry trainer with a settings tab:
    - Live telemetry chart for throttle/brake/steering.
    - Device selection tab for choosing pedals + wheel HID devices and report byte offsets.
    - Falls back to simulated input if no device is available/selected.
    """

    def __init__(self, *, app_name: str, version: str) -> None:
        """Set up the main window, tabs, timers, and initial state."""
        super().__init__()
        self.app_name = app_name
        self.version = version
        self.setWindowTitle(f"{self.app_name} - v{self.version}")
        self.resize(1080, 600)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.max_points = 200
        self.sample_index = 0
        self.last_sample = TelemetrySample(throttle=0.0, brake=0.0, steering=0.0)

        self.devices: List[HidDeviceInfo] = []
        self.pedals_device_index: Optional[int] = None
        self.wheel_device_index: Optional[int] = None
        self.pedals_device: Optional[HidDeviceInfo] = None
        self.wheel_device: Optional[HidDeviceInfo] = None
        self.pedals_session = HidSession()
        self.wheel_session = HidSession()
        self.calibration_axis: Optional[str] = None
        self.calibration_device: Optional[str] = None  # "pedals" | "wheel"
        self._baseline_samples: list[list[int]] = []
        self._active_samples: list[list[int]] = []
        self._calibration_timer = QTimer()
        self._calibration_timer.timeout.connect(self._capture_calibration_sample)
        self._steering_cal_timer = QTimer()
        self._steering_cal_timer.timeout.connect(self._capture_steering_calibration_sample)

        self._default_sound_path = _resource_path("beep.mp3")
        self._audio_output = QAudioOutput()
        self._media_player = QMediaPlayer()
        self._media_player.setAudioOutput(self._audio_output)
        self._throttle_target_hit = False
        self._brake_target_hit = False
        self._sound_checkboxes: dict[str, QCheckBox] = {}
        self._sound_files: dict[str, QLineEdit] = {}
        self._update_rate = 20
        self._show_steering = False
        self._steering_alpha = 0.08  # smoothing factor to dampen steering jitter
        self._steering_deadband = 1.5  # degrees of change to ignore small noise
        self._steering_center = 128
        self._steering_range = 127
        self._steering_cal_stage: str | None = None
        self._steering_center_samples: list[int] = []
        self._steering_left_samples: list[int] = []
        self._steering_right_samples: list[int] = []
        self._steering_manual_applied = False
        self._steering_cal_dialog: QDialog | None = None
        self._steering_cal_label: QLabel | None = None
        self._steering_cal_start_btn: QPushButton | None = None
        self._steering_pending_stage: str | None = None
        self.update_rate_row = self._create_update_rate_row()

        telemetry_tab = self._build_telemetry_tab()
        settings_tab = self._build_settings_tab()
        self.active_brake_tab = self._build_active_brake_tab()

        tabs = QTabWidget()
        tabs.addTab(telemetry_tab, "Telemetry")
        tabs.addTab(self._build_static_brake_tab(), "Static Brake")
        tabs.addTab(self.active_brake_tab, "Active Brake")
        tabs.addTab(settings_tab, "Settings")
        self.setCentralWidget(tabs)

        self.timer = QTimer(interval=50)
        self.timer.timeout.connect(self._on_tick)
        self._set_update_rate(self._update_rate, update_spin=True)

        self._ui_save_timer = QTimer()
        self._ui_save_timer.setSingleShot(True)
        self._ui_save_timer.timeout.connect(self._save_ui_settings)

        self._load_persisted_config()
        self._update_status()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Ensure HID sessions are closed before the window shuts down."""
        try:
            self.pedals_session.close()
            self.wheel_session.close()
        finally:
            super().closeEvent(event)

    def _build_telemetry_tab(self) -> QWidget:
        """Create the live telemetry tab with controls and chart."""
        self.throttle_target = QSlider(Qt.Horizontal)
        self.throttle_target.setRange(0, 100)
        self.throttle_target.setSingleStep(1)
        self.throttle_target.setPageStep(5)
        self.throttle_target.setTickInterval(10)
        self.throttle_target.setTickPosition(QSlider.TicksBelow)
        self.throttle_target.setValue(60)
        self.throttle_target.setObjectName("throttleTargetSlider")
        self.throttle_target.valueChanged.connect(self._schedule_save_ui_settings)

        self.throttle_target_value = QLabel("60%")
        self.throttle_target_value.setObjectName("throttleTargetValue")
        self.throttle_target_value.setMinimumWidth(52)
        self.throttle_target.valueChanged.connect(lambda v: self.throttle_target_value.setText(f"{int(v)}%"))

        throttle_target_row = QWidget()
        throttle_target_row_layout = QHBoxLayout(throttle_target_row)
        throttle_target_row_layout.setContentsMargins(0, 0, 0, 0)
        throttle_target_row_layout.addWidget(self.throttle_target, stretch=1)
        throttle_target_row_layout.addWidget(self.throttle_target_value)

        self.brake_target = QSlider(Qt.Horizontal)
        self.brake_target.setRange(0, 100)
        self.brake_target.setSingleStep(1)
        self.brake_target.setPageStep(5)
        self.brake_target.setTickInterval(10)
        self.brake_target.setTickPosition(QSlider.TicksBelow)
        self.brake_target.setValue(40)
        self.brake_target.setObjectName("brakeTargetSlider")
        self.brake_target.valueChanged.connect(self._schedule_save_ui_settings)

        self.brake_target_value = QLabel("40%")
        self.brake_target_value.setObjectName("brakeTargetValue")
        self.brake_target_value.setMinimumWidth(52)
        self.brake_target.valueChanged.connect(lambda v: self.brake_target_value.setText(f"{int(v)}%"))

        brake_target_row = QWidget()
        brake_target_row_layout = QHBoxLayout(brake_target_row)
        brake_target_row_layout.setContentsMargins(0, 0, 0, 0)
        brake_target_row_layout.addWidget(self.brake_target, stretch=1)
        brake_target_row_layout.addWidget(self.brake_target_value)

        self.grid_step_slider = QSlider(Qt.Horizontal)
        self.grid_step_slider.setRange(5, 50)
        self.grid_step_slider.setSingleStep(5)
        self.grid_step_slider.setPageStep(5)
        self.grid_step_slider.setTickInterval(5)
        self.grid_step_slider.setTickPosition(QSlider.TicksBelow)
        self.grid_step_slider.setValue(10)
        self.grid_step_slider.valueChanged.connect(self._on_grid_step_changed)
        self.grid_step_slider.valueChanged.connect(self._schedule_save_ui_settings)
        self.grid_step_value = QLabel("10%")
        grid_row = QWidget()
        grid_row_layout = QHBoxLayout(grid_row)
        grid_row_layout.setContentsMargins(0, 0, 0, 0)
        grid_row_layout.addWidget(self.grid_step_slider, stretch=1)
        grid_row_layout.addWidget(self.grid_step_value)

        self.show_steering_checkbox = QCheckBox("Show steering trace")
        self.show_steering_checkbox.setChecked(self._show_steering)
        self.show_steering_checkbox.stateChanged.connect(self._on_show_steering_changed)

        self.start_button = QPushButton("Start")
        self.start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.start_button.clicked.connect(self.toggle_stream)
        self.reset_button = QPushButton("Reset")
        self.reset_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.reset_button.clicked.connect(self.reset_chart)

        controls = QFormLayout()
        controls.addRow("Throttle target", throttle_target_row)
        controls.addRow("Brake target", brake_target_row)
        controls.addRow("Grid division", grid_row)
        controls.addRow("", self.show_steering_checkbox)
        controls.addRow("Update rate", self.update_rate_row)

        control_bar = QHBoxLayout()
        control_bar.addStretch()
        control_bar.addWidget(self.start_button)
        control_bar.addWidget(self.reset_button)
        control_bar.addStretch()

        self.telemetry_chart = TelemetryChart(max_points=self.max_points)
        self._on_grid_step_changed()
        self.telemetry_chart.set_steering_visible(self._show_steering)

        # Live vertical bars beside the chart for quick glance.
        self.throttle_bar_label = QLabel("0%")
        self.throttle_bar_label.setObjectName("throttleBarLabel")
        self.brake_bar_label = QLabel("0%")
        self.brake_bar_label.setObjectName("brakeBarLabel")

        self.throttle_bar = QProgressBar()
        self.throttle_bar.setOrientation(Qt.Vertical)
        self.throttle_bar.setRange(0, 100)
        self.throttle_bar.setValue(0)
        self.throttle_bar.setTextVisible(False)
        self.throttle_bar.setObjectName("throttleBar")
        self.throttle_bar.setFixedWidth(28)
        self.throttle_bar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self.brake_bar = QProgressBar()
        self.brake_bar.setOrientation(Qt.Vertical)
        self.brake_bar.setRange(0, 100)
        self.brake_bar.setValue(0)
        self.brake_bar.setTextVisible(False)
        self.brake_bar.setObjectName("brakeBar")
        self.brake_bar.setFixedWidth(28)
        self.brake_bar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        bar_labels = QHBoxLayout()
        bar_labels.setContentsMargins(0, 0, 0, 0)
        bar_labels.setSpacing(12)
        bar_labels.addWidget(self.throttle_bar_label, alignment=Qt.AlignHCenter)
        bar_labels.addWidget(self.brake_bar_label, alignment=Qt.AlignHCenter)

        bar_columns = QHBoxLayout()
        bar_columns.setContentsMargins(0, 0, 0, 0)
        bar_columns.setSpacing(12)
        bar_columns.addWidget(self.throttle_bar)
        bar_columns.addWidget(self.brake_bar)

        bars_stack = QVBoxLayout()
        bars_stack.setContentsMargins(12, 0, 0, 0)
        bars_stack.setSpacing(6)
        bars_stack.addLayout(bar_labels)
        bars_stack.addLayout(bar_columns, stretch=1)
        bars_container = QWidget()
        bars_container.setLayout(bars_stack)
        bars_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        chart_row = QHBoxLayout()
        chart_row.addWidget(self.telemetry_chart.view, stretch=1)
        chart_row.addWidget(bars_container)

        layout = QVBoxLayout()
        layout.addLayout(controls)
        layout.addLayout(control_bar)
        layout.addLayout(chart_row, stretch=1)

        container = QWidget()
        container.setLayout(layout)
        return container

    def _build_settings_tab(self) -> QWidget:
        """Create the settings tab for device selection, calibration, and sounds."""
        self.pedals_device_combo = QComboBox()
        self.wheel_device_combo = QComboBox()
        self.device_status = QLabel("No devices detected.")

        self.pedals_report_len = QSpinBox()
        self.pedals_report_len.setRange(1, MAX_REPORT_LEN)
        self.pedals_report_len.setValue(64)
        self.wheel_report_len = QSpinBox()
        self.wheel_report_len.setRange(1, MAX_REPORT_LEN)
        self.wheel_report_len.setValue(64)

        self.throttle_offset = QSpinBox()
        self.throttle_offset.setRange(0, MAX_REPORT_LEN - 1)
        self.throttle_offset.setValue(0)
        self.brake_offset = QSpinBox()
        self.brake_offset.setRange(0, MAX_REPORT_LEN - 1)
        self.brake_offset.setValue(1)
        self.steering_offset = QSpinBox()
        self.steering_offset.setRange(0, MAX_REPORT_LEN - 1)
        self.steering_offset.setValue(2)
        self.steering_center_spin = QSpinBox()
        self.steering_center_spin.setRange(0, 255)
        self.steering_center_spin.setValue(self._steering_center)
        self.steering_range_spin = QSpinBox()
        self.steering_range_spin.setRange(1, 255)
        self.steering_range_spin.setValue(self._steering_range)
        self.steering_range_spin.setSuffix(" span")

        refresh_btn = QPushButton("Refresh devices")
        refresh_btn.clicked.connect(self.refresh_devices)
        apply_btn = QPushButton("Use selection")
        apply_btn.clicked.connect(self.apply_device_selection)
        save_btn = QPushButton("Save to config.ini")
        save_btn.setText("Save all")
        save_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        save_btn.clicked.connect(self.save_current_mapping)

        cal_throttle_btn = QPushButton("Calibrate Throttle (press)")
        cal_throttle_btn.clicked.connect(lambda: self.start_calibration("pedals", "throttle"))
        cal_brake_btn = QPushButton("Calibrate Brake (press)")
        cal_brake_btn.clicked.connect(lambda: self.start_calibration("pedals", "brake"))
        cal_steer_btn = QPushButton("Calibrate Steering (turn)")
        cal_steer_btn.clicked.connect(lambda: self.start_calibration("wheel", "steering"))
        cal_steer_range_btn = QPushButton("Calibrate Steering Range")
        cal_steer_range_btn.clicked.connect(self.calibrate_steering_range)
        apply_steer_btn = QPushButton("Apply center/range")
        apply_steer_btn.clicked.connect(self._apply_manual_steering_range)

        form = QFormLayout()
        form.addRow("Pedals device", self.pedals_device_combo)
        form.addRow("Pedals report length (bytes)", self.pedals_report_len)
        form.addRow("Throttle byte offset", self.throttle_offset)
        form.addRow("Brake byte offset", self.brake_offset)
        form.addRow("Wheel device", self.wheel_device_combo)
        form.addRow("Wheel report length (bytes)", self.wheel_report_len)
        form.addRow("Steering byte offset", self.steering_offset)
        self.steering_center_label = QLabel("Center: 128 | Range: 127")
        form.addRow("Steering calibration", self.steering_center_label)
        form.addRow("Steering center", self.steering_center_spin)
        form.addRow("Steering span", self.steering_range_spin)

        buttons = QHBoxLayout()
        buttons.addWidget(refresh_btn)
        buttons.addWidget(apply_btn)
        buttons.addStretch()

        cal_buttons = QHBoxLayout()
        cal_buttons.addWidget(cal_throttle_btn)
        cal_buttons.addWidget(cal_brake_btn)
        cal_buttons.addWidget(cal_steer_btn)
        cal_buttons.addWidget(cal_steer_range_btn)
        cal_buttons.addWidget(apply_steer_btn)
        cal_buttons.addStretch()

        input_group = QGroupBox("Input Settings")
        input_layout = QVBoxLayout()
        input_layout.addLayout(form)
        input_layout.addLayout(buttons)
        input_layout.addLayout(cal_buttons)
        input_layout.addWidget(self.device_status)
        input_group.setLayout(input_layout)

        throttle_row = self._build_sound_row(kind="throttle", label="Throttle target sound")
        brake_row = self._build_sound_row(kind="brake", label="Brake target sound")

        app_form = QFormLayout()
        app_form.addRow("Throttle sound", throttle_row)
        app_form.addRow("Brake sound", brake_row)
        app_form.addRow("Update rate", self.update_rate_row)
        app_form.addRow("Steering trace", self.show_steering_checkbox)

        app_group = QGroupBox("App Settings")
        app_layout = QVBoxLayout()
        app_layout.addLayout(app_form)
        app_group.setLayout(app_layout)

        save_bar = QHBoxLayout()
        save_bar.addStretch()
        save_bar.addWidget(save_btn)
        save_bar.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(save_bar)
        layout.addWidget(input_group)
        layout.addWidget(app_group)
        layout.addStretch()

        container = QWidget()
        container.setLayout(layout)

        self.refresh_devices()
        return container

    def _build_static_brake_tab(self) -> QWidget:
        """Create the Static Brake training tab."""
        return StaticBrakeTab(read_brake_percent=self._read_brake_for_static_tab)

    def _build_active_brake_tab(self) -> QWidget:
        """Create the Active Brake training tab."""
        return ActiveBrakeTab(read_brake_percent=self._read_brake_for_active_tab)

    def _read_brake_for_active_tab(self) -> float:
        """
        Provide live brake input to the Active Brake tab even when the main telemetry
        timer is paused. Reuses the shared input reader for HID/simulator values.
        """
        sample = self._read_inputs()
        self.last_sample = sample
        return float(sample.brake)

    def _read_brake_for_static_tab(self) -> float:
        """
        Provide live brake input to Static Brake tab even when main timer is paused.
        Reuses shared input reader for HID/simulator values.
        """
        sample = self._read_inputs()
        self.last_sample = sample
        return float(sample.brake)

    def _on_update_rate_changed(self) -> None:
        """Handle slider changes by applying and persisting new update rate."""
        value = int(self.update_rate_slider.value())
        self.update_rate_value.setText(f"{value} Hz")
        self._set_update_rate(value)
        self._schedule_save_ui_settings()

    def _on_show_steering_changed(self) -> None:
        """Toggle steering visibility and persist the setting."""
        self._show_steering = self.show_steering_checkbox.isChecked()
        self.telemetry_chart.set_steering_visible(self._show_steering)
        self._schedule_save_ui_settings()

    def _create_update_rate_row(self) -> QWidget:
        """Build the update rate slider + label UI row."""
        self.update_rate_slider = QSlider(Qt.Horizontal)
        self.update_rate_slider.setRange(5, 120)
        self.update_rate_slider.setTickInterval(5)
        self.update_rate_slider.setTickPosition(QSlider.TicksBelow)
        self.update_rate_slider.setSingleStep(1)
        self.update_rate_slider.setPageStep(5)
        self.update_rate_slider.setValue(self._update_rate)
        self.update_rate_slider.valueChanged.connect(self._on_update_rate_changed)

        self.update_rate_value = QLabel(f"{self._update_rate} Hz")
        self.update_rate_value.setMinimumWidth(48)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.update_rate_slider, stretch=1)
        layout.addWidget(self.update_rate_value)
        return row

    def refresh_devices(self) -> None:
        """Enumerate HID devices and populate pedals/wheel selectors."""
        self.pedals_device_combo.clear()
        self.wheel_device_combo.clear()
        self.devices = []
        self.pedals_device = None
        self.wheel_device = None
        if not hid_available():
            self.device_status.setText("hidapi not installed; using simulator input.")
            self.pedals_device_index = None
            self.wheel_device_index = None
            self._update_status()
            return

        self.devices = enumerate_devices()
        if not self.devices:
            self.device_status.setText("No HID devices detected; using simulator.")
            self.pedals_device_index = None
            self.wheel_device_index = None
            self._update_status()
            return

        for idx, dev in enumerate(self.devices):
            label = (
                f"{dev.product_string} "
                f"(vid {dev.device_id.vendor_id:04x}, pid {dev.device_id.product_id:04x})"
            )
            self.pedals_device_combo.addItem(label, idx)
            self.wheel_device_combo.addItem(label, idx)
        self.device_status.setText("Select pedals + wheel devices and click 'Use selection'.")
        self.pedals_device_combo.setCurrentIndex(0)
        self.wheel_device_combo.setCurrentIndex(0)
        self._update_status()

    def apply_device_selection(self) -> None:
        """Open the currently selected pedals and wheel devices."""
        if not self.devices:
            self.pedals_device_index = None
            self.wheel_device_index = None
            self.pedals_device = None
            self.wheel_device = None
            self.device_status.setText("No devices available; simulator mode.")
            self._update_status()
            return
        self.pedals_device_index = int(self.pedals_device_combo.currentData())
        self.wheel_device_index = int(self.wheel_device_combo.currentData())
        if not hid_available():
            self.device_status.setText("hidapi not installed; simulator mode.")
            self.pedals_device_index = None
            self.wheel_device_index = None
            self.pedals_device = None
            self.wheel_device = None
            self._update_status()
            return

        try:
            self.pedals_device = self.devices[self.pedals_device_index]
            self.wheel_device = self.devices[self.wheel_device_index]

            self.pedals_session.open(self.pedals_device)
            self.wheel_session.open(self.wheel_device)

            self.device_status.setText("Using selected pedals + wheel devices via HID.")
            self._update_status()
        except Exception as exc:
            self.device_status.setText(f"HID open failed: {exc}; simulator mode.")
            self.pedals_device_index = None
            self.wheel_device_index = None
            self.pedals_device = None
            self.wheel_device = None
            self.pedals_session.close()
            self.wheel_session.close()
            self._update_status()

    def save_current_mapping(self) -> None:
        """Persist UI settings plus device IDs/report lengths/offsets (when available)."""
        # Always persist UI (including sound paths) even if devices are missing.
        self._save_ui_settings()
        if not self.pedals_device or not self.wheel_device:
            self.device_status.setText("Saved UI settings. Select pedals and wheel to save input mapping.")
            self._update_status()
            return
        try:
            pedals_cfg = PedalsConfig(
                vendor_id=int(self.pedals_device.device_id.vendor_id),
                product_id=int(self.pedals_device.device_id.product_id),
                product_string=str(self.pedals_device.product_string),
                report_len=int(self.pedals_report_len.value()),
                throttle_offset=int(self.throttle_offset.value()),
                brake_offset=int(self.brake_offset.value()),
            )
            wheel_cfg = WheelConfig(
                vendor_id=int(self.wheel_device.device_id.vendor_id),
                product_id=int(self.wheel_device.device_id.product_id),
                product_string=str(self.wheel_device.product_string),
                report_len=int(self.wheel_report_len.value()),
                steering_offset=int(self.steering_offset.value()),
                steering_center=int(self._steering_center),
                steering_range=int(self._steering_range),
            )
            save_input_profile(InputProfile(pedals=pedals_cfg, wheel=wheel_cfg, ui=None))
            self.device_status.setText("Saved pedals + wheel mappings to config.ini.")
            self._update_status()
        except Exception as exc:
            self.device_status.setText(f"Save failed: {exc}")

    def _load_persisted_config(self) -> None:
        """Load mappings and UI settings from `config.ini`."""
        profile = load_input_profile()
        pedals_cfg = profile.pedals
        wheel_cfg = profile.wheel
        ui_cfg = profile.ui

        if pedals_cfg:
            self.pedals_report_len.setValue(max(1, min(MAX_REPORT_LEN, pedals_cfg.report_len)))
            self.throttle_offset.setValue(max(0, min(MAX_REPORT_LEN - 1, pedals_cfg.throttle_offset)))
            self.brake_offset.setValue(max(0, min(MAX_REPORT_LEN - 1, pedals_cfg.brake_offset)))
        if wheel_cfg:
            self.wheel_report_len.setValue(max(1, min(MAX_REPORT_LEN, wheel_cfg.report_len)))
            self.steering_offset.setValue(max(0, min(MAX_REPORT_LEN - 1, wheel_cfg.steering_offset)))
            self._steering_center = int(wheel_cfg.steering_center)
            self._steering_range = max(1, int(wheel_cfg.steering_range))
            self._update_steering_calibration_label()

        if ui_cfg:
            self.throttle_target.setValue(max(0, min(100, ui_cfg.throttle_target)))
            self.brake_target.setValue(max(0, min(100, ui_cfg.brake_target)))
            self._set_grid_step(ui_cfg.grid_step_percent)
            self._set_update_rate(ui_cfg.update_hz, update_spin=True)
            self._set_show_steering(ui_cfg.show_steering, update_checkbox=True)
            self._apply_sound_settings(
                throttle_enabled=ui_cfg.throttle_sound_enabled,
                throttle_path=ui_cfg.throttle_sound_path,
                brake_enabled=ui_cfg.brake_sound_enabled,
                brake_path=ui_cfg.brake_sound_path,
            )
        else:
            self._set_update_rate(self._update_rate, update_spin=True)
            self._set_show_steering(self._show_steering, update_checkbox=True)
            self._apply_sound_settings(
                throttle_enabled=True,
                throttle_path=str(self._default_sound_path),
                brake_enabled=True,
                brake_path=str(self._default_sound_path),
            )
        self._update_steering_calibration_label()

        self.refresh_devices()

        def find_index(vendor_id: int, product_id: int) -> Optional[int]:
            for idx, dev in enumerate(self.devices):
                if dev.device_id.vendor_id == vendor_id and dev.device_id.product_id == product_id:
                    return idx
            return None

        if pedals_cfg:
            idx = find_index(pedals_cfg.vendor_id, pedals_cfg.product_id)
            if idx is not None:
                self.pedals_device_combo.setCurrentIndex(idx)
        if wheel_cfg:
            idx = find_index(wheel_cfg.vendor_id, wheel_cfg.product_id)
            if idx is not None:
                self.wheel_device_combo.setCurrentIndex(idx)

        if pedals_cfg or wheel_cfg:
            self.apply_device_selection()
            self.device_status.setText("Loaded settings from config.ini.")

    def _set_grid_step(self, step_percent: int) -> None:
        """Set the telemetry grid step via the slider, snapping to 5% increments."""
        step_percent = max(5, min(50, int(round(step_percent / 5) * 5)))
        if hasattr(self, "grid_step_slider"):
            try:
                self.grid_step_slider.blockSignals(True)
                self.grid_step_slider.setValue(step_percent)
            finally:
                self.grid_step_slider.blockSignals(False)
        self._update_grid_step_value(step_percent)
        if hasattr(self, "telemetry_chart"):
            self.telemetry_chart.set_grid_step(step_percent=step_percent)

    def _update_grid_step_value(self, step_percent: int) -> None:
        if hasattr(self, "grid_step_value"):
            self.grid_step_value.setText(f"{int(step_percent)}%")

    def start_calibration(self, device_kind: str, axis: str) -> None:
        """Start an interactive calibration for a single axis on one device."""
        if device_kind not in ("pedals", "wheel"):
            return
        if axis not in ("throttle", "brake", "steering"):
            return
        if device_kind == "pedals" and not self.pedals_session.is_open:
            self.device_status.setText("Select a pedals HID device first.")
            return
        if device_kind == "wheel" and not self.wheel_session.is_open:
            self.device_status.setText("Select a wheel HID device first.")
            return
        self.calibration_device = device_kind
        self.calibration_axis = axis
        self._baseline_samples = []
        self._active_samples = []

        self.device_status.setText(
            f"Calibrating {axis} on {device_kind}: keep controls still for 1s..."
        )
        self._calibration_timer.start(20)
        QTimer.singleShot(1000, self._begin_active_calibration)

    def _begin_active_calibration(self) -> None:
        """Begin the active portion of calibration after the baseline pause."""
        if not self.calibration_axis:
            return
        action = "press and hold" if self.calibration_axis in ("throttle", "brake") else "turn left/right"
        self.device_status.setText(f"Calibrating {self.calibration_axis}: now {action} for 2s...")
        self._baseline_samples, self._active_samples = self._active_samples, []
        QTimer.singleShot(2000, self._finish_calibration)

    def _finish_calibration(self) -> None:
        """Complete calibration by identifying the changing byte and applying it."""
        device_kind = self.calibration_device
        axis = self.calibration_axis
        self._calibration_timer.stop()
        self.calibration_device = None
        self.calibration_axis = None
        if not axis:
            return
        if not device_kind:
            return
        if not self._baseline_samples or not self._active_samples:
            self.device_status.setText("Calibration failed: not enough data. Try again.")
            return

        result = detect_changing_byte(self._baseline_samples, self._active_samples)
        if result is None:
            self.device_status.setText("Calibration failed: couldn't detect changing byte. Try again.")
            return

        if axis == "throttle":
            self.throttle_offset.setValue(result.offset)
        elif axis == "brake":
            self.brake_offset.setValue(result.offset)
        else:
            self.steering_offset.setValue(result.offset)

        self.device_status.setText(
            f"Calibration complete: {axis} offset = {result.offset} (score {result.score:.1f}). Save to persist."
        )

    def _capture_calibration_sample(self) -> None:
        """Read and buffer a single HID report during calibration."""
        session = self.pedals_session if self.calibration_device == "pedals" else self.wheel_session
        if not session.is_open:
            return
        report_len = self.pedals_report_len.value() if self.calibration_device == "pedals" else self.wheel_report_len.value()
        report = session.read_latest_report(report_len=report_len, max_reads=MAX_READS_PER_TICK)
        if report is None:
            return
        self._active_samples.append(report)

    def calibrate_steering_range(self) -> None:
        """Calibrate steering center/range (for different wheel rotation angles)."""
        if not self.wheel_session.is_open:
            self.device_status.setText("Select a wheel HID device first.")
            return
        if self.steering_offset.value() >= self.wheel_report_len.value():
            self.device_status.setText("Adjust steering offset/length first.")
            return

        # Reset samples and show guided dialog.
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
        if stage == "center":
            self._steering_center_samples = []
            text = "Capturing center... keep wheel still for 3s."
        elif stage == "left":
            self._steering_left_samples = []
            text = "Capturing full left... hold for 3s."
        else:
            self._steering_right_samples = []
            text = "Capturing full right... hold for 3s."
        self._set_steering_dialog_text(text)
        if self._steering_cal_start_btn:
            self._steering_cal_start_btn.setEnabled(False)
        self._steering_cal_timer.start(20)
        QTimer.singleShot(3000, self._complete_steering_stage)

    def _set_steering_dialog_text(self, text: str) -> None:
        if self._steering_cal_label:
            self._steering_cal_label.setText(text)

    def _complete_steering_stage(self) -> None:
        """Stop current stage and advance to next step or finish."""
        self._steering_cal_timer.stop()
        stage = self._steering_cal_stage
        self._steering_cal_stage = None
        if stage == "center":
            self._steering_pending_stage = "left"
            self._set_steering_dialog_text("Step 2 of 3: Turn wheel full left. Click Start when ready.")
        elif stage == "left":
            self._steering_pending_stage = "right"
            self._set_steering_dialog_text("Step 3 of 3: Turn wheel full right. Click Start when ready.")
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
        self.device_status.setText("Steering calibration canceled.")

    def _close_steering_cal_dialog(self, dialog: QDialog | None = None) -> None:
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
        if not self.wheel_session.is_open or not self._steering_cal_stage:
            return
        report = self.wheel_session.read_latest_report(
            report_len=self.wheel_report_len.value(),
            max_reads=MAX_READS_PER_TICK,
        )
        if not report:
            return
        s_off = self.steering_offset.value()
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
        self._steering_cal_timer.stop()
        self._steering_cal_stage = None
        if not self._steering_center_samples or not (self._steering_left_samples or self._steering_right_samples):
            self.device_status.setText("Steering calibration failed: not enough data.")
            return
        center = int(sum(self._steering_center_samples) / max(1, len(self._steering_center_samples)))
        left_min = min(self._steering_left_samples) if self._steering_left_samples else center
        right_max = max(self._steering_right_samples) if self._steering_right_samples else center
        span = max(center - left_min, right_max - center, 1)
        self._steering_center = center
        self._steering_range = span
        self.steering_center_spin.setValue(center)
        self.steering_range_spin.setValue(span)
        self._update_steering_calibration_label()
        try:
            self.save_current_mapping()
            self.device_status.setText(
                f"Steering calibrated: center={center}, range={span}. Saved to config.ini."
            )
        except Exception:
            self.device_status.setText(
                f"Steering calibrated: center={center}, range={span}. Click Save to persist."
            )

    def toggle_stream(self) -> None:
        """Start or pause the main telemetry timer."""
        if self.timer.isActive():
            self.timer.stop()
            self.start_button.setText("Start")
            self.start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        else:
            self.timer.start()
            self.start_button.setText("Pause")
            self.start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))

    def reset_chart(self) -> None:
        """Clear the telemetry chart and reset state."""
        self.telemetry_chart.reset()
        self._update_bars(TelemetrySample(throttle=0.0, brake=0.0, steering=0.0))
        self._throttle_target_hit = False
        self._brake_target_hit = False
        self._update_status()

    def _on_tick(self) -> None:
        """Timer tick: read inputs, update charts, play sounds, and status."""
        sample = self._read_inputs()
        self.last_sample = sample
        self.telemetry_chart.append(sample)
        self.telemetry_chart.set_targets(
            throttle_target=float(self.throttle_target.value()),
            brake_target=float(self.brake_target.value()),
        )
        self._update_bars(sample)
        self._maybe_play_target_sound(sample)
        self._update_status()

    def _on_grid_step_changed(self) -> None:
        """Update the telemetry grid step when the slider changes."""
        step = int(round(self.grid_step_slider.value() / 5) * 5)
        step = max(5, min(50, step))
        if step != self.grid_step_slider.value():
            self.grid_step_slider.blockSignals(True)
            self.grid_step_slider.setValue(step)
            self.grid_step_slider.blockSignals(False)
        self._update_grid_step_value(step)
        self.telemetry_chart.set_grid_step(step_percent=step)
        # Keep tick marks sensible when changing rate/step together.

    def _schedule_save_ui_settings(self) -> None:
        # Debounce to avoid writing on every tick while the user drags a control.
        self._ui_save_timer.start(250)

    def _set_update_rate(self, hz: int, *, update_spin: bool = False) -> None:
        """Apply the requested update rate to timers and sync UI controls."""
        hz = max(5, min(120, int(hz)))
        interval_ms = max(1, int(1000 / hz))
        self._update_rate = hz
        self.timer.setInterval(interval_ms)
        if hasattr(self, "active_brake_tab"):
            try:
                self.active_brake_tab.set_update_rate(hz)
            except Exception:
                pass
        if update_spin and hasattr(self, "update_rate_slider"):
            self.update_rate_slider.blockSignals(True)
            self.update_rate_slider.setValue(hz)
            self.update_rate_slider.blockSignals(False)
        if hasattr(self, "update_rate_value"):
            self.update_rate_value.setText(f"{hz} Hz")

    def _set_show_steering(self, visible: bool, *, update_checkbox: bool = False) -> None:
        """Apply steering visibility to the chart and sync the checkbox."""
        self._show_steering = bool(visible)
        if hasattr(self, "telemetry_chart"):
            self.telemetry_chart.set_steering_visible(self._show_steering)
        if update_checkbox and hasattr(self, "show_steering_checkbox"):
            self.show_steering_checkbox.blockSignals(True)
            self.show_steering_checkbox.setChecked(self._show_steering)
            self.show_steering_checkbox.blockSignals(False)

    def _update_steering_calibration_label(self) -> None:
        """Refresh the steering center/range label in settings."""
        if hasattr(self, "steering_center_label"):
            self.steering_center_label.setText(
                f"Center: {int(self._steering_center)} | Range: {int(self._steering_range)}"
            )

    def _apply_manual_steering_range(self) -> None:
        """Allow users to manually set steering center/range from spinboxes."""
        self._steering_center = int(self.steering_center_spin.value())
        self._steering_range = max(1, int(self.steering_range_spin.value()))
        self._update_steering_calibration_label()
        try:
            self.save_current_mapping()
            self.device_status.setText(
                f"Steering center/range updated (center={self._steering_center}, range={self._steering_range}). Saved."
            )
        except Exception:
            self.device_status.setText(
                f"Steering center/range updated (center={self._steering_center}, range={self._steering_range}). Click Save to persist."
            )

    def _save_ui_settings(self) -> None:
        """Persist UI-related settings (targets, grid, sounds, update rate)."""
        cfg = UiConfig(
            throttle_target=int(self.throttle_target.value()),
            brake_target=int(self.brake_target.value()),
            grid_step_percent=int(self.grid_step_slider.value()),
            update_hz=int(self.update_rate_slider.value()),
            show_steering=bool(self.show_steering_checkbox.isChecked()),
            throttle_sound_enabled=self._sound_enabled("throttle"),
            throttle_sound_path=self._resolve_sound_path_text("throttle"),
            brake_sound_enabled=self._sound_enabled("brake"),
            brake_sound_path=self._resolve_sound_path_text("brake"),
        )
        save_ui_config(cfg)

    def _update_status(self) -> None:
        """Update the status bar with current device usage."""
        parts: list[str] = []
        if self.pedals_session.is_open:
            parts.append(f"Pedals: {self.pedals_device_combo.currentText()}")
        if self.wheel_session.is_open:
            parts.append(f"Wheel: {self.wheel_device_combo.currentText()}")
        message = " | ".join(parts) if parts else "Simulator mode (no devices streaming)"
        self.status_bar.showMessage(message)

    def _maybe_play_target_sound(self, sample: TelemetrySample) -> None:
        """Play sounds when throttle/brake cross their targets."""
        throttle_target = float(self.throttle_target.value())
        brake_target = float(self.brake_target.value())
        self._update_target_flag(sample.throttle, throttle_target, "_throttle_target_hit", "throttle")
        self._update_target_flag(sample.brake, brake_target, "_brake_target_hit", "brake")

    def _update_target_flag(self, value: float, target: float, flag_attr: str, kind: str) -> None:
        """Track threshold crossings for a single axis and trigger sound once."""
        reset_threshold = max(0.0, target - 5.0)
        already_hit = getattr(self, flag_attr)
        if not self._sound_enabled(kind):
            setattr(self, flag_attr, False)
            return
        if value >= target and not already_hit:
            self._play_target_sound(kind)
            setattr(self, flag_attr, True)
        elif value < reset_threshold:
            setattr(self, flag_attr, False)

    def _play_target_sound(self, kind: str) -> None:
        """Play the selected sound for the given target if the file looks valid."""
        path = Path(self._resolve_sound_path_text(kind))
        if not path.exists() or path.suffix.lower() not in {".mp3", ".wav", ".ogg"}:
            return
        try:
            self._media_player.stop()
            self._media_player.setSource(QUrl.fromLocalFile(str(path)))
            self._audio_output.setVolume(1.0)
            self._media_player.play()
        except Exception:
            # Avoid spamming the status label; fail silently.
            pass

    def _browse_sound_file(self, kind: str) -> None:
        """Open a file dialog to choose a sound file for throttle/brake targets."""
        start_dir = Path(self._resolve_sound_path_text(kind)).expanduser().parent
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {kind} target sound",
            str(start_dir),
            "Audio Files (*.mp3 *.wav *.ogg);;All Files (*.*)",
        )
        if file_path:
            self._set_sound_file(kind, file_path, trigger_save=True)

    def _set_sound_file(self, kind: str, path: Path | str, *, trigger_save: bool) -> None:
        """Update the line edit for a sound file and optionally persist."""
        path = Path(path).expanduser()
        line_edit = self._sound_files[kind]
        line_edit.blockSignals(True)
        line_edit.setText(str(path))
        line_edit.blockSignals(False)
        if trigger_save:
            self._schedule_save_ui_settings()

    def _resolve_sound_path_text(self, kind: str) -> str:
        """Get the stored sound path text, falling back to the default."""
        line_edit = self._sound_files[kind]
        return line_edit.text().strip() or str(self._default_sound_path)

    def _sound_enabled(self, kind: str) -> bool:
        """Return whether a given target sound is enabled."""
        checkbox = self._sound_checkboxes[kind]
        return checkbox.isChecked()

    def _apply_sound_settings(
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
        self._set_sound_file("throttle", throttle_path or self._default_sound_path, trigger_save=False)
        self._set_sound_file("brake", brake_path or self._default_sound_path, trigger_save=False)

    def _build_sound_row(self, *, kind: str, label: str) -> QWidget:
        """Construct a row with path display, browse button, and enable checkbox."""
        checkbox = QCheckBox(f"Play {label.lower()}")
        checkbox.setChecked(True)
        checkbox.stateChanged.connect(self._schedule_save_ui_settings)
        self._sound_checkboxes[kind] = checkbox

        line_edit = QLineEdit()
        line_edit.setPlaceholderText(f"Select {label.lower()} (mp3 / ogg / wav)")
        line_edit.setReadOnly(True)
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

    def _update_bars(self, sample: TelemetrySample) -> None:
        """Update the vertical bar indicators beside the telemetry chart."""
        throttle_val = int(max(0.0, min(100.0, sample.throttle)))
        brake_val = int(max(0.0, min(100.0, sample.brake)))
        self.throttle_bar.setValue(throttle_val)
        self.brake_bar.setValue(brake_val)
        self.throttle_bar_label.setText(f"{throttle_val}%")
        self.brake_bar_label.setText(f"{brake_val}%")

    def _read_inputs(self) -> TelemetrySample:
        """
        Poll pedals + wheel devices (if available); otherwise use simulated data.
        """
        if hid_available() and (self.pedals_session.is_open or self.wheel_session.is_open):
            try:
                throttle = self.last_sample.throttle
                brake = self.last_sample.brake
                steering = self.last_sample.steering

                if self.pedals_session.is_open:
                    latest = self.pedals_session.read_latest_report(
                        report_len=self.pedals_report_len.value(),
                        max_reads=MAX_READS_PER_TICK,
                    )
                    if latest:
                        t_off = self.throttle_offset.value()
                        b_off = self.brake_offset.value()
                        if max(t_off, b_off) < len(latest):
                            throttle = self._scale_axis(latest[t_off], hi=255) * 100
                            brake = self._scale_axis(latest[b_off], hi=255) * 100

                if self.wheel_session.is_open:
                    latest = self.wheel_session.read_latest_report(
                        report_len=self.wheel_report_len.value(),
                        max_reads=MAX_READS_PER_TICK,
                    )
                    if latest:
                        s_off = self.steering_offset.value()
                        if s_off < len(latest):
                            steering_raw = self._apply_steering(latest[s_off])
                            steering = self._smooth_steering(steering_raw, self.last_sample.steering)

                self.last_sample = TelemetrySample(throttle, brake, steering)
                return self.last_sample
            except OSError:
                self.device_status.setText("HID read failed; using simulator.")

        # Simulator fallback: gentle waveforms starting at 0% to feed charts/training.
        self.sample_index += 1
        phase = (self.sample_index % 200) / 200.0
        throttle = max(0.0, min(100.0, (math.sin(phase * math.pi) ** 2) * 100))
        brake = max(0.0, min(100.0, (math.sin(phase * math.pi * 1.1) ** 2) * 100))
        steering_raw = max(-100.0, min(100.0, math.sin(phase * math.pi * 2.0) * 100))
        steering = self._smooth_steering(steering_raw, self.last_sample.steering)
        self.last_sample = TelemetrySample(throttle=throttle, brake=brake, steering=steering)
        return self.last_sample

    def _apply_steering(self, raw_value: int) -> float:
        """Convert raw steering byte to -100..100 using calibrated center/range."""
        center = float(self._steering_center or 128)
        span = float(max(1, self._steering_range or 127))
        normalized = (float(raw_value) - center) / span
        normalized = max(-1.0, min(1.0, normalized))
        return normalized * 100.0

    def _smooth_steering(self, raw: float, prev: float) -> float:
        """Lightly low-pass filter steering to avoid spiky traces."""
        raw = max(-100.0, min(100.0, raw))
        delta = raw - prev
        if abs(delta) < self._steering_deadband:
            return prev
        alpha = self._steering_alpha
        smoothed = prev + alpha * delta
        return max(-100.0, min(100.0, smoothed))

    @staticmethod
    def _scale_axis(value: int, lo: int = 0, hi: int = 255) -> float:
        """Normalize an integer axis value to [0,1] given bounds."""
        if hi == lo:
            return 0.0
        return max(0.0, min(1.0, (value - lo) / float(hi - lo)))
