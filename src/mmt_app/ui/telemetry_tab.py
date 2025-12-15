"""Telemetry tab for live throttle/brake/steering visualization.

This module provides a real-time telemetry display showing:
- Throttle and brake input as line charts
- Optional steering trace
- Target lines for throttle and brake
- Vertical progress bars for current values
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .telemetry_chart import TelemetryChart
from .utils import clamp, clamp_int, snap_to_step

if TYPE_CHECKING:
    from ..telemetry import TelemetrySample

# UI defaults
_DEFAULT_MAX_CHART_POINTS = 200
_DEFAULT_THROTTLE_TARGET = 60
_DEFAULT_BRAKE_TARGET = 40
_DEFAULT_GRID_STEP = 10


class TelemetryTab(QWidget):
    """Live telemetry visualization tab.

    Displays real-time throttle, brake, and steering data as a scrolling
    chart with configurable target lines and grid divisions.

    Features:
    - Real-time line chart with throttle (green) and brake (red) traces
    - Optional steering trace (blue)
    - Configurable target lines for throttle and brake
    - Vertical progress bars showing current input values
    - Adjustable grid divisions
    """

    def __init__(
        self,
        *,
        on_targets_changed: Callable[[], None] | None = None,
        on_grid_step_changed: Callable[[int], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the telemetry tab.

        Args:
            on_targets_changed: Callback when throttle/brake targets change.
            on_grid_step_changed: Callback when grid step changes.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self._on_targets_changed = on_targets_changed
        self._on_grid_step_changed_external = on_grid_step_changed
        self._is_streaming = False
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the telemetry tab UI."""
        # Throttle target slider
        self._throttle_target_slider = self._create_target_slider(
            default=_DEFAULT_THROTTLE_TARGET,
            object_name="throttleTargetSlider",
        )
        throttle_target_row = self._create_slider_row(
            self._throttle_target_slider,
            label_name="throttleTargetValue",
            initial_text=f"{_DEFAULT_THROTTLE_TARGET}%",
        )

        # Brake target slider
        self._brake_target_slider = self._create_target_slider(
            default=_DEFAULT_BRAKE_TARGET,
            object_name="brakeTargetSlider",
        )
        brake_target_row = self._create_slider_row(
            self._brake_target_slider,
            label_name="brakeTargetValue",
            initial_text=f"{_DEFAULT_BRAKE_TARGET}%",
        )

        # Grid step slider
        self._grid_step_slider = self._create_grid_slider()
        grid_row = self._create_slider_row(
            self._grid_step_slider,
            label_name="gridStepValue",
            initial_text=f"{_DEFAULT_GRID_STEP}%",
        )

        # Control buttons
        self._start_button = QPushButton("Start")
        self._start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self._start_button.clicked.connect(self._on_start_clicked)
        
        self._reset_button = QPushButton("Reset")
        self._reset_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self._reset_button.clicked.connect(self._on_reset_clicked)

        # Form layout for controls
        controls = QFormLayout()
        controls.addRow("Throttle target", throttle_target_row)
        controls.addRow("Brake target", brake_target_row)
        controls.addRow("Grid division", grid_row)

        # Button bar
        control_bar = QHBoxLayout()
        control_bar.addStretch()
        control_bar.addWidget(self._start_button)
        control_bar.addWidget(self._reset_button)
        control_bar.addStretch()

        # Telemetry chart
        self._chart = TelemetryChart(max_points=_DEFAULT_MAX_CHART_POINTS)
        self._apply_grid_step(_DEFAULT_GRID_STEP)

        # Progress bar labels
        self._throttle_bar_label = QLabel("0%")
        self._throttle_bar_label.setObjectName("throttleBarLabel")
        self._brake_bar_label = QLabel("0%")
        self._brake_bar_label.setObjectName("brakeBarLabel")

        # Progress bars
        self._throttle_bar = self._create_vertical_progress_bar("throttleBar")
        self._brake_bar = self._create_vertical_progress_bar("brakeBar")

        # Bar labels row
        bar_labels = QHBoxLayout()
        bar_labels.setContentsMargins(0, 0, 0, 0)
        bar_labels.setSpacing(12)
        bar_labels.addWidget(self._throttle_bar_label, alignment=Qt.AlignHCenter)
        bar_labels.addWidget(self._brake_bar_label, alignment=Qt.AlignHCenter)

        # Bar columns
        bar_columns = QHBoxLayout()
        bar_columns.setContentsMargins(0, 0, 0, 0)
        bar_columns.setSpacing(12)
        bar_columns.addWidget(self._throttle_bar)
        bar_columns.addWidget(self._brake_bar)

        # Bars stack
        bars_stack = QVBoxLayout()
        bars_stack.setContentsMargins(12, 0, 0, 0)
        bars_stack.setSpacing(6)
        bars_stack.addLayout(bar_labels)
        bars_stack.addLayout(bar_columns, stretch=1)
        
        bars_container = QWidget()
        bars_container.setLayout(bars_stack)
        bars_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        # Chart row with bars
        chart_row = QHBoxLayout()
        chart_row.addWidget(self._chart.view, stretch=1)
        chart_row.addWidget(bars_container)

        # Main layout
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addLayout(control_bar)
        layout.addLayout(chart_row, stretch=1)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    @property
    def is_streaming(self) -> bool:
        """Return whether the tab is currently streaming."""
        return self._is_streaming

    @property
    def throttle_target(self) -> int:
        """Return the current throttle target percentage."""
        return int(self._throttle_target_slider.value())

    @property
    def brake_target(self) -> int:
        """Return the current brake target percentage."""
        return int(self._brake_target_slider.value())

    @property
    def grid_step(self) -> int:
        """Return the current grid step percentage."""
        return int(self._grid_step_slider.value())

    def set_throttle_target(self, value: int) -> None:
        """Set the throttle target percentage."""
        self._throttle_target_slider.setValue(clamp_int(value, 0, 100))

    def set_brake_target(self, value: int) -> None:
        """Set the brake target percentage."""
        self._brake_target_slider.setValue(clamp_int(value, 0, 100))

    def set_grid_step(self, step_percent: int) -> None:
        """Set the grid step percentage."""
        step = snap_to_step(clamp_int(step_percent, 5, 50), 5)
        self._grid_step_slider.blockSignals(True)
        self._grid_step_slider.setValue(step)
        self._grid_step_slider.blockSignals(False)
        self._update_grid_step_label(step)
        self._chart.set_grid_step(step_percent=step)

    def set_steering_visible(self, visible: bool) -> None:
        """Set whether the steering trace is visible."""
        self._chart.set_steering_visible(visible)

    def set_streaming(self, streaming: bool) -> None:
        """Set the streaming state and update the UI."""
        self._is_streaming = streaming
        if streaming:
            self._start_button.setText("Pause")
            self._start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self._start_button.setText("Start")
            self._start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def append_sample(self, sample: "TelemetrySample") -> None:
        """Append a telemetry sample to the chart."""
        self._chart.append(sample)
        self._chart.set_targets(
            throttle_target=float(self._throttle_target_slider.value()),
            brake_target=float(self._brake_target_slider.value()),
        )
        self._update_bars(sample)

    def reset(self) -> None:
        """Reset the chart and progress bars."""
        self._chart.reset()
        self._throttle_bar.setValue(0)
        self._brake_bar.setValue(0)
        self._throttle_bar_label.setText("0%")
        self._brake_bar_label.setText("0%")

    # -------------------------------------------------------------------------
    # Callbacks for MainWindow
    # -------------------------------------------------------------------------

    def connect_start_stop(self, callback: Callable[[bool], None]) -> None:
        """Connect a callback for start/stop button clicks.

        Args:
            callback: Function called with True for start, False for pause.
        """
        self._start_stop_callback = callback

    def connect_reset(self, callback: Callable[[], None]) -> None:
        """Connect a callback for reset button clicks."""
        self._reset_callback = callback

    # -------------------------------------------------------------------------
    # Event handlers
    # -------------------------------------------------------------------------

    def _on_start_clicked(self) -> None:
        """Handle start/pause button click."""
        if hasattr(self, "_start_stop_callback"):
            # Toggle state
            self._start_stop_callback(not self._is_streaming)

    def _on_reset_clicked(self) -> None:
        """Handle reset button click."""
        if hasattr(self, "_reset_callback"):
            self._reset_callback()

    def _on_grid_step_changed(self) -> None:
        """Handle grid step slider changes."""
        step = snap_to_step(self._grid_step_slider.value(), 5)
        step = clamp_int(step, 5, 50)
        if step != self._grid_step_slider.value():
            self._grid_step_slider.blockSignals(True)
            self._grid_step_slider.setValue(step)
            self._grid_step_slider.blockSignals(False)
        self._update_grid_step_label(step)
        self._chart.set_grid_step(step_percent=step)
        if self._on_grid_step_changed_external:
            self._on_grid_step_changed_external(step)

    def _on_targets_changed_internal(self) -> None:
        """Handle target slider changes."""
        if self._on_targets_changed:
            self._on_targets_changed()

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def _apply_grid_step(self, step: int) -> None:
        """Apply the grid step to the chart."""
        self._chart.set_grid_step(step_percent=step)

    def _update_grid_step_label(self, step_percent: int) -> None:
        """Update the grid step label text."""
        if hasattr(self, "_grid_step_label"):
            self._grid_step_label.setText(f"{int(step_percent)}%")

    def _update_bars(self, sample: "TelemetrySample") -> None:
        """Update the vertical bar indicators."""
        throttle_val = int(clamp(sample.throttle, 0.0, 100.0))
        brake_val = int(clamp(sample.brake, 0.0, 100.0))
        self._throttle_bar.setValue(throttle_val)
        self._brake_bar.setValue(brake_val)
        self._throttle_bar_label.setText(f"{throttle_val}%")
        self._brake_bar_label.setText(f"{brake_val}%")

    def _create_target_slider(self, *, default: int, object_name: str) -> QSlider:
        """Create a target percentage slider (0-100%)."""
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setSingleStep(1)
        slider.setPageStep(5)
        slider.setTickInterval(10)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setValue(default)
        slider.setObjectName(object_name)
        slider.valueChanged.connect(self._on_targets_changed_internal)
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
