"""Display settings widget for chart visualization options.

Provides UI controls for throttle/brake targets, grid division,
update rate, and visibility toggles.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QWidget,
)

from mmt_app.config import (
    DEFAULT_THROTTLE_TARGET,
    DEFAULT_BRAKE_TARGET,
    DEFAULT_GRID_STEP_PERCENT,
    DEFAULT_UPDATE_HZ,
    DEFAULT_SHOW_STEERING,
    DEFAULT_SHOW_WATERMARK,
)
from mmt_app.ui.utils import clamp_int


_UI_SAVE_DEBOUNCE_MS: int = 500
"""Debounce interval (ms) for persisting UI settings."""


class DisplaySettingsGroup(QGroupBox):
    """Widget for display-related settings.

    Provides controls for:
    - Throttle/brake target percentages
    - Grid division step
    - Update rate (Hz)
    - Steering trace visibility
    - Watermark visibility on charts
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_targets_changed: Callable[[], None] | None = None,
        on_grid_step_changed: Callable[[int], None] | None = None,
        on_update_rate_changed: Callable[[int], None] | None = None,
        on_steering_visible_changed: Callable[[bool], None] | None = None,
        on_watermark_visible_changed: Callable[[bool], None] | None = None,
        on_settings_changed: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the display settings group.

        Args:
            parent: Parent widget.
            on_targets_changed: Callback when throttle/brake targets change.
            on_grid_step_changed: Callback when grid step changes.
            on_update_rate_changed: Callback when update rate changes.
            on_steering_visible_changed: Callback when steering visibility changes.
            on_watermark_visible_changed: Callback when watermark visibility changes.
            on_settings_changed: Callback for any setting change (for persistence).
        """
        super().__init__("Display Settings", parent)

        self._on_targets_changed = on_targets_changed or (lambda: None)
        self._on_grid_step_changed = on_grid_step_changed or (lambda _: None)
        self._on_update_rate_changed = on_update_rate_changed or (lambda _: None)
        self._on_steering_visible_changed = on_steering_visible_changed or (lambda _: None)
        self._on_watermark_visible_changed = on_watermark_visible_changed or (lambda _: None)
        self._on_settings_changed = on_settings_changed or (lambda: None)

        self._build_ui()

    # -------------------------------------------------------------------------
    # Public properties
    # -------------------------------------------------------------------------

    @property
    def throttle_target(self) -> int:
        """Return the configured throttle target percentage."""
        return self._throttle_target_slider.value()

    @property
    def brake_target(self) -> int:
        """Return the configured brake target percentage."""
        return self._brake_target_slider.value()

    @property
    def grid_step(self) -> int:
        """Return the configured grid step percentage."""
        return self._grid_step_slider.value()

    @property
    def update_rate(self) -> int:
        """Return the configured update rate in Hz."""
        return self._update_rate_slider.value()

    @property
    def show_steering(self) -> bool:
        """Return whether steering trace should be visible."""
        return self._show_steering_checkbox.isChecked()

    @property
    def show_watermark(self) -> bool:
        """Return whether watermark should be visible on charts."""
        return self._show_watermark_checkbox.isChecked()

    # -------------------------------------------------------------------------
    # Public setters
    # -------------------------------------------------------------------------

    def set_throttle_target(self, value: int) -> None:
        """Set the throttle target percentage."""
        value = clamp_int(value, 0, 100)
        self._throttle_target_slider.blockSignals(True)
        self._throttle_target_slider.setValue(value)
        self._throttle_target_slider.blockSignals(False)
        self._throttle_target_label.setText(f"{value}%")

    def set_brake_target(self, value: int) -> None:
        """Set the brake target percentage."""
        value = clamp_int(value, 0, 100)
        self._brake_target_slider.blockSignals(True)
        self._brake_target_slider.setValue(value)
        self._brake_target_slider.blockSignals(False)
        self._brake_target_label.setText(f"{value}%")

    def set_grid_step(self, step_percent: int) -> None:
        """Set the grid step percentage."""
        step = max(10, min(50, (step_percent // 10) * 10))
        self._grid_step_slider.blockSignals(True)
        self._grid_step_slider.setValue(step)
        self._grid_step_slider.blockSignals(False)
        self._grid_step_label.setText(f"{step}%")

    def set_update_rate(self, hz: int, *, update_slider: bool = False) -> None:
        """Set the update rate and optionally sync the slider."""
        hz = clamp_int(hz, 30, 120)
        if update_slider:
            self._update_rate_slider.blockSignals(True)
            self._update_rate_slider.setValue(hz)
            self._update_rate_slider.blockSignals(False)
        self._update_rate_label.setText(f"{hz} Hz")

    def set_show_steering(self, visible: bool, *, update_checkbox: bool = False) -> None:
        """Set steering visibility and optionally sync the checkbox."""
        if update_checkbox:
            self._show_steering_checkbox.blockSignals(True)
            self._show_steering_checkbox.setChecked(visible)
            self._show_steering_checkbox.blockSignals(False)

    def set_show_watermark(self, visible: bool, *, update_checkbox: bool = False) -> None:
        """Set watermark visibility and optionally sync the checkbox."""
        if update_checkbox:
            self._show_watermark_checkbox.blockSignals(True)
            self._show_watermark_checkbox.setChecked(visible)
            self._show_watermark_checkbox.blockSignals(False)

    # -------------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the display settings layout."""
        form = QFormLayout(self)

        # Throttle target slider
        self._throttle_target_slider = QSlider(Qt.Horizontal)
        self._throttle_target_slider.setObjectName("throttleTargetSlider")
        self._throttle_target_slider.setRange(0, 100)
        self._throttle_target_slider.setSingleStep(1)
        self._throttle_target_slider.setPageStep(5)
        self._throttle_target_slider.setTickInterval(10)
        self._throttle_target_slider.setTickPosition(QSlider.TicksBelow)
        self._throttle_target_slider.setValue(DEFAULT_THROTTLE_TARGET)
        self._throttle_target_slider.valueChanged.connect(self._on_targets_changed)
        self._throttle_target_slider.valueChanged.connect(self._on_settings_changed)

        self._throttle_target_label = QLabel(f"{DEFAULT_THROTTLE_TARGET}%")
        self._throttle_target_label.setObjectName("throttleTargetValue")
        self._throttle_target_label.setStyleSheet("color: #22c55e;")
        self._throttle_target_label.setMinimumWidth(52)
        self._throttle_target_slider.valueChanged.connect(
            lambda v: self._throttle_target_label.setText(f"{int(v)}%")
        )

        form.addRow("Throttle target:", self._build_slider_row(
            self._throttle_target_slider, self._throttle_target_label
        ))

        # Brake target slider
        self._brake_target_slider = QSlider(Qt.Horizontal)
        self._brake_target_slider.setObjectName("brakeTargetSlider")
        self._brake_target_slider.setRange(0, 100)
        self._brake_target_slider.setSingleStep(1)
        self._brake_target_slider.setPageStep(5)
        self._brake_target_slider.setTickInterval(10)
        self._brake_target_slider.setTickPosition(QSlider.TicksBelow)
        self._brake_target_slider.setValue(DEFAULT_BRAKE_TARGET)
        self._brake_target_slider.valueChanged.connect(self._on_targets_changed)
        self._brake_target_slider.valueChanged.connect(self._on_settings_changed)

        self._brake_target_label = QLabel(f"{DEFAULT_BRAKE_TARGET}%")
        self._brake_target_label.setObjectName("brakeTargetValue")
        self._brake_target_label.setStyleSheet("color: #ef4444;")
        self._brake_target_label.setMinimumWidth(52)
        self._brake_target_slider.valueChanged.connect(
            lambda v: self._brake_target_label.setText(f"{int(v)}%")
        )

        form.addRow("Brake target:", self._build_slider_row(
            self._brake_target_slider, self._brake_target_label
        ))

        # Grid step slider (10-50%)
        self._grid_step_slider = QSlider(Qt.Horizontal)
        self._grid_step_slider.setRange(10, 50)
        self._grid_step_slider.setSingleStep(10)
        self._grid_step_slider.setPageStep(10)
        self._grid_step_slider.setTickInterval(10)
        self._grid_step_slider.setTickPosition(QSlider.TicksBelow)
        self._grid_step_slider.setValue(DEFAULT_GRID_STEP_PERCENT)
        self._grid_step_slider.valueChanged.connect(self._on_grid_step_slider_changed)
        self._grid_step_slider.valueChanged.connect(self._on_settings_changed)

        self._grid_step_label = QLabel(f"{DEFAULT_GRID_STEP_PERCENT}%")
        self._grid_step_label.setMinimumWidth(52)

        form.addRow("Grid division:", self._build_slider_row(
            self._grid_step_slider, self._grid_step_label
        ))

        # Update rate slider
        self._update_rate_slider = QSlider(Qt.Horizontal)
        self._update_rate_slider.setRange(30, 120)
        self._update_rate_slider.setSingleStep(10)
        self._update_rate_slider.setPageStep(10)
        self._update_rate_slider.setTickInterval(10)
        self._update_rate_slider.setTickPosition(QSlider.TicksBelow)
        self._update_rate_slider.setValue(DEFAULT_UPDATE_HZ)
        self._update_rate_slider.valueChanged.connect(self._on_update_rate_slider_changed)
        self._update_rate_slider.valueChanged.connect(self._on_settings_changed)

        self._update_rate_label = QLabel(f"{DEFAULT_UPDATE_HZ} Hz")
        self._update_rate_label.setMinimumWidth(52)

        form.addRow("Update rate:", self._build_slider_row(
            self._update_rate_slider, self._update_rate_label
        ))

        # Show steering checkbox
        self._show_steering_checkbox = QCheckBox("Show steering trace (beta)")
        self._show_steering_checkbox.setChecked(DEFAULT_SHOW_STEERING)
        self._show_steering_checkbox.stateChanged.connect(self._on_steering_visible_changed_internal)
        self._show_steering_checkbox.stateChanged.connect(self._on_settings_changed)
        form.addRow("", self._show_steering_checkbox)

        # Show watermark checkbox
        self._show_watermark_checkbox = QCheckBox("Show braking watermark on charts")
        self._show_watermark_checkbox.setChecked(DEFAULT_SHOW_WATERMARK)
        self._show_watermark_checkbox.stateChanged.connect(self._on_watermark_visible_changed_internal)
        self._show_watermark_checkbox.stateChanged.connect(self._on_settings_changed)
        form.addRow("", self._show_watermark_checkbox)

    def _build_slider_row(self, slider: QSlider, label: QLabel) -> QWidget:
        """Build a slider row with label."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(slider, stretch=1)
        layout.addWidget(label)
        return row

    # -------------------------------------------------------------------------
    # Internal callbacks
    # -------------------------------------------------------------------------

    def _on_update_rate_slider_changed(self, hz: int) -> None:
        """Handle update rate slider changes with snapping."""
        hz = max(30, min(120, (hz // 10) * 10))
        if hz != self._update_rate_slider.value():
            self._update_rate_slider.blockSignals(True)
            self._update_rate_slider.setValue(hz)
            self._update_rate_slider.blockSignals(False)
        self._update_rate_label.setText(f"{hz} Hz")
        self._on_update_rate_changed(hz)

    def _on_grid_step_slider_changed(self, value: int) -> None:
        """Handle grid step slider changes with snapping."""
        step = max(10, min(50, (value // 10) * 10))
        if step != value:
            self._grid_step_slider.blockSignals(True)
            self._grid_step_slider.setValue(step)
            self._grid_step_slider.blockSignals(False)
        self._grid_step_label.setText(f"{step}%")
        self._on_grid_step_changed(step)

    def _on_steering_visible_changed_internal(self, state: int) -> None:
        """Handle steering visibility checkbox changes."""
        visible = state == Qt.Checked.value
        self._on_steering_visible_changed(visible)

    def _on_watermark_visible_changed_internal(self, state: int) -> None:
        """Handle watermark visibility checkbox changes."""
        visible = state == Qt.Checked.value
        self._on_watermark_visible_changed(visible)
