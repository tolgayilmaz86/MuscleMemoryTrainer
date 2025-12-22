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
    QLabel,
    QPushButton,
    QHBoxLayout,
    QSlider,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from ..config import (
    ActiveBrakeConfig,
    load_active_brake_config,
    save_active_brake_config,
    DEFAULT_ACTIVE_BRAKE_SPEED,
)
from ..trail_brake import ease, smooth, jitter
from .watermark_chart_view import WatermarkChartView
from .utils import AXIS_MAX, AXIS_MIN, clamp

# Constants for active brake training
_DEFAULT_MID_X = 50.0
_DEFAULT_AXIS_X_MAX = 100.0
_DEFAULT_SCROLL_SPEED = 1.5
_DEFAULT_TIMER_INTERVAL = 40
_DEFAULT_GRID_STEP = 10
_MIN_SPEED_HZ = 30
_MAX_SPEED_HZ = 120


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
        self._init_chart_params()
        self._init_ui()
        self._init_state()

    def _init_chart_params(self) -> None:
        """Initialize chart parameters and constants."""
        self._mid_x = _DEFAULT_MID_X
        self._axis_x_max = _DEFAULT_AXIS_X_MAX
        self._axis_y_min = float(AXIS_MIN)
        self._axis_y_max = float(AXIS_MAX)
        self._scroll_speed = _DEFAULT_SCROLL_SPEED
        self._target_queue: deque[float] = deque()

    def _init_ui(self) -> None:
        """Initialize UI components."""
        self._timer = QTimer(interval=_DEFAULT_TIMER_INTERVAL)
        self._timer.timeout.connect(self._on_tick)

        self._status_label = QLabel("Press Start, then match the red target as it crosses the center line.")

        self._start_btn = QPushButton("Start")
        self._start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self._start_btn.clicked.connect(self.toggle_running)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self._reset_btn.clicked.connect(self.reset)

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

        # Load saved speed from config
        try:
            cfg = load_active_brake_config()
            initial_speed = cfg.speed
        except Exception:
            initial_speed = DEFAULT_ACTIVE_BRAKE_SPEED
        self._speed_slider.setValue(initial_speed)
        self._update_speed_label(initial_speed)

        (
            self._chart,
            self._series_target,
            self._series_user,
            self._series_midline,
            self._axis_x,
            self._axis_y,
        ) = self._create_chart()
        self._chart_view = WatermarkChartView(self._chart)
        self._watermark_visible = True  # Track watermark visibility

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self._start_btn)
        buttons.addWidget(self._reset_btn)
        buttons.addStretch()

        # Speed control row
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed:"))
        speed_row.addWidget(self._speed_slider, stretch=1)
        speed_row.addWidget(self._speed_label)

        layout = QVBoxLayout()
        layout.addLayout(buttons)
        layout.addLayout(speed_row)
        layout.addWidget(self._chart_view, stretch=1)
        layout.addWidget(self._status_label)
        self.setLayout(layout)
        self._chart_view.set_watermark_visible(self._watermark_visible)

    def _init_state(self) -> None:
        """Initialize application state."""
        self._state = _ActiveBrakeState(
            running=False,
            user_cursor=0,
            target_points=[],
            user_points=[],
        )
        self._apply_grid_step(_DEFAULT_GRID_STEP)
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

    def _apply_grid_step(self, step_percent: int) -> None:
        """Apply grid tick spacing on the Y axis."""
        step_percent = max(5, min(50, int(step_percent)))
        tick_count = int((self._axis_y_max - self._axis_y_min) / step_percent) + 1
        try:
            self._axis_y.setTickCount(tick_count)
        except Exception:
            pass
        if hasattr(self._axis_y, "setTickInterval"):
            self._axis_y.setTickInterval(float(step_percent))

    def toggle_running(self) -> None:
        """Toggle the training loop between running/paused states."""
        if self._state.running:
            self._timer.stop()
            self._state.running = False
            self._start_btn.setText("Start")
            self._start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self._status_label.setText("Paused. Press Start to continue.")
            return

        self._timer.start()
        self._state.running = True
        self._start_btn.setText("Pause")
        self._start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self._status_label.setText("Match the red target as it crosses the center line.")

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
        self._start_btn.setText("Start")
        self._start_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self._status_label.setText("Reset. Press Start when ready.")

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
        self._series_target.replace(points)

    def _render_user(self) -> None:
        """Render the user series with current points sorted by X."""
        points = sorted(self._state.user_points, key=lambda p: p.x())
        self._series_user.replace(points)

    def _render_midline(self) -> None:
        """Draw the vertical midline where the target crosses the user cursor."""
        self._series_midline.replace(
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
        return smooth(jitter(raw, spread=2.0), passes=2)

    @staticmethod
    def _shape_ramp_hold_drop(length: int, peak: float) -> list[float]:
        """Ease up to peak, hold, then ease down."""
        up = max(5, int(length * 0.25))
        hold = max(4, int(length * 0.2))
        down = max(5, length - up - hold)
        values = []
        for i in range(up):
            t = (i + 1) / up
            values.append(peak * ease(t))
        values.extend([peak] * hold)
        for i in range(down):
            t = (i + 1) / down
            values.append(peak * (1 - ease(t)))
        return [max(0.0, min(100.0, v)) for v in values]

    @staticmethod
    def _shape_spike(length: int, peak: float) -> list[float]:
        """Quick ramp and drop shape."""
        up = max(3, int(length * 0.15))
        down = max(4, length - up)
        values = []
        for i in range(up):
            t = (i + 1) / up
            values.append(peak * ease(t))
        for i in range(down):
            t = (i + 1) / down
            values.append(peak * (1 - ease(t)))
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
            values.append(peak * ease(t))
        for i in range(decay):
            t = (i + 1) / decay
            values.append(peak * (1 - ease(t) * 0.9))
        return [max(0.0, min(100.0, v)) for v in values]

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
        return clamp(value, self._axis_y_min, self._axis_y_max)

    def _set_watermark_percent(self, value: float) -> None:
        """Update the watermark display with the current brake percentage."""
        try:
            self._chart_view.set_watermark_text(f"{int(round(value))}")
            self._chart_view.set_watermark_visible(self._watermark_visible)
        except Exception:
            pass

    def set_watermark_visible(self, visible: bool) -> None:
        """Set watermark visibility (called from settings)."""
        self._watermark_visible = visible
        self._chart_view.set_watermark_visible(visible)

    def set_grid_step(self, step_percent: int) -> None:
        """Set the grid step from global settings.

        Args:
            step_percent: Grid step percentage (10, 20, 30, 40, 50).
        """
        self._apply_grid_step(step_percent)

    def set_update_rate(self, hz: int) -> None:
        """Adjust timer interval for how often the active brake chart ticks."""
        hz = max(_MIN_SPEED_HZ, min(_MAX_SPEED_HZ, int(hz)))
        interval_ms = max(1, int(1000 / hz))
        self._timer.setInterval(interval_ms)

    def _on_speed_changed(self, hz: int) -> None:
        """Handle speed slider changes."""
        hz = max(_MIN_SPEED_HZ, min(_MAX_SPEED_HZ, int(hz)))
        self._update_speed_label(hz)
        self.set_update_rate(hz)
        # Save to config
        try:
            save_active_brake_config(ActiveBrakeConfig(speed=hz))
        except Exception:
            pass

    def _update_speed_label(self, hz: int) -> None:
        """Update the speed label text."""
        self._speed_label.setText(f"{hz} Hz")
