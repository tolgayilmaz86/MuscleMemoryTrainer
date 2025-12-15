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
    QMainWindow,
    QStatusBar,
    QTabWidget,
)

from ..config import UiConfig, load_ui_config, save_ui_config
from ..telemetry import TelemetrySample
from .about_tab import AboutTab
from .active_brake_tab import ActiveBrakeTab
from .settings_tab import SettingsTab
from .telemetry_tab import TelemetryTab
from .trail_brake_tab import TrailBrakeTab
from .utils import (
    clamp,
    clamp_int,
    scale_axis,
)


# Steering smoothing constants
_STEERING_SMOOTHING_ALPHA = 0.08
_STEERING_DEADBAND_DEGREES = 1.5

# UI defaults
_DEFAULT_UPDATE_RATE_HZ = 20
_DEFAULT_MAX_CHART_POINTS = 200
_UI_SAVE_DEBOUNCE_MS = 250
_MAX_READS_PER_TICK = 50


class MainWindow(QMainWindow):
    """Main application window for Muscle Memory Trainer.

    Orchestrates the application tabs:
    - Telemetry: Live chart for throttle/brake/steering.
    - Trail Brake: Trace-following brake training.
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
        # Create settings tab first (has targets and grid controls)
        self._settings_tab = SettingsTab(
            on_status_update=self._on_settings_status_update,
            on_targets_changed=self._on_settings_targets_changed,
            on_grid_step_changed=self._on_settings_grid_step_changed,
            on_update_rate_changed=self._on_settings_update_rate_changed,
            on_steering_visible_changed=self._on_settings_steering_visible_changed,
        )

        # Create telemetry tab
        self._telemetry_tab = TelemetryTab()
        self._telemetry_tab.connect_start_stop(self._on_telemetry_start_stop)
        self._telemetry_tab.connect_reset(self._on_telemetry_reset)
        
        self._active_brake_tab = ActiveBrakeTab(read_brake_percent=self._read_brake_for_active_tab)

        self._about_tab = AboutTab(app_name=self._app_name, version=self._version)

        tabs = QTabWidget()
        tabs.addTab(self._telemetry_tab, "Telemetry")
        tabs.addTab(TrailBrakeTab(read_brake_percent=self._read_brake_for_static_tab), "Trail Brake")
        tabs.addTab(self._active_brake_tab, "Active Brake")
        tabs.addTab(self._settings_tab, "Settings")
        tabs.addTab(self._about_tab, "About")
        self.setCentralWidget(tabs)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Ensure HID sessions are closed and settings saved before shutdown."""
        self._save_ui_settings()
        self._settings_tab.close_sessions()
        super().closeEvent(event)

    def _read_brake_for_active_tab(self) -> float:
        """Provide live brake input to the Active Brake tab.

        Works even when the main telemetry timer is paused.
        """
        sample = self._read_inputs()
        self._last_sample = sample
        return float(sample.brake)

    def _read_brake_for_static_tab(self) -> float:
        """Provide live brake input to Trail Brake tab.

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

    def _on_settings_targets_changed(self) -> None:
        """Handle throttle/brake target changes from SettingsTab."""
        if hasattr(self, "_telemetry_tab"):
            self._telemetry_tab.set_throttle_target(self._settings_tab.throttle_target)
            self._telemetry_tab.set_brake_target(self._settings_tab.brake_target)

    def _on_settings_grid_step_changed(self, step: int) -> None:
        """Handle grid step changes from SettingsTab."""
        if hasattr(self, "_telemetry_tab"):
            self._telemetry_tab.set_grid_step(step)

    def _on_settings_update_rate_changed(self, hz: int) -> None:
        """Handle update rate changes from SettingsTab."""
        self._set_update_rate(hz, update_spin=True)

    def _on_settings_steering_visible_changed(self, visible: bool) -> None:
        """Handle steering visibility changes from SettingsTab."""
        self._set_show_steering(visible, update_checkbox=True)

    # -------------------------------------------------------------------------
    # Core functionality
    # -------------------------------------------------------------------------

    def _on_telemetry_start_stop(self, start: bool) -> None:
        """Handle start/stop from telemetry tab."""
        if start:
            self._timer.start()
            self._telemetry_tab.set_streaming(True)
        else:
            self._timer.stop()
            self._telemetry_tab.set_streaming(False)

    def _on_telemetry_reset(self) -> None:
        """Handle reset from telemetry tab."""
        self._telemetry_tab.reset()
        self._throttle_target_hit = False
        self._brake_target_hit = False
        self._update_status()

    def _on_tick(self) -> None:
        """Timer tick: read inputs, update charts, play sounds, and status."""
        sample = self._read_inputs()
        self._last_sample = sample
        self._telemetry_tab.append_sample(sample)
        self._maybe_play_target_sound(sample)
        self._update_status()

    def _schedule_save_ui_settings(self) -> None:
        """Debounce UI settings save to avoid excessive writes."""
        self._ui_save_timer.start(_UI_SAVE_DEBOUNCE_MS)

    def _set_update_rate(self, hz: int, *, update_spin: bool = False) -> None:
        """Apply the requested update rate to timers."""
        hz = clamp_int(hz, 5, 120)
        interval_ms = max(1, int(1000 / hz))
        self._update_rate = hz
        self._timer.setInterval(interval_ms)
        if hasattr(self, "_active_brake_tab"):
            try:
                self._active_brake_tab.set_update_rate(hz)
            except Exception:
                pass

    def _set_show_steering(self, visible: bool, *, update_checkbox: bool = False) -> None:
        """Apply steering visibility to the chart."""
        self._show_steering = bool(visible)
        if hasattr(self, "_telemetry_tab"):
            self._telemetry_tab.set_steering_visible(self._show_steering)

    def _set_grid_step(self, step_percent: int) -> None:
        """Set the telemetry grid step, snapping to 10% increments."""
        step_percent = max(10, min(50, (step_percent // 10) * 10))
        if hasattr(self, "_telemetry_tab"):
            self._telemetry_tab.set_grid_step(step_percent)

    def _save_ui_settings(self) -> None:
        """Persist UI-related settings (targets, grid, update rate, window size)."""
        cfg = UiConfig(
            throttle_target=self._settings_tab.throttle_target,
            brake_target=self._settings_tab.brake_target,
            grid_step_percent=self._settings_tab.grid_step,
            update_hz=self._update_rate,
            show_steering=self._show_steering,
            throttle_sound_enabled=self._settings_tab.sound_enabled("throttle"),
            throttle_sound_path=self._settings_tab.resolve_sound_path("throttle"),
            brake_sound_enabled=self._settings_tab.sound_enabled("brake"),
            brake_sound_path=self._settings_tab.resolve_sound_path("brake"),
            window_width=self.width(),
            window_height=self.height(),
        )
        save_ui_config(cfg)

    def _load_persisted_config(self) -> None:
        """Load UI settings from config.ini."""
        try:
            ui_cfg = load_ui_config()
            if ui_cfg:
                # Set targets in settings tab (which propagates to telemetry tab)
                self._settings_tab.set_throttle_target(ui_cfg.throttle_target)
                self._settings_tab.set_brake_target(ui_cfg.brake_target)
                self._settings_tab.set_grid_step(ui_cfg.grid_step_percent)
                # Also set directly on telemetry tab
                self._telemetry_tab.set_throttle_target(ui_cfg.throttle_target)
                self._telemetry_tab.set_brake_target(ui_cfg.brake_target)
                self._telemetry_tab.set_grid_step(ui_cfg.grid_step_percent)
                self._set_update_rate(ui_cfg.update_hz)
                self._set_show_steering(ui_cfg.show_steering)
                self._settings_tab.apply_sound_settings(
                    throttle_enabled=ui_cfg.throttle_sound_enabled,
                    throttle_path=ui_cfg.throttle_sound_path,
                    brake_enabled=ui_cfg.brake_sound_enabled,
                    brake_path=ui_cfg.brake_sound_path,
                )
                self.resize(ui_cfg.window_width, ui_cfg.window_height)
            else:
                self._set_update_rate(self._update_rate)
                self._set_show_steering(self._show_steering)
        except Exception:
            self._set_update_rate(self._update_rate)
            self._set_show_steering(self._show_steering)

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
        throttle_target = float(self._settings_tab.throttle_target)
        brake_target = float(self._settings_tab.brake_target)
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
    # Cleanup
    # -------------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Clean up resources when the window is closed."""
        self._settings_tab.close_sessions()
        super().closeEvent(event)
