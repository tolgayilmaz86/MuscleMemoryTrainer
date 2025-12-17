"""Threshold Training Tab for muscle memory training.

This module provides a game-like interface for training brake pressure thresholds.
Random target values appear on the right side and float to the left, while the user
attempts to match them with their brake input.

Design Principles:
- Single Responsibility: Each class has one clear purpose
- Open/Closed: Extensible via configuration, closed for modification
- Interface Segregation: Uses Callable for dependency injection
- Dependency Inversion: Depends on abstractions (Callable) not concrete implementations
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, List, Protocol

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QScatterSeries, QValueAxis
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    ThresholdTrainingConfig,
    load_threshold_training_config,
    save_threshold_training_config,
    DEFAULT_THRESHOLD_SPEED,
    DEFAULT_THRESHOLD_STEP,
)
from .watermark_chart_view import WatermarkChartView
from .utils import AXIS_MAX, AXIS_MIN, clamp


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

_MIN_STEP = 5
_MAX_STEP = 25
_MIN_SPEED_HZ = 30
_MAX_SPEED_HZ = 120
_TIMER_INTERVAL_MS = 40
_DEFAULT_SCROLL_SPEED = 1.5
_AXIS_X_MAX = 100.0
_TARGET_LIFETIME_X = 100.0  # X distance a target travels before removal
_INDICATOR_SIZE = 12.0  # Size of the brake position indicator
_TARGET_MARKER_SIZE = 40.0  # Size of target markers


# -----------------------------------------------------------------------------
# Data Classes for State Management (Single Responsibility)
# -----------------------------------------------------------------------------


@dataclass
class FloatingTarget:
    """Represents a single floating target bubble."""

    x: float
    value: int  # Target brake percentage (0-100)

    def move_left(self, speed: float) -> None:
        """Move the target leftward by the given speed."""
        self.x -= speed

    def is_expired(self) -> bool:
        """Check if the target has moved off screen."""
        return self.x < 0


@dataclass
class ThresholdTrainingState:
    """Internal state for the threshold training tab."""

    running: bool = False
    targets: List[FloatingTarget] = field(default_factory=list)
    current_brake: float = 0.0
    spawn_counter: int = 0


# -----------------------------------------------------------------------------
# Target Generator (Open/Closed Principle - Strategy Pattern)
# -----------------------------------------------------------------------------


class TargetGenerator(Protocol):
    """Protocol for generating target values."""

    def generate(self) -> int:
        """Generate a target value."""
        ...


class StepBasedTargetGenerator:
    """Generates targets based on configurable step values.

    Follows Open/Closed Principle: behavior can be changed via configuration
    without modifying the class itself.
    """

    def __init__(self, step: int = 10, min_val: int = 5, max_val: int = 100) -> None:
        """Initialize the generator with step configuration.

        Args:
            step: The step increment between possible values (5, 10, 15, 20, 25).
            min_val: Minimum value for targets.
            max_val: Maximum value for targets.
        """
        self._step = max(_MIN_STEP, min(_MAX_STEP, step))
        self._min_val = min_val
        self._max_val = max_val

    @property
    def step(self) -> int:
        """Get the current step value."""
        return self._step

    @step.setter
    def step(self, value: int) -> None:
        """Set the step value with bounds checking."""
        self._step = max(_MIN_STEP, min(_MAX_STEP, value))

    def generate(self) -> int:
        """Generate a random target value aligned to the step.

        Returns:
            A random value from [step, step*2, ..., max_val] that's divisible by step.
        """
        # Generate values that are multiples of step, e.g., for step=10: 10, 20, ..., 100
        possible_values = list(range(self._step, self._max_val + 1, self._step))
        if not possible_values:
            return self._step
        return random.choice(possible_values)


# -----------------------------------------------------------------------------
# Custom Chart View with Target Labels (Single Responsibility)
# -----------------------------------------------------------------------------


class LabeledTargetChartView(QChartView):
    """Chart view that draws labels centered on target scatter points.

    This custom view renders text labels directly on top of target markers,
    ensuring they are always visible and properly centered. Also supports
    a large watermark display like WatermarkChartView.
    """

    def __init__(self, chart: QChart, targets_series: QScatterSeries) -> None:
        """Initialize the labeled chart view.

        Args:
            chart: The chart to display.
            targets_series: The scatter series containing target points.
        """
        super().__init__(chart)
        self._targets_series = targets_series
        self._label_font = QFont()
        self._label_font.setBold(True)
        self._label_font.setPixelSize(12)
        self._label_color = QColor("#ffffff")
        self.setRenderHint(QPainter.Antialiasing)

        # Watermark support
        self._watermark_text = ""
        self._watermark_visible = True
        self._watermark_font = QFont()
        self._watermark_font.setBold(True)
        self._watermark_color = QColor(148, 163, 184, 100)

    def set_watermark_text(self, text: str) -> None:
        """Set the watermark text to display."""
        self._watermark_text = str(text)
        self.viewport().update()

    def set_watermark_visible(self, visible: bool) -> None:
        """Set whether the watermark is visible."""
        self._watermark_visible = bool(visible)
        self.viewport().update()

    def paintEvent(self, event) -> None:
        """Paint the chart, watermark, and target labels."""
        super().paintEvent(event)
        self._draw_watermark()
        self._draw_target_labels()

    def _draw_watermark(self) -> None:
        """Draw the large watermark in the center of the chart."""
        if not self._watermark_visible or not self._watermark_text:
            return

        chart = self.chart()
        if chart is None:
            return

        plot_area = chart.plotArea()
        if plot_area.isEmpty():
            return

        painter = QPainter(self.viewport())

        # Calculate font size based on plot area
        font = QFont(self._watermark_font)
        font_size = int(plot_area.height() * 0.6)
        font.setPixelSize(max(24, font_size))
        painter.setFont(font)
        painter.setPen(self._watermark_color)

        # Draw centered in plot area, slightly above center
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(self._watermark_text)
        text_height = metrics.height()

        x = int(plot_area.center().x() - text_width / 2)
        y = int(plot_area.center().y() + text_height / 4 - plot_area.height() * 0.05)

        painter.drawText(x, y, self._watermark_text)
        painter.end()

    def _draw_target_labels(self) -> None:
        """Draw value labels centered on each target marker."""
        chart = self.chart()
        if chart is None:
            return

        plot_area = chart.plotArea()
        if plot_area.isEmpty():
            return

        painter = QPainter(self.viewport())
        painter.setFont(self._label_font)
        painter.setPen(self._label_color)

        metrics = QFontMetrics(self._label_font)

        for i in range(self._targets_series.count()):
            point = self._targets_series.at(i)
            # Map data coordinates to pixel coordinates
            pixel_pos = chart.mapToPosition(point, self._targets_series)

            # Get the label text (Y value = threshold percentage)
            label = str(int(point.y()))

            # Calculate text dimensions for centering
            text_width = metrics.horizontalAdvance(label)
            text_height = metrics.height()

            # Draw text centered on the marker
            x = int(pixel_pos.x() - text_width / 2)
            y = int(pixel_pos.y() + text_height / 4)  # Slight adjustment for visual centering

            painter.drawText(x, y, label)

        painter.end()


# -----------------------------------------------------------------------------
# Chart Components (Single Responsibility)
# -----------------------------------------------------------------------------


class ThresholdChartBuilder:
    """Builds and configures the threshold training chart.

    Single Responsibility: Only handles chart creation and configuration.
    """

    @staticmethod
    def create_chart() -> tuple[
        QChart,
        QScatterSeries,
        QScatterSeries,
        QLineSeries,
        QValueAxis,
        QValueAxis,
    ]:
        """Create the chart with all necessary series.

        Returns:
            Tuple of (chart, target_series, indicator_series, brake_line_series, x_axis, y_axis)
        """
        # Target bubbles (scatter series for circular markers)
        series_targets = QScatterSeries()
        series_targets.setName("Targets")
        series_targets.setMarkerSize(_TARGET_MARKER_SIZE)
        series_targets.setColor(QColor("#ef4444"))  # Red circles
        series_targets.setBorderColor(QColor("#dc2626"))

        # Brake position indicator (smaller circle at current brake value)
        series_indicator = QScatterSeries()
        series_indicator.setName("Brake Position")
        series_indicator.setMarkerSize(_INDICATOR_SIZE)
        series_indicator.setColor(QColor(56, 189, 248, 200))  # Cyan
        series_indicator.setBorderColor(QColor(14, 165, 233))

        # Horizontal line showing current brake level
        series_brake_line = QLineSeries()
        series_brake_line.setName("Current Brake %")
        pen = QPen(QColor(56, 189, 248, 140), 3)
        series_brake_line.setPen(pen)

        chart = QChart()
        chart.addSeries(series_brake_line)
        chart.addSeries(series_targets)
        chart.addSeries(series_indicator)

        # Configure axes
        axis_x = QValueAxis()
        axis_x.setRange(0, _AXIS_X_MAX)
        axis_x.setLabelFormat("%d")
        axis_x.setLabelsVisible(False)
        axis_x.setGridLineVisible(False)

        axis_y = QValueAxis()
        axis_y.setRange(float(AXIS_MIN), float(AXIS_MAX))
        axis_y.setLabelFormat("%d")
        axis_y.setTitleText("Brake %")
        axis_y.setTickCount(11)

        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)

        for series in (series_targets, series_indicator, series_brake_line):
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)

        chart.legend().setVisible(True)
        chart.setTitle("Threshold Training")

        return chart, series_targets, series_indicator, series_brake_line, axis_x, axis_y


# -----------------------------------------------------------------------------
# Main Tab Widget (Composition over Inheritance)
# -----------------------------------------------------------------------------


class ThresholdTrainingTab(QWidget):
    """Threshold Training tab for muscle memory training.

    Game-like interface where:
    - Random target values (circles with numbers) float from right to left
    - User tries to match target values with brake input
    - A smaller circle indicates the current brake position
    - Configurable step sizes for target values (5, 10, 15, 20, 25)

    Follows SOLID principles:
    - Single Responsibility: UI orchestration only, delegates to specialized classes
    - Open/Closed: Configurable via settings, behavior extensible via generators
    - Liskov Substitution: Uses Protocol for target generation
    - Interface Segregation: Depends only on Callable for brake input
    - Dependency Inversion: Depends on abstractions (Callable, Protocol)
    """

    def __init__(self, *, read_brake_percent: Callable[[], float]) -> None:
        """Initialize the threshold training tab.

        Args:
            read_brake_percent: Callable that returns current brake percentage (0-100).
        """
        super().__init__()
        self._read_brake_percent = read_brake_percent
        self._scroll_speed = _DEFAULT_SCROLL_SPEED
        self._spawn_interval = 40  # Spawn a new target every N ticks
        self._watermark_visible = True

        self._init_components()
        self._init_ui()
        self._init_state()
        self._load_config()

    def _init_components(self) -> None:
        """Initialize reusable components."""
        self._target_generator = StepBasedTargetGenerator(step=DEFAULT_THRESHOLD_STEP)
        self._timer = QTimer(interval=_TIMER_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

    def _init_ui(self) -> None:
        """Initialize all UI components."""
        # Status label
        self._status_label = QLabel(
            "Press Start to begin. Match the floating targets with your brake input."
        )

        # Control buttons
        self._start_btn = QPushButton("Start")
        self._start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self._start_btn.clicked.connect(self.toggle_running)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self._reset_btn.clicked.connect(self.reset)

        # Step slider (5, 10, 15, 20, 25)
        self._step_slider = QSlider(Qt.Horizontal)
        self._step_slider.setRange(1, 5)  # Maps to step values 5, 10, 15, 20, 25
        self._step_slider.setSingleStep(1)
        self._step_slider.setPageStep(1)
        self._step_slider.setTickInterval(1)
        self._step_slider.setTickPosition(QSlider.TicksBelow)
        self._step_slider.valueChanged.connect(self._on_step_changed)

        self._step_label = QLabel()
        self._step_label.setMinimumWidth(52)

        # Speed slider (30-120 Hz)
        self._speed_slider = QSlider(Qt.Horizontal)
        self._speed_slider.setRange(_MIN_SPEED_HZ, _MAX_SPEED_HZ)
        self._speed_slider.setSingleStep(10)
        self._speed_slider.setPageStep(10)
        self._speed_slider.setTickInterval(10)
        self._speed_slider.setTickPosition(QSlider.TicksBelow)
        self._speed_slider.valueChanged.connect(self._on_speed_changed)

        self._speed_label = QLabel()
        self._speed_label.setMinimumWidth(52)

        # Create chart
        (
            self._chart,
            self._series_targets,
            self._series_indicator,
            self._series_brake_line,
            self._axis_x,
            self._axis_y,
        ) = ThresholdChartBuilder.create_chart()

        self._chart_view = LabeledTargetChartView(self._chart, self._series_targets)

        # Layout
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self._start_btn)
        buttons.addWidget(self._reset_btn)
        buttons.addStretch()

        step_row = QHBoxLayout()
        step_row.addWidget(QLabel("Step:"))
        step_row.addWidget(self._step_slider, stretch=1)
        step_row.addWidget(self._step_label)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed:"))
        speed_row.addWidget(self._speed_slider, stretch=1)
        speed_row.addWidget(self._speed_label)

        settings_layout = QFormLayout()
        settings_layout.addRow(step_row)
        settings_layout.addRow(speed_row)

        layout = QVBoxLayout()
        layout.addLayout(buttons)
        layout.addLayout(settings_layout)
        layout.addWidget(self._chart_view, stretch=1)
        layout.addWidget(self._status_label)
        self.setLayout(layout)

    def _init_state(self) -> None:
        """Initialize application state."""
        self._state = ThresholdTrainingState()
        self._update_display()

    def _load_config(self) -> None:
        """Load persisted configuration."""
        try:
            cfg = load_threshold_training_config()
            self._step_slider.setValue(cfg.step // 5)  # Convert step to slider value
            self._speed_slider.setValue(cfg.speed)
        except Exception:
            self._step_slider.setValue(2)  # Default to step=10
            self._speed_slider.setValue(DEFAULT_THRESHOLD_SPEED)

        self._update_step_label(self._step_slider.value() * 5)
        self._update_speed_label(self._speed_slider.value())
        self._chart_view.set_watermark_visible(self._watermark_visible)

    def _save_config(self) -> None:
        """Save current configuration."""
        try:
            cfg = ThresholdTrainingConfig(
                step=self._step_slider.value() * 5,
                speed=self._speed_slider.value(),
            )
            save_threshold_training_config(cfg)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Public Interface
    # -------------------------------------------------------------------------

    def toggle_running(self) -> None:
        """Toggle between running and paused states."""
        if self._state.running:
            self._pause()
        else:
            self._start()

    def reset(self) -> None:
        """Reset the training session."""
        self._timer.stop()
        self._state = ThresholdTrainingState()
        self._update_display()
        self._start_btn.setText("Start")
        self._start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self._status_label.setText("Reset. Press Start when ready.")
        self._set_watermark_percent(0)

    def set_watermark_visible(self, visible: bool) -> None:
        """Set watermark visibility (called from settings)."""
        self._watermark_visible = visible
        self._chart_view.set_watermark_visible(visible)

    def set_update_rate(self, hz: int) -> None:
        """Adjust timer interval for update rate."""
        hz = max(_MIN_SPEED_HZ, min(_MAX_SPEED_HZ, int(hz)))
        interval_ms = max(1, int(1000 / hz))
        self._timer.setInterval(interval_ms)

    # -------------------------------------------------------------------------
    # Private Methods - State Management
    # -------------------------------------------------------------------------

    def _start(self) -> None:
        """Start the training session."""
        self._timer.start()
        self._state.running = True
        self._start_btn.setText("Pause")
        self._start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self._status_label.setText("Match the floating targets with your brake input!")

    def _pause(self) -> None:
        """Pause the training session."""
        self._timer.stop()
        self._state.running = False
        self._start_btn.setText("Start")
        self._start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self._status_label.setText("Paused. Press Start to continue.")

    def _on_tick(self) -> None:
        """Handle timer tick - update targets and brake position."""
        # Read current brake value
        self._state.current_brake = clamp(
            float(self._read_brake_percent()), float(AXIS_MIN), float(AXIS_MAX)
        )

        # Move existing targets
        self._move_targets()

        # Spawn new targets periodically
        self._state.spawn_counter += 1
        if self._state.spawn_counter >= self._spawn_interval:
            self._spawn_target()
            self._state.spawn_counter = 0

        # Update display
        self._update_display()
        self._set_watermark_percent(self._state.current_brake)

    def _move_targets(self) -> None:
        """Move all targets leftward and remove expired ones."""
        for target in self._state.targets:
            target.move_left(self._scroll_speed)

        # Remove targets that have gone off screen
        self._state.targets = [t for t in self._state.targets if not t.is_expired()]

    def _spawn_target(self) -> None:
        """Spawn a new target at the right edge."""
        value = self._target_generator.generate()
        target = FloatingTarget(x=_AXIS_X_MAX, value=value)
        self._state.targets.append(target)

    # -------------------------------------------------------------------------
    # Private Methods - Display
    # -------------------------------------------------------------------------

    def _update_display(self) -> None:
        """Update all chart series with current state."""
        self._render_targets()
        self._render_brake_indicator()
        self._render_brake_line()

    def _render_targets(self) -> None:
        """Render floating target circles."""
        points = [QPointF(t.x, float(t.value)) for t in self._state.targets]
        self._series_targets.replace(points)

    def _render_brake_indicator(self) -> None:
        """Render the small circle at the current brake position."""
        # Position the indicator at a fixed X position (left side) at current brake Y
        indicator_x = 10.0  # Fixed position on the left
        self._series_indicator.replace([QPointF(indicator_x, self._state.current_brake)])

    def _render_brake_line(self) -> None:
        """Render a horizontal line at the current brake level."""
        y = self._state.current_brake
        self._series_brake_line.replace([
            QPointF(0, y),
            QPointF(_AXIS_X_MAX, y),
        ])

    def _set_watermark_percent(self, value: float) -> None:
        """Update the watermark display with current brake percentage."""
        try:
            self._chart_view.set_watermark_text(f"{int(round(value))}")
            self._chart_view.set_watermark_visible(self._watermark_visible)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Private Methods - Settings Handlers
    # -------------------------------------------------------------------------

    def _on_step_changed(self, slider_value: int) -> None:
        """Handle step slider changes."""
        step = slider_value * 5  # Convert 1-5 to 5, 10, 15, 20, 25
        self._target_generator.step = step
        self._update_step_label(step)
        self._update_y_axis_ticks(step)
        self._save_config()

    def _on_speed_changed(self, hz: int) -> None:
        """Handle speed slider changes."""
        hz = max(_MIN_SPEED_HZ, min(_MAX_SPEED_HZ, int(hz)))
        self._update_speed_label(hz)
        self.set_update_rate(hz)
        self._save_config()

    def _update_step_label(self, step: int) -> None:
        """Update the step label text."""
        self._step_label.setText(f"{step}%")

    def _update_speed_label(self, hz: int) -> None:
        """Update the speed label text."""
        self._speed_label.setText(f"{hz} Hz")

    def _update_y_axis_ticks(self, step: int) -> None:
        """Update Y axis tick marks to match the step value."""
        tick_count = int((AXIS_MAX - AXIS_MIN) / step) + 1
        try:
            self._axis_y.setTickCount(tick_count)
        except Exception:
            pass
