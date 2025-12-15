"""UI package for Muscle Memory Trainer.

Exports:
    MainWindow: Main application window.
    SettingsTab: Device configuration and calibration settings.
    StaticBrakeTab: Static brake training tab.
    ActiveBrakeTab: Active brake training tab.
    TelemetryChart: Live telemetry visualization.
"""

from .main_window import MainWindow
from .settings_tab import SettingsTab
from .static_brake_tab import StaticBrakeTab
from .active_brake_tab import ActiveBrakeTab
from .telemetry_chart import TelemetryChart

__all__ = [
    "MainWindow",
    "SettingsTab",
    "StaticBrakeTab",
    "ActiveBrakeTab",
    "TelemetryChart",
]
