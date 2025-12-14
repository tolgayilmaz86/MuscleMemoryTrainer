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
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

from ..config import (
    StaticBrakeConfig,
    load_static_brake_config,
    load_static_brake_traces,
    save_static_brake_config,
    save_static_brake_trace,
)
from ..static_brake import BrakeTrace, presets as preset_traces, random_trace
from .watermark_chart_view import WatermarkChartView


@dataclass(frozen=True, slots=True)
class StaticBrakeState:
    trace: BrakeTrace
    user_points: list[int]
    cursor: int
    recording: bool
    has_brake: bool


class StaticBrakeTab(QWidget):
    """Static Brake training tab.

    - X axis is fixed (0..N-1); it does not scroll.
    - A target brake trace is displayed.
    - User can record an attempt; brake input is overlaid.
    - Custom traces and selection persist via config.ini; import/export supported.
    """

    def __init__(self, *, read_brake_percent: Callable[[], float]) -> None:
        super().__init__()
        self._read_brake_percent = read_brake_percent

        self._timer = QTimer(interval=20)
        self._timer.timeout.connect(self._on_tick)

        self.trace_combo = QComboBox()
        self.status = QLabel("Select a trace or generate one, then press Start.")
        self.length_slider = QSlider(Qt.Horizontal)
        self.length_slider.setRange(20, 500)
        self.length_slider.setValue(150)
        self.length_slider.setTickInterval(20)
        self.length_slider.setSingleStep(1)
        self.length_slider.setPageStep(10)
        self.length_slider.setTickPosition(QSlider.TicksBelow)
        self.length_slider.valueChanged.connect(self._on_length_changed)
        self.length_value = QLabel("150")
        length_row = QWidget()
        length_row_layout = QHBoxLayout(length_row)
        length_row_layout.setContentsMargins(0, 0, 0, 0)
        length_row_layout.addWidget(self.length_slider, stretch=1)
        length_row_layout.addWidget(self.length_value)

        self.start_btn = QPushButton("Start auto")
        self.start_btn.clicked.connect(self.toggle_recording)
        self.reset_btn = QPushButton("Reset attempt")
        self.reset_btn.clicked.connect(self.reset_attempt)
        self.regen_btn = QPushButton("Regenerate target")
        self.regen_btn.clicked.connect(self._regenerate_random_trace)
        self.auto_regen_checkbox = QCheckBox("Auto Generate")
        self.auto_regen_checkbox.setChecked(True)
        self.watermark_checkbox = QCheckBox("Show watermark")
        self.watermark_checkbox.setChecked(True)
        self.watermark_checkbox.stateChanged.connect(self._on_watermark_toggled)
        self.save_btn = QPushButton("Save trace")
        self.save_btn.clicked.connect(self.save_trace_as)
        self.import_btn = QPushButton("Import trace")
        self.import_btn.clicked.connect(self.import_trace)
        self.export_btn = QPushButton("Export trace")
        self.export_btn.clicked.connect(self.export_trace)

        self.chart, self.series_target, self.series_user, self.axis_x, self.axis_y = self._create_chart()
        self.chart_view = WatermarkChartView(self.chart)

        form = QFormLayout()
        form.addRow("Brake trace", self.trace_combo)
        form.addRow("Trace length", length_row)

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.reset_btn)
        buttons.addWidget(self.regen_btn)
        buttons.addWidget(self.auto_regen_checkbox)
        buttons.addWidget(self.watermark_checkbox)
        buttons.addStretch()
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.import_btn)
        buttons.addWidget(self.export_btn)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.chart_view, stretch=1)
        layout.addWidget(self.status)
        self.setLayout(layout)

        self._presets = preset_traces()
        self._custom = load_static_brake_traces()
        self._generated_trace: Optional[BrakeTrace] = None
        self._loop_active = False
        self._populate_traces()
        self._load_selection()

        initial_trace = self._current_trace()
        self._state = StaticBrakeState(
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
        self.chart_view.set_watermark_visible(self.watermark_checkbox.isChecked())

    def _create_chart(self):
        series_target = QLineSeries(name="Target brake %")
        series_user = QLineSeries(name="Your brake %")

        series_target.setPen(QPen(QColor("#ef4444"), 2))  # red
        # Match Active Brake styling: semi-transparent cyan, thicker stroke.
        series_user.setPen(QPen(QColor(56, 189, 248, 140), 6))

        chart = QChart()
        chart.addSeries(series_target)
        chart.addSeries(series_user)

        axis_x = QValueAxis()
        axis_x.setRange(0, 100)
        axis_x.setLabelFormat("%d")
        axis_x.setTitleText("Trace steps")

        axis_y = QValueAxis()
        axis_y.setRange(0, 100)
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
        try:
            self.trace_combo.currentIndexChanged.disconnect(self._on_trace_changed)
        except Exception:
            pass

        current = self.trace_combo.currentData()
        self.trace_combo.blockSignals(True)
        self.trace_combo.clear()

        self.trace_combo.addItem("Random (regenerating)", ("random", "Random target"))
        for name in sorted(self._presets.keys()):
            self.trace_combo.addItem(f"Preset: {name}", ("preset", name))
        for name in sorted(self._custom.keys()):
            self.trace_combo.addItem(f"Custom: {name}", ("custom", name))

        if current is not None:
            for i in range(self.trace_combo.count()):
                if self.trace_combo.itemData(i) == current:
                    self.trace_combo.setCurrentIndex(i)
                    break

        self.trace_combo.currentIndexChanged.connect(self._on_trace_changed)
        self.trace_combo.blockSignals(False)

    def _load_selection(self) -> None:
        cfg = load_static_brake_config()
        if not cfg or not cfg.selected_trace:
            self.trace_combo.setCurrentIndex(0)
            return
        for i in range(self.trace_combo.count()):
            data = self.trace_combo.itemData(i)
            if data:
                _, name = data
                if str(name) == cfg.selected_trace:
                    self.trace_combo.setCurrentIndex(i)
                    return
            label = self.trace_combo.itemText(i)
            if label.endswith(cfg.selected_trace) or label == cfg.selected_trace:
                self.trace_combo.setCurrentIndex(i)
                return

    def _save_selection(self) -> None:
        name = self._selected_trace_name()
        save_static_brake_config(StaticBrakeConfig(selected_trace=name))

    def _selected_trace_name(self) -> str:
        data = self.trace_combo.currentData()
        if not data:
            return ""
        _, name = data
        return str(name)

    def _current_trace_length(self) -> int:
        try:
            return len(self._state.trace.points)
        except Exception:
            return len(self._current_trace().points)

    def _current_trace(self) -> BrakeTrace:
        data = self.trace_combo.currentData()
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
        self._save_selection()
        self._apply_trace(self._current_trace(), status_text="Trace selected. Press Start.")

    def _update_axes(self, *, length: Optional[int] = None) -> None:
        length = length if length is not None else self._current_trace_length()
        self.axis_x.setRange(0, max(0, length - 1))

    def _render_target(self) -> None:
        points = [QPointF(float(i), float(v)) for i, v in enumerate(self._state.trace.points)]
        self.series_target.replace(points)

    def _render_user(self) -> None:
        points = [QPointF(float(i), float(v)) for i, v in enumerate(self._state.user_points)]
        self.series_user.replace(points)
        if self._state.user_points:
            last_index = max(0, min(self._state.cursor - 1, len(self._state.user_points) - 1))
            self._set_watermark_percent(self._state.user_points[last_index])

    def toggle_recording(self) -> None:
        if self._loop_active:
            self._loop_active = False
            self._stop_current_attempt(status="Stopped auto-recording. Click Start to resume.")
            return

        self._loop_active = True
        self._begin_attempt(status="Auto-recording armed. Press brake to start; release to loop.")

    def reset_attempt(self) -> None:
        self._timer.stop()
        self._loop_active = False
        trace = self._state.trace
        self._state = StaticBrakeState(
            trace=trace,
            user_points=[0] * len(trace.points),
            cursor=0,
            recording=False,
            has_brake=False,
        )
        self._set_start_button_text()
        self.status.setText("Attempt reset. Auto-recording stopped.")
        self._update_axes(length=len(trace.points))
        self._render_target()
        self._render_user()
        self._set_watermark_percent(0)

    def _on_tick(self) -> None:
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
        self._state = StaticBrakeState(
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
        self._timer.stop()
        if regen and self.auto_regen_checkbox.isChecked() and self._is_random_selected():
            self._regenerate_random_trace(
                status_text=f"{message} New random target ready.",
                auto_restart=self._loop_active,
            )
            return
        self._state = StaticBrakeState(
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
            self.status.setText(message)

    def _read_brake_value(self) -> int:
        return int(round(max(0.0, min(100.0, float(self._read_brake_percent())))))

    def _regenerate_random_trace(self, status_text: Optional[str] = None, *, auto_restart: bool = False) -> None:
        self._ensure_random_selected()
        length = self._random_length()
        self._generated_trace = random_trace(length)
        self._apply_trace(self._generated_trace, status_text=status_text or "Random target regenerated.")
        self._save_selection()
        if auto_restart and self._loop_active:
            self._begin_attempt(status="Random target regenerated. Auto-recording armed.")

    def _apply_trace(self, trace: BrakeTrace, *, status_text: Optional[str] = None) -> None:
        normalized = self._normalize_trace(trace, force_end_zero=self._is_random_selected())
        length = len(normalized.points)
        self._timer.stop()
        self._state = StaticBrakeState(
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
            self.status.setText(status_text)

    def _random_length(self) -> int:
        try:
            return max(20, min(500, int(self.length_slider.value())))
        except Exception:
            return 150

    def _normalize_trace(self, trace: BrakeTrace, *, force_end_zero: bool = False) -> BrakeTrace:
        points = list(trace.points) or [0]
        points[0] = 0
        if force_end_zero and points:
            points[-1] = 0
        return BrakeTrace(trace.name, points)

    def _is_random_selected(self) -> bool:
        data = self.trace_combo.currentData()
        return bool(data) and data[0] == "random"

    def _ensure_random_selected(self) -> None:
        if self._is_random_selected():
            return
        for i in range(self.trace_combo.count()):
            data = self.trace_combo.itemData(i)
            if data and data[0] == "random":
                self.trace_combo.blockSignals(True)
                self.trace_combo.setCurrentIndex(i)
                self.trace_combo.blockSignals(False)
                break

    def save_trace_as(self) -> None:
        """Save the current user trace as a custom trace."""
        name, ok = QInputDialog.getText(self, "Save brake trace", "Trace name:")
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            self.status.setText("Save canceled: empty name.")
            return
        try:
            save_static_brake_trace(name, self._state.user_points)
            self._custom = load_static_brake_traces()
            self._populate_traces()
            self.status.setText(f"Saved trace '{name}'.")
        except Exception as exc:
            self.status.setText(f"Save failed: {exc}")

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
            self.status.setText(f"Imported trace '{name}'.")
        except Exception as exc:
            self.status.setText(f"Import failed: {exc}")

    def export_trace(self) -> None:
        """Export the currently selected trace to a JSON file."""
        data = self.trace_combo.currentData() or ("preset", self._state.trace.name)
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
            self.status.setText(f"Exported to {path}.")
        except Exception as exc:
            self.status.setText(f"Export failed: {exc}")

    def _rebuild_default_trace_if_needed(self) -> None:
        if self._is_random_selected():
            self._regenerate_random_trace(status_text="Random target regenerated for new length.")
        else:
            self._update_axes(length=self._current_trace_length())

    def _on_length_changed(self, value: int) -> None:
        self.length_value.setText(str(int(value)))
        self._rebuild_default_trace_if_needed()

    def _begin_attempt(self, status: Optional[str] = None) -> None:
        trace = self._state.trace
        points = [0] * len(trace.points)
        cursor = 1 if points else 0  # keep index 0 pinned at zero
        self._state = StaticBrakeState(
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
            self.status.setText(status)

    def _stop_current_attempt(self, status: Optional[str] = None) -> None:
        self._timer.stop()
        trace = self._state.trace
        self._state = StaticBrakeState(
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
            self.status.setText(status)

    def _set_start_button_text(self) -> None:
        if self._loop_active:
            self.start_btn.setText("Stop auto")
        else:
            self.start_btn.setText("Start auto")

    def _set_watermark_percent(self, value: int) -> None:
        try:
            self.chart_view.set_watermark_text(f"{int(value)}")
            self.chart_view.set_watermark_visible(self.watermark_checkbox.isChecked())
        except Exception:
            pass

    def _on_watermark_toggled(self, state: int) -> None:
        self.chart_view.set_watermark_visible(bool(state))
