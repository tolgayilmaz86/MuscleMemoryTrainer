from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
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
from ..static_brake import BrakeTrace, presets as preset_traces


@dataclass(frozen=True, slots=True)
class StaticBrakeState:
    trace: BrakeTrace
    user_points: list[int]
    cursor: int
    recording: bool


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
        self.status = QLabel("Select a trace and press Start.")
        self.length_spin = QSpinBox()
        self.length_spin.setRange(20, 500)
        self.length_spin.setValue(101)
        self.length_spin.valueChanged.connect(self._rebuild_default_trace_if_needed)

        self.start_btn = QPushButton("Start attempt")
        self.start_btn.clicked.connect(self.toggle_recording)
        self.reset_btn = QPushButton("Reset attempt")
        self.reset_btn.clicked.connect(self.reset_attempt)
        self.save_btn = QPushButton("Save trace…")
        self.save_btn.clicked.connect(self.save_trace_as)
        self.import_btn = QPushButton("Import trace…")
        self.import_btn.clicked.connect(self.import_trace)
        self.export_btn = QPushButton("Export trace…")
        self.export_btn.clicked.connect(self.export_trace)

        self.chart, self.series_target, self.series_user, self.axis_x, self.axis_y = self._create_chart()
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.Antialiasing)

        form = QFormLayout()
        form.addRow("Brake trace", self.trace_combo)
        form.addRow("New trace length", self.length_spin)

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.reset_btn)
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
        self._populate_traces()
        self._load_selection()

        self._state = StaticBrakeState(
            trace=self._current_trace(),
            user_points=[0] * self._current_trace_length(),
            cursor=0,
            recording=False,
        )
        self._render_target()
        self._render_user()

    def _create_chart(self):
        series_target = QLineSeries(name="Target brake %")
        series_user = QLineSeries(name="Your brake %")

        series_target.setPen(QPen(QColor("#ef4444"), 2))  # red
        series_user.setPen(QPen(QColor("#94a3b8"), 2))  # gray

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
        self.trace_combo.blockSignals(True)
        self.trace_combo.clear()

        for name in sorted(self._presets.keys()):
            self.trace_combo.addItem(f"Preset: {name}", ("preset", name))
        for name in sorted(self._custom.keys()):
            self.trace_combo.addItem(f"Custom: {name}", ("custom", name))

        self.trace_combo.currentIndexChanged.connect(self._on_trace_changed)
        self.trace_combo.blockSignals(False)

    def _load_selection(self) -> None:
        cfg = load_static_brake_config()
        if not cfg or not cfg.selected_trace:
            return
        for i in range(self.trace_combo.count()):
            label = self.trace_combo.itemText(i)
            if label.endswith(cfg.selected_trace) or label == cfg.selected_trace:
                self.trace_combo.setCurrentIndex(i)
                return

    def _save_selection(self) -> None:
        name = self._selected_trace_name()
        save_static_brake_config(StaticBrakeConfig(selected_trace=name))

    def _selected_trace_name(self) -> str:
        _, name = self.trace_combo.currentData()
        return str(name)

    def _current_trace_length(self) -> int:
        return len(self._current_trace().points)

    def _current_trace(self) -> BrakeTrace:
        kind, name = self.trace_combo.currentData()
        if kind == "custom":
            points = self._custom.get(name) or [0] * int(self.length_spin.value())
            return BrakeTrace(str(name), list(points))
        return self._presets.get(name) or next(iter(self._presets.values()))

    def _on_trace_changed(self) -> None:
        self._save_selection()
        self._state = StaticBrakeState(
            trace=self._current_trace(),
            user_points=[0] * self._current_trace_length(),
            cursor=0,
            recording=False,
        )
        self._timer.stop()
        self.start_btn.setText("Start attempt")
        self.status.setText("Trace selected. Press Start.")
        self._update_axes()
        self._render_target()
        self._render_user()

    def _update_axes(self) -> None:
        length = self._current_trace_length()
        self.axis_x.setRange(0, max(0, length - 1))

    def _render_target(self) -> None:
        points = [QPointF(float(i), float(v)) for i, v in enumerate(self._state.trace.points)]
        self.series_target.replace(points)

    def _render_user(self) -> None:
        points = [QPointF(float(i), float(v)) for i, v in enumerate(self._state.user_points)]
        self.series_user.replace(points)

    def toggle_recording(self) -> None:
        if self._state.recording:
            self._timer.stop()
            self._state = StaticBrakeState(
                trace=self._state.trace,
                user_points=self._state.user_points,
                cursor=self._state.cursor,
                recording=False,
            )
            self.start_btn.setText("Start attempt")
            self.status.setText("Paused. Press Start to continue.")
            return

        self._state = StaticBrakeState(
            trace=self._state.trace,
            user_points=self._state.user_points,
            cursor=self._state.cursor,
            recording=True,
        )
        self.start_btn.setText("Pause")
        self.status.setText("Recording… press pedal to match the red trace.")
        self._timer.start()

    def reset_attempt(self) -> None:
        self._timer.stop()
        self._state = StaticBrakeState(
            trace=self._current_trace(),
            user_points=[0] * self._current_trace_length(),
            cursor=0,
            recording=False,
        )
        self.start_btn.setText("Start attempt")
        self.status.setText("Attempt reset.")
        self._update_axes()
        self._render_target()
        self._render_user()

    def _on_tick(self) -> None:
        if not self._state.recording:
            return
        length = len(self._state.user_points)
        if self._state.cursor >= length:
            self._timer.stop()
            self._state = StaticBrakeState(
                trace=self._state.trace,
                user_points=self._state.user_points,
                cursor=self._state.cursor,
                recording=False,
            )
            self.start_btn.setText("Start attempt")
            self.status.setText("Attempt complete.")
            return

        brake = int(round(max(0.0, min(100.0, float(self._read_brake_percent())))))
        user_points = list(self._state.user_points)
        user_points[self._state.cursor] = brake
        self._state = StaticBrakeState(
            trace=self._state.trace,
            user_points=user_points,
            cursor=self._state.cursor + 1,
            recording=True,
        )
        self._render_user()

    def save_trace_as(self) -> None:
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
        kind, name = self.trace_combo.currentData()
        trace = self._current_trace()
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
        # Keep this simple for now; length affects only new imports/saves and the simulator trace fallback.
        # Presets keep their own fixed lengths.
        pass

