from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPen, QColor

from ..telemetry import TelemetrySample
from .utils import AXIS_MAX, AXIS_MIN, clamp
from .watermark_chart_view import WatermarkChartView

# Constants
_DEFAULT_MAX_POINTS = 200
_STEERING_CENTER_PERCENT = 50.0
_MIN_GRID_STEP = 5
_MAX_GRID_STEP = 50


class TelemetryChart:
    """Encapsulates the telemetry chart rendering and scrolling window."""

    def __init__(self, *, max_points: int = _DEFAULT_MAX_POINTS) -> None:
        """Initialize the telemetry chart.

        Args:
            max_points: Maximum number of points to display in the chart window.
        """
        self._max_points = max_points
        self._sample_index = 0
        self._init_series()
        self._init_chart()
        self._init_view()

    def _init_series(self) -> None:
        """Initialize all chart series."""
        self._series_throttle = QLineSeries(name="Throttle %")
        self._series_brake = QLineSeries(name="Brake %")
        self._series_steering = QLineSeries(name="Steering (0=center)")
        self._series_steering_zero = QLineSeries(name="Steering 0")
        self._series_target_throttle = QLineSeries(name="Throttle Target")
        self._series_target_brake = QLineSeries(name="Brake Target")

        self._series_throttle.setPen(QPen(QColor("#22c55e"), 2))  # green
        self._series_brake.setPen(QPen(QColor("#ef4444"), 2))  # red
        self._series_steering.setPen(QPen(QColor("#f97316"), 2))  # orange
        self._series_steering_zero.setPen(QPen(QColor("#94a3b8"), 1, Qt.DashLine))

    def _init_chart(self) -> None:
        """Initialize the chart and axes."""
        self._chart = QChart()
        all_series = self._get_all_series()
        for series in all_series:
            self._chart.addSeries(series)

        self._axis_x = QValueAxis()
        self._axis_x.setRange(0, self._max_points)
        self._axis_x.setLabelFormat("%d")

        self._axis_y = QValueAxis()
        self._axis_y.setRange(AXIS_MIN, AXIS_MAX)
        self._axis_y.setLabelFormat("%d")

        self._chart.addAxis(self._axis_x, Qt.AlignBottom)
        self._chart.addAxis(self._axis_y, Qt.AlignLeft)
        for series in all_series:
            series.attachAxis(self._axis_x)
            series.attachAxis(self._axis_y)

        self._chart.legend().setVisible(True)
        self._hide_steering_zero_legend()

    def _init_view(self) -> None:
        """Initialize the chart view with watermark support."""
        self._view = WatermarkChartView(self._chart)
        self._view.setRenderHint(QPainter.Antialiasing)
        self._watermark_visible = True

    def _get_all_series(self) -> tuple:
        """Get all chart series as a tuple."""
        return (
            self._series_throttle,
            self._series_brake,
            self._series_steering,
            self._series_steering_zero,
            self._series_target_throttle,
            self._series_target_brake,
        )

    def _hide_steering_zero_legend(self) -> None:
        """Hide the steering zero line from the legend."""
        try:
            markers = self._chart.legend().markers(self._series_steering_zero)
            if markers:
                markers[0].setVisible(False)
        except Exception:
            pass

    @property
    def view(self) -> WatermarkChartView:
        """Get the chart view widget."""
        return self._view

    @property
    def chart(self) -> QChart:
        """Get the chart object."""
        return self._chart

    def set_watermark_visible(self, visible: bool) -> None:
        """Set whether the watermark is visible."""
        self._watermark_visible = visible
        self._view.set_watermark_visible(visible)

    def set_watermark_text(self, text: str) -> None:
        """Set the watermark text."""
        self._view.set_watermark_text(text)
        self._view.set_watermark_visible(self._watermark_visible)

    def reset(self) -> None:
        """Reset all series and sample counter."""
        for series in (
            self._series_throttle,
            self._series_brake,
            self._series_steering,
            self._series_target_throttle,
            self._series_target_brake,
        ):
            series.clear()
        self._sample_index = 0
        self._axis_x.setRange(0, self._max_points)
        self._update_steering_zero_line()

    def append(self, sample: TelemetrySample) -> None:
        """Append a new telemetry sample to the chart."""
        self._sample_index += 1
        x = float(self._sample_index)
        self._series_throttle.append(QPointF(x, sample.throttle))
        self._series_brake.append(QPointF(x, sample.brake))
        self._series_steering.append(QPointF(x, self._steering_to_percent(sample.steering)))

        for series in (self._series_throttle, self._series_brake, self._series_steering):
            overflow = series.count() - self._max_points
            if overflow > 0:
                series.removePoints(0, overflow)

        min_x = max(0, self._sample_index - self._max_points)
        self._axis_x.setRange(min_x, min_x + self._max_points)
        self._update_steering_zero_line()

    def set_targets(self, *, throttle_target: float, brake_target: float) -> None:
        """Set horizontal target lines for throttle and brake."""
        min_x = float(self._axis_x.min())
        max_x = float(self._axis_x.max())
        self._series_target_throttle.replace([QPointF(min_x, throttle_target), QPointF(max_x, throttle_target)])
        self._series_target_brake.replace([QPointF(min_x, brake_target), QPointF(max_x, brake_target)])
        self._update_steering_zero_line()

    def set_grid_step(self, *, step_percent: int) -> None:
        """Set the y-axis tick spacing (0..100 divided into equal steps)."""
        step_percent = max(_MIN_GRID_STEP, min(_MAX_GRID_STEP, int(step_percent)))
        self._axis_y.setRange(AXIS_MIN, AXIS_MAX)
        tick_count = int(AXIS_MAX / step_percent) + 1  # 0..100 inclusive
        try:
            self._axis_y.setTickCount(tick_count)
        except Exception:
            pass
        # Keep support for dynamic ticks where available.
        if hasattr(self._axis_y, "setTickAnchor"):
            self._axis_y.setTickAnchor(0.0)
        if hasattr(self._axis_y, "setTickInterval"):
            self._axis_y.setTickInterval(float(step_percent))

    def _update_steering_zero_line(self) -> None:
        """Update the steering center reference line position."""
        min_x = float(self._axis_x.min())
        max_x = float(self._axis_x.max())
        self._series_steering_zero.replace([QPointF(min_x, _STEERING_CENTER_PERCENT), QPointF(max_x, _STEERING_CENTER_PERCENT)])

    @staticmethod
    def _steering_to_percent(steering: float) -> float:
        """Map steering -100..100 to 0..100, where 50 represents 0."""
        return clamp((steering + 100.0) / 2.0, float(AXIS_MIN), float(AXIS_MAX))

    def set_steering_visible(self, visible: bool) -> None:
        """Toggle visibility of steering trace and zero line."""
        self._series_steering.setVisible(visible)
        self._series_steering_zero.setVisible(visible)
        try:
            for series in (self._series_steering, self._series_steering_zero):
                markers = self._chart.legend().markers(series)
                if markers:
                    markers[0].setVisible(visible and series is self._series_steering)
        except Exception:
            pass
