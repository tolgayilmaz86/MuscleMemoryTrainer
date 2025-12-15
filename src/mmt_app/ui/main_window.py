"""Main window for the Muscle Memory Trainer application.

Design notes:
- MainWindow orchestrates tabs following Single Responsibility Principle.
- Settings functionality delegated to SettingsTab class.
- Input I/O lives in `mmt_app.input.*` modules.
- Mappings are persisted to `config.ini` via `mmt_app.config`.
"""

import math
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStatusBar,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import UiConfig, load_ui_config, save_ui_config
from ..telemetry import TelemetrySample
from .active_brake_tab import ActiveBrakeTab
from .settings_tab import SettingsTab
from .static_brake_tab import StaticBrakeTab
from .telemetry_chart import TelemetryChart
from .utils import (
    clamp,
    clamp_int,
    scale_axis,
    snap_to_step,
)


# Steering smoothing constants
_STEERING_SMOOTHING_ALPHA = 0.08
_STEERING_DEADBAND_DEGREES = 1.5

# UI defaults
_DEFAULT_UPDATE_RATE_HZ = 20
_DEFAULT_MAX_CHART_POINTS = 200
_DEFAULT_THROTTLE_TARGET = 60
_DEFAULT_BRAKE_TARGET = 40
_DEFAULT_GRID_STEP = 10
_UI_SAVE_DEBOUNCE_MS = 250
_MAX_READS_PER_TICK = 50


class MainWindow(QMainWindow):
    """Main application window for Muscle Memory Trainer.

    Orchestrates the application tabs:
    - Telemetry: Live chart for throttle/brake/steering.
    - Static Brake: Trace-following brake training.
    - Active Brake: Dynamic brake training with moving targets.
    - Settings: Device configuration, calibration, and sound settings.

    Follows Single Responsibility Principle by delegating settings
    functionality to the SettingsTab class.
    """

    def __init__(self, *, app_name: str, version: str) -> None:
        """Initialize the main window with tabs, timers, and state."""
        super().__init__()
        self._app_name = app_name
        self._version = version
        self.setWindowTitle(f"{self._app_name} - v{self._version}")
        self.resize(1080, 600)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        self._max_points = _DEFAULT_MAX_CHART_POINTS
        self._sample_index = 0
        self._last_sample = TelemetrySample(throttle=0.0, brake=0.0, steering=0.0)

        self._init_ui_state()
        self._init_sound_state()

        self._build_ui()
        self._setup_timers()
        self._load_persisted_config()
        self._update_status()

    def _init_ui_state(self) -> None:
        """Initialize UI configuration state."""
        self._update_rate = _DEFAULT_UPDATE_RATE_HZ
        self._show_steering = False
        self._steering_alpha = _STEERING_SMOOTHING_ALPHA
        self._steering_deadband = _STEERING_DEADBAND_DEGREES

    def _init_sound_state(self) -> None:
        """Initialize sound target tracking state."""
        self._throttle_target_hit = False
        self._brake_target_hit = False

    def _setup_timers(self) -> None:
        """Create and configure timers."""
        self._timer = QTimer(interval=50)
        self._timer.timeout.connect(self._on_tick)
        self._set_update_rate(self._update_rate, update_spin=True)

        self._ui_save_timer = QTimer()
        self._ui_save_timer.setSingleShot(True)
        self._ui_save_timer.timeout.connect(self._save_ui_settings)

    def _build_ui(self) -> None:
        """Build the main UI with tabs."""
        self._update_rate_row = self._create_update_rate_row()
        telemetry_tab = self._build_telemetry_tab()
        
        # Create settings tab with callbacks
        self._settings_tab = SettingsTab(
            on_status_update=self._on_settings_status_update,
            on_grid_step_changed=self._on_settings_grid_step_changed,
            on_update_rate_changed=self._on_settings_update_rate_changed,
            on_steering_visible_changed=self._on_settings_steering_visible_changed,
        )
        
        self._active_brake_tab = self._build_active_brake_tab()

        tabs = QTabWidget()
        tabs.addTab(telemetry_tab, "Telemetry")
        tabs.addTab(self._build_static_brake_tab(), "Static Brake")
        tabs.addTab(self._active_brake_tab, "Active Brake")
        tabs.addTab(self._settings_tab, "Settings")
        self.setCentralWidget(tabs)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Ensure HID sessions are closed before the window shuts down."""
        try:
            self._pedals_session.close()
            self._wheel_session.close()
        finally:
            super().closeEvent(event)

    def _build_telemetry_tab(self) -> QWidget:
        """Create the live telemetry tab with controls and chart."""
        self._throttle_target_slider = self._create_target_slider(
            default=_DEFAULT_THROTTLE_TARGET,
            object_name="throttleTargetSlider",
        )
        throttle_target_row = self._create_slider_row(
            self._throttle_target_slider,
            label_name="throttleTargetValue",
            initial_text=f"{_DEFAULT_THROTTLE_TARGET}%",
        )

        self._brake_target_slider = self._create_target_slider(
            default=_DEFAULT_BRAKE_TARGET,
            object_name="brakeTargetSlider",
        )
        brake_target_row = self._create_slider_row(
            self._brake_target_slider,
            label_name="brakeTargetValue",
            initial_text=f"{_DEFAULT_BRAKE_TARGET}%",
        )

        self._grid_step_slider = self._create_grid_slider()
        grid_row = self._create_slider_row(
            self._grid_step_slider,
            label_name="gridStepValue",
            initial_text=f"{_DEFAULT_GRID_STEP}%",
        )

        self._show_steering_checkbox = QCheckBox("Show steering trace")
        self._show_steering_checkbox.setChecked(self._show_steering)
        self._show_steering_checkbox.stateChanged.connect(self._on_show_steering_changed)

        self._start_button = QPushButton("Start")
        self._start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self._start_button.clicked.connect(self.toggle_stream)
        self._reset_button = QPushButton("Reset")
        self._reset_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self._reset_button.clicked.connect(self.reset_chart)

        from PySide6.QtWidgets import QFormLayout
        controls = QFormLayout()
        controls.addRow("Throttle target", throttle_target_row)
        controls.addRow("Brake target", brake_target_row)
        controls.addRow("Grid division", grid_row)
        controls.addRow("", self._show_steering_checkbox)
        controls.addRow("Update rate", self._update_rate_row)

        control_bar = QHBoxLayout()
        control_bar.addStretch()
        control_bar.addWidget(self._start_button)
        control_bar.addWidget(self._reset_button)
        control_bar.addStretch()

        self._telemetry_chart = TelemetryChart(max_points=self._max_points)
        self._on_grid_step_changed()
        self._telemetry_chart.set_steering_visible(self._show_steering)

        self._throttle_bar_label = QLabel("0%")
        self._throttle_bar_label.setObjectName("throttleBarLabel")
        self._brake_bar_label = QLabel("0%")
        self._brake_bar_label.setObjectName("brakeBarLabel")

        self._throttle_bar = self._create_vertical_progress_bar("throttleBar")
        self._brake_bar = self._create_vertical_progress_bar("brakeBar")

        bar_labels = QHBoxLayout()
        bar_labels.setContentsMargins(0, 0, 0, 0)
        bar_labels.setSpacing(12)
        bar_labels.addWidget(self._throttle_bar_label, alignment=Qt.AlignHCenter)
        bar_labels.addWidget(self._brake_bar_label, alignment=Qt.AlignHCenter)

        bar_columns = QHBoxLayout()
        bar_columns.setContentsMargins(0, 0, 0, 0)
        bar_columns.setSpacing(12)
        bar_columns.addWidget(self._throttle_bar)
        bar_columns.addWidget(self._brake_bar)

        bars_stack = QVBoxLayout()
        bars_stack.setContentsMargins(12, 0, 0, 0)
        bars_stack.setSpacing(6)
        bars_stack.addLayout(bar_labels)
        bars_stack.addLayout(bar_columns, stretch=1)
        bars_container = QWidget()
        bars_container.setLayout(bars_stack)
        bars_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        chart_row = QHBoxLayout()
        chart_row.addWidget(self._telemetry_chart.view, stretch=1)
        chart_row.addWidget(bars_container)

        layout = QVBoxLayout()
        layout.addLayout(controls)
        layout.addLayout(control_bar)
        layout.addLayout(chart_row, stretch=1)

        container = QWidget()
        container.setLayout(layout)
        return container

    def _build_static_brake_tab(self) -> QWidget:
        """Create the Static Brake training tab."""
        return StaticBrakeTab(read_brake_percent=self._read_brake_for_static_tab)

    def _build_active_brake_tab(self) -> QWidget:
        """Create the Active Brake training tab."""
        return ActiveBrakeTab(read_brake_percent=self._read_brake_for_active_tab)

    def _read_brake_for_active_tab(self) -> float:
        """Provide live brake input to the Active Brake tab.

        Works even when the main telemetry timer is paused.
        """
        sample = self._read_inputs()
        self._last_sample = sample
        return float(sample.brake)

    def _read_brake_for_static_tab(self) -> float:
        """Provide live brake input to Static Brake tab.

        Works even when the main telemetry timer is paused.
        """
        sample = self._read_inputs()
        self._last_sample = sample
        return float(sample.brake)

    # -------------------------------------------------------------------------
    # SettingsTab callback handlers
    # -------------------------------------------------------------------------

    def _on_settings_status_update(self, message: str) -> None:
        """Handle status updates from SettingsTab."""
        self._status_bar.showMessage(message, 5000)

    def _on_settings_grid_step_changed(self, step: int) -> None:
        """Handle grid step changes from SettingsTab."""
        if hasattr(self, "_telemetry_chart"):
            self._telemetry_chart.set_grid_step(step_percent=step)

    def _on_settings_update_rate_changed(self, hz: int) -> None:
        """Handle update rate changes from SettingsTab."""
        self._set_update_rate(hz, update_spin=True)

    def _on_settings_steering_visible_changed(self, visible: bool) -> None:
        """Handle steering visibility changes from SettingsTab."""
        self._set_show_steering(visible, update_checkbox=True)

    # -------------------------------------------------------------------------
    # UI event handlers
    # -------------------------------------------------------------------------

    def _on_update_rate_changed(self) -> None:
        """Handle slider changes by applying and persisting new update rate."""
        value = int(self._update_rate_slider.value())
        self._update_rate_label.setText(f"{value} Hz")
        self._set_update_rate(value)
        self._schedule_save_ui_settings()

    def _on_show_steering_changed(self) -> None:
        """Toggle steering visibility and persist the setting."""
        self._show_steering = self._show_steering_checkbox.isChecked()
        self._telemetry_chart.set_steering_visible(self._show_steering)
        self._schedule_save_ui_settings()

    def _create_update_rate_row(self) -> QWidget:
        """Build the update rate slider + label UI row."""
        self._update_rate_slider = QSlider(Qt.Horizontal)
        self._update_rate_slider.setRange(5, 120)
        self._update_rate_slider.setTickInterval(5)
        self._update_rate_slider.setTickPosition(QSlider.TicksBelow)
        self._update_rate_slider.setSingleStep(1)
        self._update_rate_slider.setPageStep(5)
        self._update_rate_slider.setValue(self._update_rate)
        self._update_rate_slider.valueChanged.connect(self._on_update_rate_changed)

        self._update_rate_label = QLabel(f"{self._update_rate} Hz")
        self._update_rate_label.setMinimumWidth(48)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._update_rate_slider, stretch=1)
        layout.addWidget(self._update_rate_label)
        return row
            
    # -------------------------------------------------------------------------
    # Core functionality
    # -------------------------------------------------------------------------

    def toggle_stream(self) -> None:
        """Start or pause the main telemetry timer."""
        if self._timer.isActive():
            self._timer.stop()
            self._start_button.setText("Start")
            self._start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        else:
            self._timer.start()
            self._start_button.setText("Pause")
            self._start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))

    def reset_chart(self) -> None:
        """Clear the telemetry chart and reset state."""
        self._telemetry_chart.reset()
        self._update_bars(TelemetrySample(throttle=0.0, brake=0.0, steering=0.0))
        self._throttle_target_hit = False
        self._brake_target_hit = False
        self._update_status()

    def _on_tick(self) -> None:
        """Timer tick: read inputs, update charts, play sounds, and status."""
        sample = self._read_inputs()
        self._last_sample = sample
        self._telemetry_chart.append(sample)
        self._telemetry_chart.set_targets(
            throttle_target=float(self._throttle_target_slider.value()),
            brake_target=float(self._brake_target_slider.value()),
        )
        self._update_bars(sample)
        self._maybe_play_target_sound(sample)
        self._update_status()

    def _on_grid_step_changed(self) -> None:
        """Update the telemetry grid step when the slider changes."""
        step = snap_to_step(self._grid_step_slider.value(), 5)
        step = clamp_int(step, 5, 50)
        if step != self._grid_step_slider.value():
            self._grid_step_slider.blockSignals(True)
            self._grid_step_slider.setValue(step)
            self._grid_step_slider.blockSignals(False)
        self._update_grid_step_label(step)
        self._telemetry_chart.set_grid_step(step_percent=step)

    def _schedule_save_ui_settings(self) -> None:
        """Debounce UI settings save to avoid excessive writes."""
        self._ui_save_timer.start(_UI_SAVE_DEBOUNCE_MS)

    def _set_update_rate(self, hz: int, *, update_spin: bool = False) -> None:
        """Apply the requested update rate to timers and sync UI controls."""
        hz = clamp_int(hz, 5, 120)
        interval_ms = max(1, int(1000 / hz))
        self._update_rate = hz
        self._timer.setInterval(interval_ms)
        if hasattr(self, "_active_brake_tab"):
            try:
                self._active_brake_tab.set_update_rate(hz)
            except Exception:
                pass
        if update_spin and hasattr(self, "_update_rate_slider"):
            self._update_rate_slider.blockSignals(True)
            self._update_rate_slider.setValue(hz)
            self._update_rate_slider.blockSignals(False)
        if hasattr(self, "_update_rate_label"):
            self._update_rate_label.setText(f"{hz} Hz")

    def _set_show_steering(self, visible: bool, *, update_checkbox: bool = False) -> None:
        """Apply steering visibility to the chart and sync the checkbox."""
        self._show_steering = bool(visible)
        if hasattr(self, "_telemetry_chart"):
            self._telemetry_chart.set_steering_visible(self._show_steering)
        if update_checkbox and hasattr(self, "_show_steering_checkbox"):
            self._show_steering_checkbox.blockSignals(True)
            self._show_steering_checkbox.setChecked(self._show_steering)
            self._show_steering_checkbox.blockSignals(False)

    def _set_grid_step(self, step_percent: int) -> None:
        """Set the telemetry grid step via the slider, snapping to 5% increments."""
        step_percent = snap_to_step(clamp_int(step_percent, 5, 50), 5)
        if hasattr(self, "_grid_step_slider"):
            try:
                self._grid_step_slider.blockSignals(True)
                self._grid_step_slider.setValue(step_percent)
            finally:
                self._grid_step_slider.blockSignals(False)
        self._update_grid_step_label(step_percent)
        if hasattr(self, "_telemetry_chart"):
            self._telemetry_chart.set_grid_step(step_percent=step_percent)

    def _update_grid_step_label(self, step_percent: int) -> None:
        """Update the grid step label text."""
        if hasattr(self, "_grid_step_label"):
            self._grid_step_label.setText(f"{int(step_percent)}%")

    def _save_ui_settings(self) -> None:
        """Persist UI-related settings (targets, grid, update rate)."""
        cfg = UiConfig(
            throttle_target=int(self._throttle_target_slider.value()),
            brake_target=int(self._brake_target_slider.value()),
            grid_step_percent=int(self._grid_step_slider.value()),
            update_hz=int(self._update_rate_slider.value()),
            show_steering=bool(self._show_steering_checkbox.isChecked()),
            throttle_sound_enabled=self._settings_tab.sound_enabled("throttle"),
            throttle_sound_path=self._settings_tab.resolve_sound_path("throttle"),
            brake_sound_enabled=self._settings_tab.sound_enabled("brake"),
            brake_sound_path=self._settings_tab.resolve_sound_path("brake"),
        )
        save_ui_config(cfg)

    def _load_persisted_config(self) -> None:
        """Load UI settings from config.ini."""
        try:
            ui_cfg = load_ui_config()
            if ui_cfg:
                self._throttle_target_slider.setValue(clamp_int(ui_cfg.throttle_target, 0, 100))
                self._brake_target_slider.setValue(clamp_int(ui_cfg.brake_target, 0, 100))
                self._set_grid_step(ui_cfg.grid_step_percent)
                self._set_update_rate(ui_cfg.update_hz, update_spin=True)
                self._set_show_steering(ui_cfg.show_steering, update_checkbox=True)
                self._settings_tab.apply_sound_settings(
                    throttle_enabled=ui_cfg.throttle_sound_enabled,
                    throttle_path=ui_cfg.throttle_sound_path,
                    brake_enabled=ui_cfg.brake_sound_enabled,
                    brake_path=ui_cfg.brake_sound_path,
                )
            else:
                self._set_update_rate(self._update_rate, update_spin=True)
                self._set_show_steering(self._show_steering, update_checkbox=True)
        except Exception:
            self._set_update_rate(self._update_rate, update_spin=True)
            self._set_show_steering(self._show_steering, update_checkbox=True)

    def _update_status(self) -> None:
        """Update the status bar with current device usage."""
        parts: list[str] = []
        if self._settings_tab.pedals_session.is_open:
            parts.append("Pedals: connected")
        if self._settings_tab.wheel_session.is_open:
            parts.append("Wheel: connected")
        message = " | ".join(parts) if parts else "Simulator mode (no devices streaming)"
        self._status_bar.showMessage(message)

    # -------------------------------------------------------------------------
    # Sound management
    # -------------------------------------------------------------------------

    def _maybe_play_target_sound(self, sample: TelemetrySample) -> None:
        """Play sounds when throttle/brake cross their targets."""
        throttle_target = float(self._throttle_target_slider.value())
        brake_target = float(self._brake_target_slider.value())
        self._update_target_flag(sample.throttle, throttle_target, "_throttle_target_hit", "throttle")
        self._update_target_flag(sample.brake, brake_target, "_brake_target_hit", "brake")

    def _update_target_flag(self, value: float, target: float, flag_attr: str, kind: str) -> None:
        """Track threshold crossings for a single axis and trigger sound once."""
        reset_threshold = max(0.0, target - 5.0)
        already_hit = getattr(self, flag_attr)
        if not self._settings_tab.sound_enabled(kind):
            setattr(self, flag_attr, False)
            return
        if value >= target and not already_hit:
            self._settings_tab.play_target_sound(kind)
            setattr(self, flag_attr, True)
        elif value < reset_threshold:
            setattr(self, flag_attr, False)

    # -------------------------------------------------------------------------
    # Input handling
    # -------------------------------------------------------------------------

    def _update_bars(self, sample: TelemetrySample) -> None:
        """Update the vertical bar indicators beside the telemetry chart."""
        throttle_val = int(clamp(sample.throttle, 0.0, 100.0))
        brake_val = int(clamp(sample.brake, 0.0, 100.0))
        self._throttle_bar.setValue(throttle_val)
        self._brake_bar.setValue(brake_val)
        self._throttle_bar_label.setText(f"{throttle_val}%")
        self._brake_bar_label.setText(f"{brake_val}%")

    def _read_inputs(self) -> TelemetrySample:
        """Poll pedals + wheel devices (if available); otherwise use simulated data."""
        from mmt_app.input.hid_backend import hid_available
        
        pedals_session = self._settings_tab.pedals_session
        wheel_session = self._settings_tab.wheel_session
        
        if hid_available() and (pedals_session.is_open or wheel_session.is_open):
            try:
                throttle = self._last_sample.throttle
                brake = self._last_sample.brake
                steering = self._last_sample.steering

                if pedals_session.is_open:
                    latest = pedals_session.read_latest_report(
                        report_len=self._settings_tab.pedals_report_len,
                        max_reads=_MAX_READS_PER_TICK,
                    )
                    if latest:
                        t_off = self._settings_tab.throttle_offset
                        b_off = self._settings_tab.brake_offset
                        if max(t_off, b_off) < len(latest):
                            throttle = scale_axis(latest[t_off]) * 100
                            brake = scale_axis(latest[b_off]) * 100

                if wheel_session.is_open:
                    latest = wheel_session.read_latest_report(
                        report_len=self._settings_tab.wheel_report_len,
                        max_reads=_MAX_READS_PER_TICK,
                    )
                    if latest:
                        s_off = self._settings_tab.steering_offset
                        if s_off < len(latest):
                            steering_raw = self._apply_steering(latest[s_off])
                            steering = self._smooth_steering(steering_raw, self._last_sample.steering)

                self._last_sample = TelemetrySample(throttle, brake, steering)
                return self._last_sample
            except OSError:
                pass  # Fall through to simulated sample

        return self._generate_simulated_sample()

    def _generate_simulated_sample(self) -> TelemetrySample:
        """Generate simulated telemetry data for testing without hardware."""
        self._sample_index += 1
        phase = (self._sample_index % 200) / 200.0
        throttle = clamp((math.sin(phase * math.pi) ** 2) * 100, 0.0, 100.0)
        brake = clamp((math.sin(phase * math.pi * 1.1) ** 2) * 100, 0.0, 100.0)
        steering_raw = clamp(math.sin(phase * math.pi * 2.0) * 100, -100.0, 100.0)
        steering = self._smooth_steering(steering_raw, self._last_sample.steering)
        self._last_sample = TelemetrySample(throttle=throttle, brake=brake, steering=steering)
        return self._last_sample

    def _apply_steering(self, raw_value: int) -> float:
        """Convert raw steering byte to -100..100 using calibrated center/range."""
        center = float(self._settings_tab.steering_center or 128)
        span = float(max(1, self._settings_tab.steering_range or 127))
        normalized = clamp((float(raw_value) - center) / span, -1.0, 1.0)
        return normalized * 100.0

    def _smooth_steering(self, raw: float, prev: float) -> float:
        """Lightly low-pass filter steering to avoid spiky traces."""
        raw = clamp(raw, -100.0, 100.0)
        delta = raw - prev
        if abs(delta) < self._steering_deadband:
            return prev
        smoothed = prev + self._steering_alpha * delta
        return clamp(smoothed, -100.0, 100.0)

    # -------------------------------------------------------------------------
    # Helper methods for UI construction
    # -------------------------------------------------------------------------

    def _create_target_slider(
        self, *, default: int, object_name: str
    ) -> QSlider:
        """Create a target percentage slider (0-100%)."""
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setSingleStep(1)
        slider.setPageStep(5)
        slider.setTickInterval(10)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setValue(default)
        slider.setObjectName(object_name)
        slider.valueChanged.connect(self._schedule_save_ui_settings)
        return slider

    def _create_slider_row(
        self, slider: QSlider, *, label_name: str, initial_text: str
    ) -> QWidget:
        """Create a row with a slider and value label."""
        label = QLabel(initial_text)
        label.setObjectName(label_name)
        label.setMinimumWidth(52)
        slider.valueChanged.connect(lambda v: label.setText(f"{int(v)}%"))

        # Store reference to label for grid step updates
        if "grid" in label_name.lower():
            self._grid_step_label = label

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(slider, stretch=1)
        layout.addWidget(label)
        return row

    def _create_grid_slider(self) -> QSlider:
        """Create the grid step slider."""
        slider = QSlider(Qt.Horizontal)
        slider.setRange(5, 50)
        slider.setSingleStep(5)
        slider.setPageStep(5)
        slider.setTickInterval(5)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setValue(_DEFAULT_GRID_STEP)
        slider.valueChanged.connect(self._on_grid_step_changed)
        slider.valueChanged.connect(self._schedule_save_ui_settings)
        return slider

    def _create_vertical_progress_bar(self, object_name: str) -> QProgressBar:
        """Create a vertical progress bar for input visualization."""
        bar = QProgressBar()
        bar.setOrientation(Qt.Vertical)
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setObjectName(object_name)
        bar.setFixedWidth(28)
        bar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        return bar

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Clean up resources when the window is closed."""
        self._settings_tab.close_sessions()
        super().closeEvent(event)
