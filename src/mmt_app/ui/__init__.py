"""UI package for Muscle Memory Trainer.

Exports:
    MainWindow: Main application window.
    AboutTab: Application information and credits.
    SettingsTab: Device configuration and calibration settings.
    TelemetryTab: Live telemetry visualization tab.
    TrailBrakeTab: Trail brake training tab.
    ActiveBrakeTab: Active brake training tab.
    ThresholdTrainingTab: Threshold training game tab.
    TelemetryChart: Live telemetry chart component.
"""

from .about_tab import AboutTab
from .main_window import MainWindow
from .settings_tab import SettingsTab
from .telemetry_tab import TelemetryTab
from .trail_brake_tab import TrailBrakeTab
from .active_brake_tab import ActiveBrakeTab
from .threshold_training_tab import ThresholdTrainingTab
from .telemetry_chart import TelemetryChart

__all__ = [
    "MainWindow",
    "AboutTab",
    "SettingsTab",
    "TelemetryTab",
    "TrailBrakeTab",
    "ActiveBrakeTab",
    "ThresholdTrainingTab",
    "TelemetryChart",
]
