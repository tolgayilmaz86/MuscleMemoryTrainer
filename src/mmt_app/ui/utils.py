"""Shared UI utilities for Muscle Memory Trainer.

This module provides reusable components and helper functions used across
UI modules to promote DRY principles and maintain consistency.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSlider,
    QWidget,
)


# Constants
MAX_REPORT_LEN = 1024
MAX_READS_PER_TICK = 50
DEFAULT_UPDATE_RATE_HZ = 20

# Axis scaling defaults (raw device values)
AXIS_VALUE_MIN = 0
AXIS_VALUE_MAX = 255

# Percentage axis constants
AXIS_MIN = 0
AXIS_MAX = 100


def resource_path(*parts: str) -> Path:
    """Get the absolute path to a bundled resource file.

    Handles both development mode and PyInstaller bundled executables.

    Args:
        *parts: Path components relative to the resources directory.

    Returns:
        Absolute path to the resource.
    """
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base_path.joinpath("resources", *parts)


def scale_axis(value: int, lo: int = AXIS_VALUE_MIN, hi: int = AXIS_VALUE_MAX) -> float:
    """Normalize an integer axis value to [0,1] given bounds.

    Args:
        value: The raw axis value to scale.
        lo: The minimum expected value (default 0).
        hi: The maximum expected value (default 255).

    Returns:
        Normalized value in range [0.0, 1.0].
    """
    if hi == lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / float(hi - lo)))


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value to the specified range.

    Args:
        value: The value to clamp.
        min_val: Minimum allowed value.
        max_val: Maximum allowed value.

    Returns:
        Clamped value within [min_val, max_val].
    """
    return max(min_val, min(max_val, value))


def clamp_int(value: int, min_val: int, max_val: int) -> int:
    """Clamp an integer value to the specified range.

    Args:
        value: The value to clamp.
        min_val: Minimum allowed value.
        max_val: Maximum allowed value.

    Returns:
        Clamped integer within [min_val, max_val].
    """
    return max(min_val, min(max_val, value))


def snap_to_step(value: int, step: int) -> int:
    """Round a value to the nearest step increment.

    Args:
        value: The value to snap.
        step: The step size to snap to.

    Returns:
        Value rounded to nearest step.
    """
    if step <= 0:
        return value
    return int(round(value / step) * step)


class SliderWithLabel(QWidget):
    """A reusable slider widget with an adjacent value label.

    This composite widget provides a horizontal slider with a label
    displaying the current value, reducing boilerplate for slider rows.
    """

    def __init__(
        self,
        *,
        min_value: int,
        max_value: int,
        default_value: int,
        tick_interval: int = 5,
        single_step: int = 1,
        page_step: int = 5,
        suffix: str = "",
        label_width: int = 52,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize the slider with label widget.

        Args:
            min_value: Minimum slider value.
            max_value: Maximum slider value.
            default_value: Initial value.
            tick_interval: Spacing between tick marks.
            single_step: Value change per arrow key press.
            page_step: Value change per page up/down.
            suffix: Suffix to append to label (e.g., "%", " Hz").
            label_width: Fixed width for the value label.
            parent: Parent widget.
        """
        super().__init__(parent)
        self._suffix = suffix

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(min_value, max_value)
        self.slider.setSingleStep(single_step)
        self.slider.setPageStep(page_step)
        self.slider.setTickInterval(tick_interval)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setValue(default_value)

        self.label = QLabel()
        self.label.setMinimumWidth(label_width)
        self._update_label(default_value)

        self.slider.valueChanged.connect(self._update_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.slider, stretch=1)
        layout.addWidget(self.label)

    def _update_label(self, value: int) -> None:
        """Update the label text when slider value changes."""
        self.label.setText(f"{value}{self._suffix}")

    def value(self) -> int:
        """Get the current slider value."""
        return self.slider.value()

    def setValue(self, value: int) -> None:  # noqa: N802 (Qt naming convention)
        """Set the slider value."""
        self.slider.setValue(value)

    def setValueSilent(self, value: int) -> None:  # noqa: N802 (Qt naming convention)
        """Set value without emitting valueChanged signal."""
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self._update_label(value)

    @property
    def valueChanged(self):  # noqa: N802 (Qt naming convention)
        """Expose the slider's valueChanged signal."""
        return self.slider.valueChanged
