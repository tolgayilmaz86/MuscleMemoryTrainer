from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCharts import QChart, QLineSeries, QValueAxis
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    StaticBrakeConfig,
    load_static_brake_config,
    load_static_brake_traces,
    save_static_brake_config,
    save_static_brake_trace,
)
from ..static_brake import BrakeTrace, presets as preset_traces, random_trace
from .utils import AXIS_MAX, clamp, clamp_int
from .watermark_chart_view import WatermarkChartView

# Constants
DEFAULT_TRACE_LENGTH = 150
MIN_TRACE_LENGTH = 20
MAX_TRACE_LENGTH = 500
_TIMER_INTERVAL_MS = 20
_BRAKE_MIN = 0.0
_BRAKE_MAX = 100.0


@dataclass(frozen=True, slots=True)
class _StaticBrakeState:
    """Internal state for the static brake training tab."""

    trace: BrakeTrace
    user_points: list[int]
    cursor: int
    recording: bool
    has_brake: bool


class StaticBrakeTab(QWidget):
    """Static Brake training tab.

    Features:
    - Fixed X axis (0..N-1) that does not scroll.
    - Target brake trace is displayed.
    - User can record an attempt; brake input is overlaid.
    - Custom traces and selection persist via config.ini.
    - Import/export functionality for sharing traces.
    """

    def __init__(self, *, read_brake_percent: Callable[[], float]) -> None:
        """Initialize the static brake tab.

        Args:
            read_brake_percent: Callable that returns current brake percentage.
        """
        super().__init__()
        self._read_brake_percent = read_brake_percent

        self._timer = QTimer(interval=_TIMER_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

        self._init_ui()
        self._init_state()

    def _init_ui(self) -> None:
        """Initialize all UI components."""
        self._trace_combo = QComboBox()
        self._status_label = QLabel("Select a trace or generate one, then press Start.")

        self._length_slider = QSlider(Qt.Horizontal)
        self._length_slider.setRange(MIN_TRACE_LENGTH, MAX_TRACE_LENGTH)
        self._length_slider.setValue(DEFAULT_TRACE_LENGTH)
        self._length_slider.setTickInterval(20)
        self._length_slider.setSingleStep(1)
        self._length_slider.setPageStep(10)
        self._length_slider.setTickPosition(QSlider.TicksBelow)
        self._length_slider.valueChanged.connect(self._on_length_changed)

        self._length_label = QLabel(str(DEFAULT_TRACE_LENGTH))
        length_row = self._create_slider_row(self._length_slider, self._length_label)

        self._start_btn = QPushButton("Start auto")
        self._start_btn.clicked.connect(self.toggle_recording)
        self._reset_btn = QPushButton("Reset attempt")
        self._reset_btn.clicked.connect(self.reset_attempt)
        self._regen_btn = QPushButton("Regenerate target")
        self._regen_btn.clicked.connect(self._regenerate_random_trace)
        self._auto_regen_checkbox = QCheckBox("Auto Generate")
        self._auto_regen_checkbox.setChecked(True)
        self._watermark_checkbox = QCheckBox("Show watermark")
        self._watermark_checkbox.setChecked(True)
        self._watermark_checkbox.stateChanged.connect(self._on_watermark_toggled)
        self._save_btn = QPushButton("Save trace")
        self._save_btn.clicked.connect(self.save_trace_as)
        self._import_btn = QPushButton("Import trace")
        self._import_btn.clicked.connect(self.import_trace)
        self._export_btn = QPushButton("Export trace")
        self._export_btn.clicked.connect(self.export_trace)

        self._chart, self._series_target, self._series_user, self._axis_x, self._axis_y = self._create_chart()
        self._chart_view = WatermarkChartView(self._chart)

        form = QFormLayout()
        form.addRow("Brake trace", self._trace_combo)
        form.addRow("Trace length", length_row)

        buttons = QHBoxLayout()
        buttons.addWidget(self._start_btn)
        buttons.addWidget(self._reset_btn)
        buttons.addWidget(self._regen_btn)
        buttons.addWidget(self._auto_regen_checkbox)
        buttons.addWidget(self._watermark_checkbox)
        buttons.addStretch()
        buttons.addWidget(self._save_btn)
        buttons.addWidget(self._import_btn)
        buttons.addWidget(self._export_btn)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self._chart_view, stretch=1)
        layout.addWidget(self._status_label)
        self.setLayout(layout)

    def _init_state(self) -> None:
        """Initialize internal state and load persisted configuration."""
        self._presets = preset_traces()
        self._custom = load_static_brake_traces()
        self._generated_trace: Optional[BrakeTrace] = None
        self._loop_active = False

        self._populate_traces()
        self._load_selection()

        initial_trace = self._current_trace()
        self._state = _StaticBrakeState(
            trace=initial_trace,
            user_points=[0] * len(initial_trace.points),
            cursor=0,
            recording=False,
            has_brake=False,
        )
        self._update_axes(length=len(initial_trace.points))
        self._render_target()
        self._render_user()
        self._set_start_button_text()
        self._set_watermark_percent(0)
        self._chart_view.set_watermark_visible(self._watermark_checkbox.isChecked())

    @staticmethod
    def _create_slider_row(slider: QSlider, label: QLabel) -> QWidget:
        """Create a widget containing a slider and its value label."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(slider, stretch=1)
        layout.addWidget(label)
        return row

    def _create_chart(self):
        """Create and configure the chart with target and user series."""
        series_target = QLineSeries(name="Target brake %")
        series_user = QLineSeries(name="Your brake %")

        series_target.setPen(QPen(QColor("#ef4444"), 2))  # red
        series_user.setPen(QPen(QColor(56, 189, 248, 140), 6))  # semi-transparent cyan

        chart = QChart()
        chart.addSeries(series_target)
        chart.addSeries(series_user)

        axis_x = QValueAxis()
        axis_x.setRange(0, 100)
        axis_x.setLabelFormat("%d")
        axis_x.setTitleText("Trace steps")

        axis_y = QValueAxis()
        axis_y.setRange(int(_BRAKE_MIN), int(_BRAKE_MAX))
        axis_y.setLabelFormat("%d")
        axis_y.setTitleText("Brake %")
        axis_y.setTickCount(11)

        chart.addAxis(axis_x, Qt.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignLeft)
        series_target.attachAxis(axis_x)
        series_target.attachAxis(axis_y)
        series_user.attachAxis(axis_x)
        series_user.attachAxis(axis_y)
        chart.legend().setVisible(True)
        chart.setTitle("Static Brake Training")

        return chart, series_target, series_user, axis_x, axis_y

    def _populate_traces(self) -> None:
        """Populate the trace combo box with presets and custom traces."""
        try:
            self._trace_combo.currentIndexChanged.disconnect(self._on_trace_changed)
        except Exception:
            pass

        current = self._trace_combo.currentData()
        self._trace_combo.blockSignals(True)
        self._trace_combo.clear()

        self._trace_combo.addItem("Random (regenerating)", ("random", "Random target"))
        for name in sorted(self._presets.keys()):
            self._trace_combo.addItem(f"Preset: {name}", ("preset", name))
        for name in sorted(self._custom.keys()):
            self._trace_combo.addItem(f"Custom: {name}", ("custom", name))

        if current is not None:
            for i in range(self._trace_combo.count()):
                if self._trace_combo.itemData(i) == current:
                    self._trace_combo.setCurrentIndex(i)
                    break

        self._trace_combo.currentIndexChanged.connect(self._on_trace_changed)
        self._trace_combo.blockSignals(False)

    def _load_selection(self) -> None:
        """Load the previously selected trace from configuration."""
        cfg = load_static_brake_config()
        if not cfg or not cfg.selected_trace:
            self._trace_combo.setCurrentIndex(0)
            return
        for i in range(self._trace_combo.count()):
            data = self._trace_combo.itemData(i)
            if data:
                _, name = data
                if str(name) == cfg.selected_trace:
                    self._trace_combo.setCurrentIndex(i)
                    return
            label = self._trace_combo.itemText(i)
            if label.endswith(cfg.selected_trace) or label == cfg.selected_trace:
                self._trace_combo.setCurrentIndex(i)
                return

    def _save_selection(self) -> None:
        """Persist the currently selected trace name."""
        name = self._selected_trace_name()
        save_static_brake_config(StaticBrakeConfig(selected_trace=name))

    def _selected_trace_name(self) -> str:
        """Get the name of the currently selected trace."""
        data = self._trace_combo.currentData()
        if not data:
            return ""
        _, name = data
        return str(name)

    def _current_trace_length(self) -> int:
        """Get the length of the current trace."""
        try:
            return len(self._state.trace.points)
        except Exception:
            return len(self._current_trace().points)

    def _current_trace(self) -> BrakeTrace:
        """Get the currently selected brake trace."""
        data = self._trace_combo.currentData()
        if not data:
            return self._normalize_trace(next(iter(self._presets.values())))
        kind, name = data
        if kind == "random":
            target_length = self._random_length()
            if self._generated_trace is None or len(self._generated_trace.points) != target_length:
                self._generated_trace = random_trace(target_length)
            return self._normalize_trace(self._generated_trace, force_end_zero=True)
        if kind == "custom":
            points = self._custom.get(name) or [0] * self._random_length()
            return self._normalize_trace(BrakeTrace(str(name), list(points)))
        trace = self._presets.get(name) or next(iter(self._presets.values()))
        return self._normalize_trace(trace)

    def _on_trace_changed(self) -> None:
        """Handle trace selection change."""
        self._save_selection()
        self._apply_trace(self._current_trace(), status_text="Trace selected. Press Start.")

    def _update_axes(self, *, length: Optional[int] = None) -> None:
        """Update the X axis range based on trace length."""
        length = length if length is not None else self._current_trace_length()
        self._axis_x.setRange(0, max(0, length - 1))

    def _render_target(self) -> None:
        """Render the target series with current trace points."""
        points = [QPointF(float(i), float(v)) for i, v in enumerate(self._state.trace.points)]
        self._series_target.replace(points)

    def _render_user(self) -> None:
        """Render the user series with current attempt points."""
        points = [QPointF(float(i), float(v)) for i, v in enumerate(self._state.user_points)]
        self._series_user.replace(points)
        if self._state.user_points:
            last_index = max(0, min(self._state.cursor - 1, len(self._state.user_points) - 1))
            self._set_watermark_percent(self._state.user_points[last_index])

    def toggle_recording(self) -> None:
        """Toggle the auto-recording loop."""
        if self._loop_active:
            self._loop_active = False
            self._stop_current_attempt(status="Stopped auto-recording. Click Start to resume.")
            return

        self._loop_active = True
        self._begin_attempt(status="Auto-recording armed. Press brake to start; release to loop.")

    def reset_attempt(self) -> None:
        """Reset the current attempt state."""
        self._timer.stop()
        self._loop_active = False
        trace = self._state.trace
        self._state = _StaticBrakeState(
            trace=trace,
            user_points=[0] * len(trace.points),
            cursor=0,
            recording=False,
            has_brake=False,
        )
        self._set_start_button_text()
        self._status_label.setText("Attempt reset. Auto-recording stopped.")
        self._update_axes(length=len(trace.points))
        self._render_target()
        self._render_user()
        self._set_watermark_percent(0)

    def _on_tick(self) -> None:
        """Handle timer tick during recording."""
        if not self._state.recording:
            return
        length = len(self._state.user_points)
        brake = self._read_brake_value()
        self._set_watermark_percent(brake)
        has_brake = self._state.has_brake or brake > 0

        # If we've reached the end of the trace, keep waiting for release to 0 before finishing/regenerating.
        if self._state.cursor >= length:
            if brake <= 0 and has_brake:
                self._finish_attempt("Brake returned to 0%.", regen=True)
            return

        # Do not advance until the first non-zero input arrives; keep the start anchored at zero.
        if not has_brake and brake <= 0:
            return

        user_points = list(self._state.user_points)
        user_points[self._state.cursor] = brake
        self._state = _StaticBrakeState(
            trace=self._state.trace,
            user_points=user_points,
            cursor=min(self._state.cursor + 1, length),
            recording=True,
            has_brake=has_brake,
        )
        self._render_user()
        # Only stop after we've seen brake input and it returns to zero.
        if brake <= 0 and has_brake and self._state.cursor > 0:
            self._finish_attempt("Brake returned to 0%.", regen=True)

    def _finish_attempt(self, message: str, *, regen: bool) -> None:
        """Complete the current attempt and optionally regenerate trace."""
        self._timer.stop()
        if regen and self._auto_regen_checkbox.isChecked() and self._is_random_selected():
            self._regenerate_random_trace(
                status_text=f"{message} New random target ready.",
                auto_restart=self._loop_active,
            )
            return
        self._state = _StaticBrakeState(
            trace=self._state.trace,
            user_points=self._state.user_points,
            cursor=self._state.cursor,
            recording=False,
            has_brake=False,
        )
        if self._loop_active:
            self._begin_attempt(status=f"{message} Next attempt armed.")
        else:
            self._set_start_button_text()
            self._status_label.setText(message)

    def _read_brake_value(self) -> int:
        """Read and clamp the current brake percentage value."""
        return clamp_int(int(round(float(self._read_brake_percent()))), 0, AXIS_MAX)

    def _regenerate_random_trace(self, status_text: Optional[str] = None, *, auto_restart: bool = False) -> None:
        self._ensure_random_selected()
        length = self._random_length()
        self._generated_trace = random_trace(length)
        self._apply_trace(self._generated_trace, status_text=status_text or "Random target regenerated.")
        self._save_selection()
        if auto_restart and self._loop_active:
            self._begin_attempt(status="Random target regenerated. Auto-recording armed.")

    def _apply_trace(self, trace: BrakeTrace, *, status_text: Optional[str] = None) -> None:
        """Apply a trace to the chart and reset state."""
        normalized = self._normalize_trace(trace, force_end_zero=self._is_random_selected())
        length = len(normalized.points)
        self._timer.stop()
        self._state = _StaticBrakeState(
            trace=normalized,
            user_points=[0] * length,
            cursor=0,
            recording=False,
            has_brake=False,
        )
        self._update_axes(length=length)
        self._render_target()
        self._render_user()
        self._set_start_button_text()
        self._set_watermark_percent(0)
        if status_text:
            self._status_label.setText(status_text)

    def _random_length(self) -> int:
        """Get the target length for random traces from the slider."""
        try:
            return max(MIN_TRACE_LENGTH, min(MAX_TRACE_LENGTH, int(self._length_slider.value())))
        except Exception:
            return DEFAULT_TRACE_LENGTH

    def _normalize_trace(self, trace: BrakeTrace, *, force_end_zero: bool = False) -> BrakeTrace:
        points = list(trace.points) or [0]
        points[0] = 0
        if force_end_zero and points:
            points[-1] = 0
        return BrakeTrace(trace.name, points)

    def _is_random_selected(self) -> bool:
        """Check if the random trace option is selected."""
        data = self._trace_combo.currentData()
        return bool(data) and data[0] == "random"

    def _ensure_random_selected(self) -> None:
        """Ensure the random trace option is selected in the combo box."""
        if self._is_random_selected():
            return
        for i in range(self._trace_combo.count()):
            data = self._trace_combo.itemData(i)
            if data and data[0] == "random":
                self._trace_combo.blockSignals(True)
                self._trace_combo.setCurrentIndex(i)
                self._trace_combo.blockSignals(False)
                break

    def save_trace_as(self) -> None:
        """Save the current user trace as a custom trace."""
        name, ok = QInputDialog.getText(self, "Save brake trace", "Trace name:")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            self._status_label.setText("Save canceled: empty name.")
            return
        try:
            save_static_brake_trace(name, self._state.user_points)
            self._custom = load_static_brake_traces()
            self._populate_traces()
            self._status_label.setText(f"Saved trace '{name}'.")
        except Exception as exc:
            self._status_label.setText(f"Save failed: {exc}")

    def import_trace(self) -> None:
        """Import a brake trace from a JSON file."""
        path_str, _ = QFileDialog.getOpenFileName(self, "Import brake trace", "", "JSON (*.json)")
        if not path_str:
            return
        path = Path(path_str)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or "name" not in raw or "points" not in raw:
                raise ValueError("Expected JSON object with keys: name, points")
            name = str(raw["name"]).strip()
            points = raw["points"]
            if not isinstance(points, list):
                raise ValueError("points must be a list")
            save_static_brake_trace(name, [int(x) for x in points])
            self._custom = load_static_brake_traces()
            self._populate_traces()
            self._status_label.setText(f"Imported trace '{name}'.")
        except Exception as exc:
            self._status_label.setText(f"Import failed: {exc}")

    def export_trace(self) -> None:
        """Export the currently selected trace to a JSON file."""
        data = self._trace_combo.currentData() or ("preset", self._state.trace.name)
        kind, name = data
        trace = self._state.trace
        default = f"{trace.name}.json"
        path_str, _ = QFileDialog.getSaveFileName(self, "Export brake trace", default, "JSON (*.json)")
        if not path_str:
            return
        path = Path(path_str)
        try:
            payload = {"name": trace.name, "points": trace.points, "kind": kind, "selected": name}
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._status_label.setText(f"Exported to {path}.")
        except Exception as exc:
            self._status_label.setText(f"Export failed: {exc}")

    def _rebuild_default_trace_if_needed(self) -> None:
        if self._is_random_selected():
            self._regenerate_random_trace(status_text="Random target regenerated for new length.")
        else:
            self._update_axes(length=self._current_trace_length())

    def _on_length_changed(self, value: int) -> None:
        """Handle length slider value change."""
        self._length_value_label.setText(str(int(value)))
        self._rebuild_default_trace_if_needed()

    def _begin_attempt(self, status: Optional[str] = None) -> None:
        """Begin a new recording attempt."""
        trace = self._state.trace
        points = [0] * len(trace.points)
        cursor = 1 if points else 0  # keep index 0 pinned at zero
        self._state = _StaticBrakeState(
            trace=trace,
            user_points=points,
            cursor=cursor,
            recording=True,
            has_brake=False,
        )
        self._render_user()
        self._set_watermark_percent(0)
        self._timer.start()
        self._set_start_button_text()
        if status:
            self._status_label.setText(status)

    def _stop_current_attempt(self, status: Optional[str] = None) -> None:
        """Stop the current recording attempt."""
        self._timer.stop()
        trace = self._state.trace
        self._state = _StaticBrakeState(
            trace=trace,
            user_points=[0] * len(trace.points),
            cursor=0,
            recording=False,
            has_brake=False,
        )
        self._render_user()
        self._set_watermark_percent(0)
        self._set_start_button_text()
        if status:
            self._status_label.setText(status)

    def _set_start_button_text(self) -> None:
        """Update the start button text based on loop state."""
        if self._loop_active:
            self._start_btn.setText("Stop auto")
        else:
            self._start_btn.setText("Start auto")

    def _set_watermark_percent(self, value: int) -> None:
        """Update the watermark display with the current brake percentage."""
        try:
            self._chart_view.set_watermark_text(f"{int(value)}")
            self._chart_view.set_watermark_visible(self._watermark_checkbox.isChecked())
        except Exception:
            pass

    def _on_watermark_toggled(self, state: int) -> None:
        """Handle watermark checkbox toggle."""
        self._chart_view.set_watermark_visible(bool(state))
