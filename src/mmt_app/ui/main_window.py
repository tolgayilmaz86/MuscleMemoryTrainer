"""Main window for the Muscle Memory Trainer application.

Design notes:
- UI code stays here; input I/O lives in `mmt_app.input.*` modules.
- Calibration uses a simple "press to bind" heuristic (see `mmt_app.input.calibration`).
- Mappings are persisted to `config.ini` via `mmt_app.config`.
"""

from random import random
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QProgressBar,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from ..config import InputProfile, PedalsConfig, UiConfig, WheelConfig, load_input_profile, save_input_profile, save_ui_config
from ..input.calibration import detect_changing_byte
from ..input.hid_backend import HidDeviceInfo, HidSession, enumerate_devices, hid_available
from ..telemetry import TelemetrySample
from .telemetry_chart import TelemetryChart
from .static_brake_tab import StaticBrakeTab

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
        super().__init__()
        self.app_name = app_name
        self.version = version
        self.setWindowTitle(f"{self.app_name} - v{self.version}")
        self.resize(1080, 600)

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

        telemetry_tab = self._build_telemetry_tab()
        settings_tab = self._build_settings_tab()

        tabs = QTabWidget()
        tabs.addTab(telemetry_tab, "Telemetry")
        tabs.addTab(settings_tab, "Input Settings")
        tabs.addTab(self._build_static_brake_tab(), "Static Brake")
        self.setCentralWidget(tabs)

        self.timer = QTimer(interval=50)
        self.timer.timeout.connect(self._on_tick)

        self._ui_save_timer = QTimer()
        self._ui_save_timer.setSingleShot(True)
        self._ui_save_timer.timeout.connect(self._save_ui_settings)

        self._load_persisted_config()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        try:
            self.pedals_session.close()
            self.wheel_session.close()
        finally:
            super().closeEvent(event)

    def _build_telemetry_tab(self) -> QWidget:
        self.status_label = QLabel("Ready to train.")

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

        self.grid_step_combo = QComboBox()
        for step in range(10, 55, 5):
            self.grid_step_combo.addItem(f"{step}%", step)
        self.grid_step_combo.setCurrentIndex(0)
        self.grid_step_combo.currentIndexChanged.connect(self._on_grid_step_changed)
        self.grid_step_combo.currentIndexChanged.connect(self._schedule_save_ui_settings)

        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.toggle_stream)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_chart)

        controls = QFormLayout()
        controls.addRow("Throttle target", throttle_target_row)
        controls.addRow("Brake target", brake_target_row)
        controls.addRow("Grid division", self.grid_step_combo)

        control_bar = QHBoxLayout()
        control_bar.addWidget(self.start_button)
        control_bar.addWidget(self.reset_button)
        control_bar.addStretch()

        self.telemetry_chart = TelemetryChart(max_points=self.max_points)
        self._on_grid_step_changed()

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
        layout.addWidget(self.status_label)
        layout.addLayout(controls)
        layout.addLayout(control_bar)
        layout.addLayout(chart_row, stretch=1)

        container = QWidget()
        container.setLayout(layout)
        return container

    def _build_settings_tab(self) -> QWidget:
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

        refresh_btn = QPushButton("Refresh devices")
        refresh_btn.clicked.connect(self.refresh_devices)
        apply_btn = QPushButton("Use selection")
        apply_btn.clicked.connect(self.apply_device_selection)
        save_btn = QPushButton("Save to config.ini")
        save_btn.clicked.connect(self.save_current_mapping)

        cal_throttle_btn = QPushButton("Calibrate Throttle (press)")
        cal_throttle_btn.clicked.connect(lambda: self.start_calibration("pedals", "throttle"))
        cal_brake_btn = QPushButton("Calibrate Brake (press)")
        cal_brake_btn.clicked.connect(lambda: self.start_calibration("pedals", "brake"))
        cal_steer_btn = QPushButton("Calibrate Steering (turn)")
        cal_steer_btn.clicked.connect(lambda: self.start_calibration("wheel", "steering"))

        form = QFormLayout()
        form.addRow("Pedals device", self.pedals_device_combo)
        form.addRow("Pedals report length (bytes)", self.pedals_report_len)
        form.addRow("Throttle byte offset", self.throttle_offset)
        form.addRow("Brake byte offset", self.brake_offset)
        form.addRow("Wheel device", self.wheel_device_combo)
        form.addRow("Wheel report length (bytes)", self.wheel_report_len)
        form.addRow("Steering byte offset", self.steering_offset)

        buttons = QHBoxLayout()
        buttons.addWidget(refresh_btn)
        buttons.addWidget(apply_btn)
        buttons.addWidget(save_btn)
        buttons.addStretch()

        cal_buttons = QHBoxLayout()
        cal_buttons.addWidget(cal_throttle_btn)
        cal_buttons.addWidget(cal_brake_btn)
        cal_buttons.addWidget(cal_steer_btn)
        cal_buttons.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addLayout(cal_buttons)
        layout.addWidget(self.device_status)
        layout.addStretch()

        container = QWidget()
        container.setLayout(layout)

        self.refresh_devices()
        return container

    def _build_static_brake_tab(self) -> QWidget:
        return StaticBrakeTab(read_brake_percent=lambda: float(self.last_sample.brake))

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
            return

        self.devices = enumerate_devices()
        if not self.devices:
            self.device_status.setText("No HID devices detected; using simulator.")
            self.pedals_device_index = None
            self.wheel_device_index = None
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

    def apply_device_selection(self) -> None:
        """Open the currently selected pedals and wheel devices."""
        if not self.devices:
            self.pedals_device_index = None
            self.wheel_device_index = None
            self.pedals_device = None
            self.wheel_device = None
            self.device_status.setText("No devices available; simulator mode.")
            return
        self.pedals_device_index = int(self.pedals_device_combo.currentData())
        self.wheel_device_index = int(self.wheel_device_combo.currentData())
        if not hid_available():
            self.device_status.setText("hidapi not installed; simulator mode.")
            self.pedals_device_index = None
            self.wheel_device_index = None
            self.pedals_device = None
            self.wheel_device = None
            return

        try:
            self.pedals_device = self.devices[self.pedals_device_index]
            self.wheel_device = self.devices[self.wheel_device_index]

            self.pedals_session.open(self.pedals_device)
            self.wheel_session.open(self.wheel_device)

            self.device_status.setText("Using selected pedals + wheel devices via HID.")
        except Exception as exc:
            self.device_status.setText(f"HID open failed: {exc}; simulator mode.")
            self.pedals_device_index = None
            self.wheel_device_index = None
            self.pedals_device = None
            self.wheel_device = None
            self.pedals_session.close()
            self.wheel_session.close()

    def save_current_mapping(self) -> None:
        """Persist the current device IDs, report lengths, and byte offsets."""
        if not self.pedals_device or not self.wheel_device:
            self.device_status.setText("Select pedals and wheel devices first, then save.")
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
            )
            save_input_profile(InputProfile(pedals=pedals_cfg, wheel=wheel_cfg, ui=None))
            self._save_ui_settings()
            self.device_status.setText("Saved pedals + wheel mappings to config.ini.")
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

        if ui_cfg:
            self.throttle_target.setValue(max(0, min(100, ui_cfg.throttle_target)))
            self.brake_target.setValue(max(0, min(100, ui_cfg.brake_target)))
            self._set_grid_step(ui_cfg.grid_step_percent)

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
        step_percent = int(step_percent)
        for i in range(self.grid_step_combo.count()):
            if int(self.grid_step_combo.itemData(i)) == step_percent:
                self.grid_step_combo.setCurrentIndex(i)
                return
        self.grid_step_combo.setCurrentIndex(0)

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
        if not self.calibration_axis:
            return
        action = "press and hold" if self.calibration_axis in ("throttle", "brake") else "turn left/right"
        self.device_status.setText(f"Calibrating {self.calibration_axis}: now {action} for 2s...")
        self._baseline_samples, self._active_samples = self._active_samples, []
        QTimer.singleShot(2000, self._finish_calibration)

    def _finish_calibration(self) -> None:
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
        session = self.pedals_session if self.calibration_device == "pedals" else self.wheel_session
        if not session.is_open:
            return
        report_len = self.pedals_report_len.value() if self.calibration_device == "pedals" else self.wheel_report_len.value()
        report = session.read_latest_report(report_len=report_len, max_reads=MAX_READS_PER_TICK)
        if report is None:
            return
        self._active_samples.append(report)

    def toggle_stream(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.start_button.setText("Start")
            self.status_label.setText("Paused.")
        else:
            self.timer.start()
            self.start_button.setText("Pause")
            self.status_label.setText("Streaming telemetry...")

    def reset_chart(self) -> None:
        self.telemetry_chart.reset()
        self.status_label.setText("Chart reset.")
        self.telemetry_label.setText("Throttle 0% | Brake 0% | Steering 0 deg")
        self._update_bars(TelemetrySample(throttle=0.0, brake=0.0, steering=0.0))

    def _on_tick(self) -> None:
        sample = self._read_inputs()
        self.last_sample = sample
        self.telemetry_chart.append(sample)
        self.telemetry_chart.set_targets(
            throttle_target=float(self.throttle_target.value()),
            brake_target=float(self.brake_target.value()),
        )
        self._update_bars(sample)
        self._update_status(sample)

    def _on_grid_step_changed(self) -> None:
        step = int(self.grid_step_combo.currentData() or 10)
        self.telemetry_chart.set_grid_step(step_percent=step)

    def _schedule_save_ui_settings(self) -> None:
        # Debounce to avoid writing on every tick while the user drags a control.
        self._ui_save_timer.start(250)

    def _save_ui_settings(self) -> None:
        cfg = UiConfig(
            throttle_target=int(self.throttle_target.value()),
            brake_target=int(self.brake_target.value()),
            grid_step_percent=int(self.grid_step_combo.currentData() or 10),
        )
        save_ui_config(cfg)

    def _update_status(self, sample: TelemetrySample) -> None:
        parts: list[str] = []
        if self.pedals_session.is_open:
            parts.append(f"Pedals: {self.pedals_device_combo.currentText()}")
        if self.wheel_session.is_open:
            parts.append(f"Wheel: {self.wheel_device_combo.currentText()}")
        source = " | ".join(parts) if parts else "Simulator"
        self.telemetry_label.setText(f"[{source}]")

    def _update_bars(self, sample: TelemetrySample) -> None:
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
                            steering = self._scale_axis(latest[s_off], hi=255) * 200 - 100

                self.last_sample = TelemetrySample(throttle, brake, steering)
                return self.last_sample
            except OSError:
                self.device_status.setText("HID read failed; using simulator.")

        wobble = (self.sample_index % 200) / 2.0
        throttle = (50 + wobble + random() * 10) % 101
        brake = (30 + wobble * 0.5 + random() * 8) % 101
        steering = (wobble * 2 - 100) % 200 - 100
        self.last_sample = TelemetrySample(throttle=throttle, brake=brake, steering=steering)
        return self.last_sample

    @staticmethod
    def _scale_axis(value: int, lo: int = 0, hi: int = 255) -> float:
        if hi == lo:
            return 0.0
        return max(0.0, min(1.0, (value - lo) / float(hi - lo)))
