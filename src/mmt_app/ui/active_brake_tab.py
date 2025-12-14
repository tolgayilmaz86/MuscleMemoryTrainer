from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCharts import QChart, QLineSeries, QValueAxis
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from ..config import ActiveBrakeConfig, load_active_brake_config, save_active_brake_config
from .watermark_chart_view import WatermarkChartView


@dataclass
class _ActiveBrakeState:
    running: bool
    user_cursor: int
    target_points: list[QPointF]
    user_points: list[QPointF]


class ActiveBrakeTab(QWidget):
    """Active Brake training tab.

    - A target brake signal scrolls right-to-left.
    - User presses brake as the target crosses the center line; their trace starts at the midline.
    - Grid step is user-configurable and persisted.
    """

    def __init__(self, *, read_brake_percent: Callable[[], float]) -> None:
        """Initialize the tab with a callable that supplies live brake percentage."""
        super().__init__()
        self._read_brake_percent = read_brake_percent
        self._mid_x = 50.0
        self._axis_x_max = 100.0
        self._axis_y_min = 0.0
        self._axis_y_max = 100.0
        self._scroll_speed = 1.5
        self._target_queue: deque[float] = deque()

        self._timer = QTimer(interval=40)
        self._timer.timeout.connect(self._on_tick)

        self.grid_slider = QSlider(Qt.Horizontal)
        self.grid_slider.setRange(10, 50)
        self.grid_slider.setSingleStep(5)
        self.grid_slider.setPageStep(5)
        self.grid_slider.setTickInterval(5)
        self.grid_slider.setTickPosition(QSlider.TicksBelow)
        self.grid_slider.setValue(10)
        self.grid_slider.valueChanged.connect(self._on_grid_changed)
        self.grid_value_label = QLabel()
        self._update_grid_value_label(self.grid_slider.value())
        grid_row = QWidget()
        grid_row_layout = QHBoxLayout(grid_row)
        grid_row_layout.setContentsMargins(0, 0, 0, 0)
        grid_row_layout.addWidget(self.grid_slider, 1)
        grid_row_layout.addWidget(self.grid_value_label)

        self.status = QLabel("Press Start, then match the red target as it crosses the center line.")

        self.start_btn = QPushButton("Start")
        self.start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.start_btn.clicked.connect(self.toggle_running)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.reset_btn.clicked.connect(self.reset)
        self.watermark_checkbox = QCheckBox("Show watermark")
        self.watermark_checkbox.setChecked(True)
        self.watermark_checkbox.stateChanged.connect(self._on_watermark_toggled)

        (
            self.chart,
            self.series_target,
            self.series_user,
            self.series_midline,
            self.axis_x,
            self.axis_y,
        ) = self._create_chart()
        self.chart_view = WatermarkChartView(self.chart)

        controls = QFormLayout()
        controls.addRow("Grid division", grid_row)
        controls.addRow("Watermark", self.watermark_checkbox)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.reset_btn)
        buttons.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(controls)
        layout.addLayout(buttons)
        layout.addWidget(self.chart_view, stretch=1)
        layout.addWidget(self.status)
        self.setLayout(layout)
        self.chart_view.set_watermark_visible(self.watermark_checkbox.isChecked())

        self._state = _ActiveBrakeState(
            running=False,
            user_cursor=0,
            target_points=[],
            user_points=[],
        )
        self._load_config()
        self.reset()

    def _create_chart(self):
        """Create chart objects and wire up axes/series."""
        series_target = QLineSeries(name="Target brake %")
        series_user = QLineSeries(name="Your brake %")
        series_midline = QLineSeries(name="Target arrival")

        series_target.setPen(QPen(QColor("#ef4444"), 2))
        user_pen = QPen(QColor(56, 189, 248, 140), 6)  # semi-transparent cyan, thicker
        series_user.setPen(user_pen)
        series_midline.setPen(QPen(QColor("#94a3b8"), 1, Qt.DashLine))

        chart = QChart()
        for series in (series_target, series_user, series_midline):
            chart.addSeries(series)

        axis_x = QValueAxis()
        axis_x.setRange(0, self._axis_x_max)
        axis_x.setLabelFormat("%d")

        axis_y = QValueAxis()
        axis_y.setRange(self._axis_y_min, self._axis_y_max)
        axis_y.setLabelFormat("%d")
        axis_y.setTitleText("Brake %")

        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)
        for series in (series_target, series_user, series_midline):
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)

        chart.legend().setVisible(True)
        chart.setTitle("Active Brake Training")

        return chart, series_target, series_user, series_midline, axis_x, axis_y

    def _load_config(self) -> None:
        """Restore saved grid spacing for the active brake chart."""
        cfg = load_active_brake_config()
        self._apply_grid_step(cfg.grid_step_percent)

    def _save_config(self) -> None:
        """Persist the current grid spacing to config."""
        step = int(self.grid_slider.value())
        save_active_brake_config(ActiveBrakeConfig(grid_step_percent=step))

    def _on_grid_changed(self, value: int) -> None:
        """Handle user selecting a new grid step via the slider."""
        step = int(round(value / 5) * 5)
        step = max(5, min(50, step))
        if step != value:
            self.grid_slider.blockSignals(True)
            self.grid_slider.setValue(step)
            self.grid_slider.blockSignals(False)
        self._update_grid_value_label(step)
        self._apply_grid_step(step)
        self._save_config()

    def _apply_grid_step(self, step_percent: int) -> None:
        """Apply grid tick spacing on the Y axis and sync the slider."""
        step_percent = max(5, min(50, int(step_percent)))
        try:
            self.grid_slider.blockSignals(True)
            self.grid_slider.setValue(step_percent)
        finally:
            self.grid_slider.blockSignals(False)
        self._update_grid_value_label(step_percent)
        tick_count = int((self._axis_y_max - self._axis_y_min) / step_percent) + 1
        try:
            self.axis_y.setTickCount(tick_count)
        except Exception:
            pass
        if hasattr(self.axis_y, "setTickInterval"):
            self.axis_y.setTickInterval(float(step_percent))

    def toggle_running(self) -> None:
        """Toggle the training loop between running/paused states."""
        if self._state.running:
            self._timer.stop()
            self._state.running = False
            self.start_btn.setText("Start")
            self.start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.status.setText("Paused. Press Start to continue.")
            return

        self._timer.start()
        self._state.running = True
        self.start_btn.setText("Pause")
        self.start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.status.setText("Match the red target as it crosses the center line.")

    def reset(self) -> None:
        """Reset target/user traces and put the tab into a ready state."""
        self._timer.stop()
        self._state = _ActiveBrakeState(
            running=False,
            user_cursor=0,
            target_points=self._seed_target_points(),
            user_points=[],
        )
        self._render_target()
        self._render_user()
        self._render_midline()
        self._set_watermark_percent(0)
        self.start_btn.setText("Start")
        self.start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.status.setText("Reset. Press Start when ready.")

    def _seed_target_points(self) -> list[QPointF]:
        """Fill the chart initially by walking across the X axis with queued target values."""
        self._target_queue.clear()
        self._refill_target_queue()
        points: list[QPointF] = []
        x = self._axis_x_max
        while x >= 0:
            points.append(QPointF(x, self._next_target_value()))
            x -= self._scroll_speed
        return points

    def _render_target(self) -> None:
        """Render the target series with current points sorted by X."""
        points = sorted(self._state.target_points, key=lambda p: p.x())
        self.series_target.replace(points)

    def _render_user(self) -> None:
        """Render the user series with current points sorted by X."""
        points = sorted(self._state.user_points, key=lambda p: p.x())
        self.series_user.replace(points)

    def _render_midline(self) -> None:
        """Draw the vertical midline where the target crosses the user cursor."""
        self.series_midline.replace(
            [QPointF(self._mid_x, self._axis_y_min), QPointF(self._mid_x, self._axis_y_max)]
        )

    def _advance_target(self) -> None:
        """Shift target points left and append a new rightmost point from the queue."""
        shifted: list[QPointF] = []
        for pt in self._state.target_points:
            new_x = pt.x() - self._scroll_speed
            if new_x >= 0:
                shifted.append(QPointF(new_x, pt.y()))
        shifted.append(QPointF(self._axis_x_max, self._next_target_value()))
        self._state.target_points = shifted
        self._render_target()

    def _record_user(self) -> None:
        """Append the latest brake reading at the midline."""
        brake = self._clamp_y(float(self._read_brake_percent()))
        self._state.user_points.append(QPointF(self._mid_x, brake))
        self._state.user_cursor += 1
        self._render_user()
        self._set_watermark_percent(brake)

    def _advance_user_points(self) -> None:
        """Scroll user points left with the target to create the trailing trace."""
        shifted: list[QPointF] = []
        for pt in self._state.user_points:
            new_x = pt.x() - self._scroll_speed
            if new_x >= 0:
                shifted.append(QPointF(new_x, pt.y()))
        self._state.user_points = shifted
        self._render_user()

    def _refill_target_queue(self) -> None:
        """Top up the target queue with random pattern segments."""
        burst: list[float] = []
        for _ in range(random.randint(1, 2)):
            pattern = random.choice(["ramp_hold_drop", "double_peak", "spike", "hill", "trail_brake"])
            burst.extend(self._build_segment(pattern))
            burst.extend([0.0] * random.randint(3, 12))
        self._target_queue.extend(burst)

    def _build_segment(self, pattern: str) -> list[float]:
        """Build one target segment according to the requested pattern."""
        length = random.randint(20, 120)
        peak = random.uniform(55.0, 100.0)
        if pattern == "spike":
            raw = self._shape_spike(length, peak)
        if pattern == "double_peak":
            raw = self._shape_double_peak(length, peak)
        if pattern == "hill":
            raw = self._shape_hill(length, peak)
        if pattern == "trail_brake":
            raw = self._shape_trail_brake(length, peak)
        else:
            raw = self._shape_ramp_hold_drop(length, peak)
        return self._smooth(self._jitter(raw))

    @staticmethod
    def _shape_ramp_hold_drop(length: int, peak: float) -> list[float]:
        """Ease up to peak, hold, then ease down."""
        up = max(5, int(length * 0.25))
        hold = max(4, int(length * 0.2))
        down = max(5, length - up - hold)
        values = []
        for i in range(up):
            t = (i + 1) / up
            values.append(peak * ActiveBrakeTab._ease(t))
        values.extend([peak] * hold)
        for i in range(down):
            t = (i + 1) / down
            values.append(peak * (1 - ActiveBrakeTab._ease(t)))
        return [max(0.0, min(100.0, v)) for v in values]

    @staticmethod
    def _shape_spike(length: int, peak: float) -> list[float]:
        """Quick ramp and drop shape."""
        up = max(3, int(length * 0.15))
        down = max(4, length - up)
        values = []
        for i in range(up):
            t = (i + 1) / up
            values.append(peak * ActiveBrakeTab._ease(t))
        for i in range(down):
            t = (i + 1) / down
            values.append(peak * (1 - ActiveBrakeTab._ease(t)))
        return [max(0.0, min(100.0, v)) for v in values]

    @staticmethod
    def _shape_double_peak(length: int, peak: float) -> list[float]:
        """Two peaks separated by a small gap plateau."""
        first = ActiveBrakeTab._shape_ramp_hold_drop(max(6, int(length * 0.5)), peak)
        gap = [peak * 0.3] * max(3, int(length * 0.1))
        second = ActiveBrakeTab._shape_spike(max(6, length - len(first) - len(gap)), peak * 0.9)
        return [max(0.0, min(100.0, v)) for v in (first + gap + second)]

    @staticmethod
    def _shape_hill(length: int, peak: float) -> list[float]:
        """Smooth hill using a sine curve."""
        values = []
        for i in range(length):
            t = i / max(1, length - 1)
            values.append(peak * (math.sin(math.pi * t) ** 1.5))
        return [max(0.0, min(100.0, v)) for v in values]

    @staticmethod
    def _shape_trail_brake(length: int, peak: float) -> list[float]:
        """Rise to peak then trail off gradually."""
        up = max(4, int(length * 0.2))
        decay = max(10, length - up)
        values = []
        for i in range(up):
            t = (i + 1) / up
            values.append(peak * ActiveBrakeTab._ease(t))
        for i in range(decay):
            t = (i + 1) / decay
            values.append(peak * (1 - ActiveBrakeTab._ease(t) * 0.9))
        return [max(0.0, min(100.0, v)) for v in values]

    @staticmethod
    def _ease(t: float) -> float:
        """Smoothstep-ish easing for softer ramps."""
        t = max(0.0, min(1.0, t))
        return 0.5 - 0.5 * math.cos(math.pi * t)

    @staticmethod
    def _smooth(values: list[float]) -> list[float]:
        """Light smoothing pass over generated values."""
        if not values:
            return values
        smoothed = values[:]
        for _ in range(2):
            buf: list[float] = []
            for i, v in enumerate(smoothed):
                left = smoothed[i - 1] if i > 0 else smoothed[i]
                right = smoothed[i + 1] if i + 1 < len(smoothed) else smoothed[i]
                buf.append((left + v * 2 + right) / 4.0)
            smoothed = buf
        return [max(0.0, min(100.0, v)) for v in smoothed]

    @staticmethod
    def _jitter(values: list[float]) -> list[float]:
        """Add small random noise and clamp to [0,100]."""
        return [
            max(0.0, min(100.0, v + random.uniform(-2.0, 2.0)))
            for v in values
        ]

    def _next_target_value(self) -> float:
        """Pull the next target value, refilling the queue if needed."""
        if not self._target_queue:
            self._refill_target_queue()
        return self._clamp_y(self._target_queue.popleft())

    def _on_tick(self) -> None:
        """Advance target and, when running, record and scroll user points."""
        self._set_watermark_percent(self._clamp_y(float(self._read_brake_percent())))
        self._advance_target()
        if self._state.running:
            self._advance_user_points()
            self._record_user()

    def _clamp_y(self, value: float) -> float:
        """Clamp a value to the visible Y range."""
        return max(self._axis_y_min, min(self._axis_y_max, value))

    def _update_grid_value_label(self, step_percent: int) -> None:
        self.grid_value_label.setText(f"{int(step_percent)}%")

    def _set_watermark_percent(self, value: float) -> None:
        try:
            self.chart_view.set_watermark_text(f"{int(round(value))}")
            self.chart_view.set_watermark_visible(self.watermark_checkbox.isChecked())
        except Exception:
            pass

    def _on_watermark_toggled(self, state: int) -> None:
        self.chart_view.set_watermark_visible(bool(state))

    def set_update_rate(self, hz: int) -> None:
        """Adjust timer interval for how often the active brake chart ticks."""
        hz = max(5, min(120, int(hz)))
        interval_ms = max(1, int(1000 / hz))
        self._timer.setInterval(interval_ms)
