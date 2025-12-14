from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPen, QColor

from ..telemetry import TelemetrySample


class TelemetryChart:
    """Encapsulates the telemetry chart rendering and scrolling window."""

    def __init__(self, *, max_points: int = 200) -> None:
        self.max_points = max_points

        self.series_throttle = QLineSeries(name="Throttle %")
        self.series_brake = QLineSeries(name="Brake %")
        self.series_steering = QLineSeries(name="Steering (0=center)")
        self.series_steering_zero = QLineSeries(name="Steering 0")
        self.series_target_throttle = QLineSeries(name="Throttle Target")
        self.series_target_brake = QLineSeries(name="Brake Target")

        self.series_throttle.setPen(QPen(QColor("#22c55e"), 2))  # green
        self.series_brake.setPen(QPen(QColor("#ef4444"), 2))  # red
        self.series_steering.setPen(QPen(QColor("#f97316"), 2))  # orange
        self.series_steering_zero.setPen(QPen(QColor("#94a3b8"), 1, Qt.DashLine))

        chart = QChart()
        for series in (
            self.series_throttle,
            self.series_brake,
            self.series_steering,
            self.series_steering_zero,
            self.series_target_throttle,
            self.series_target_brake,
        ):
            chart.addSeries(series)

        self.axis_x = QValueAxis()
        self.axis_x.setRange(0, self.max_points)
        self.axis_x.setLabelFormat("%d")
        self.axis_x.setTitleText("Samples")

        self.axis_y = QValueAxis()
        self.axis_y.setRange(0, 100)
        self.axis_y.setLabelFormat("%d")

        chart.addAxis(self.axis_x, Qt.AlignBottom)
        chart.addAxis(self.axis_y, Qt.AlignLeft)
        for series in (
            self.series_throttle,
            self.series_brake,
            self.series_steering,
            self.series_steering_zero,
            self.series_target_throttle,
            self.series_target_brake,
        ):
            series.attachAxis(self.axis_x)
            series.attachAxis(self.axis_y)

        chart.legend().setVisible(True)
        try:
            markers = chart.legend().markers(self.series_steering_zero)
            if markers:
                markers[0].setVisible(False)
        except Exception:
            pass
        self.chart = chart

        view = QChartView(self.chart)
        view.setRenderHint(QPainter.Antialiasing)
        self.view = view

        self.sample_index = 0

    def reset(self) -> None:
        for series in (
            self.series_throttle,
            self.series_brake,
            self.series_steering,
            self.series_target_throttle,
            self.series_target_brake,
        ):
            series.clear()
        self.sample_index = 0
        self.axis_x.setRange(0, self.max_points)
        self._update_steering_zero_line()

    def append(self, sample: TelemetrySample) -> None:
        self.sample_index += 1
        x = float(self.sample_index)
        self.series_throttle.append(QPointF(x, sample.throttle))
        self.series_brake.append(QPointF(x, sample.brake))
        self.series_steering.append(QPointF(x, self._steering_to_percent(sample.steering)))

        for series in (self.series_throttle, self.series_brake, self.series_steering):
            overflow = series.count() - self.max_points
            if overflow > 0:
                series.removePoints(0, overflow)

        min_x = max(0, self.sample_index - self.max_points)
        self.axis_x.setRange(min_x, min_x + self.max_points)
        self._update_steering_zero_line()

    def set_targets(self, *, throttle_target: float, brake_target: float) -> None:
        min_x = float(self.axis_x.min())
        max_x = float(self.axis_x.max())
        self.series_target_throttle.replace([QPointF(min_x, throttle_target), QPointF(max_x, throttle_target)])
        self.series_target_brake.replace([QPointF(min_x, brake_target), QPointF(max_x, brake_target)])
        self._update_steering_zero_line()

    def set_grid_step(self, *, step_percent: int) -> None:
        """Set the y-axis tick spacing (0..100 divided into equal steps)."""
        step_percent = max(5, min(50, int(step_percent)))
        self.axis_y.setRange(0, 100)
        tick_count = int(100 / step_percent) + 1  # 0..100 inclusive
        try:
            self.axis_y.setTickCount(tick_count)
        except Exception:
            pass
        # Keep support for dynamic ticks where available.
        if hasattr(self.axis_y, "setTickAnchor"):
            self.axis_y.setTickAnchor(0.0)
        if hasattr(self.axis_y, "setTickInterval"):
            self.axis_y.setTickInterval(float(step_percent))

    def _update_steering_zero_line(self) -> None:
        min_x = float(self.axis_x.min())
        max_x = float(self.axis_x.max())
        self.series_steering_zero.replace([QPointF(min_x, 50.0), QPointF(max_x, 50.0)])

    @staticmethod
    def _steering_to_percent(steering: float) -> float:
        """Map steering -100..100 to 0..100, where 50 represents 0."""
        return max(0.0, min(100.0, (steering + 100.0) / 2.0))
