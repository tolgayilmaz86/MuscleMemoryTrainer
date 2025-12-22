"""Calibration settings widget for device configuration.

Provides UI controls for steering range and advanced calibration settings.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mmt_app.config import (
    DEFAULT_PEDALS_REPORT_LEN,
    DEFAULT_WHEEL_REPORT_LEN,
    DEFAULT_THROTTLE_OFFSET,
    DEFAULT_BRAKE_OFFSET,
    DEFAULT_STEERING_OFFSET,
    DEFAULT_STEERING_RANGE,
    DEFAULT_STEERING_BITS,
)


class CalibrationSettingsGroup(QGroupBox):
    """Widget for calibration-related settings.

    Provides controls for:
    - Input Setup Wizard button
    - Calibrate Steering button
    - Wheel rotation slider
    - Advanced settings (report lengths, byte offsets, bit depth)
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_setup_wizard: Callable[[], None] | None = None,
        on_calibrate_steering: Callable[[], None] | None = None,
        on_steering_range_changed: Callable[[int], None] | None = None,
    ) -> None:
        """Initialize the calibration settings group.

        Args:
            parent: Parent widget.
            on_setup_wizard: Callback when setup wizard button clicked.
            on_calibrate_steering: Callback when calibrate steering button clicked.
            on_steering_range_changed: Callback when steering range slider changes.
        """
        super().__init__("Calibration", parent)

        self._on_setup_wizard = on_setup_wizard or (lambda: None)
        self._on_calibrate_steering = on_calibrate_steering or (lambda: None)
        self._on_steering_range_changed = on_steering_range_changed or (lambda _: None)

        self._build_ui()

    # -------------------------------------------------------------------------
    # Public properties
    # -------------------------------------------------------------------------

    @property
    def pedals_report_len(self) -> int:
        """Return the configured pedals report length."""
        return self._pedals_report_len.value()

    @property
    def wheel_report_len(self) -> int:
        """Return the configured wheel report length."""
        return self._wheel_report_len.value()

    @property
    def throttle_offset(self) -> int:
        """Return the configured throttle byte offset."""
        return self._throttle_offset.value()

    @property
    def brake_offset(self) -> int:
        """Return the configured brake byte offset."""
        return self._brake_offset.value()

    @property
    def steering_offset(self) -> int:
        """Return the configured steering byte offset."""
        return self._steering_offset.value()

    @property
    def steering_bits(self) -> int:
        """Return the steering bit depth (8, 16, or 32)."""
        return self._steering_bits.currentData()

    @property
    def steering_range(self) -> int:
        """Return the steering range (wheel rotation degrees)."""
        return self._steering_range_slider.value()

    # -------------------------------------------------------------------------
    # Public setters
    # -------------------------------------------------------------------------

    def set_pedals_report_len(self, value: int) -> None:
        """Set the pedals report length."""
        self._pedals_report_len.setValue(value)

    def set_wheel_report_len(self, value: int) -> None:
        """Set the wheel report length."""
        self._wheel_report_len.setValue(value)

    def set_throttle_offset(self, value: int) -> None:
        """Set the throttle byte offset."""
        self._throttle_offset.setValue(value)

    def set_brake_offset(self, value: int) -> None:
        """Set the brake byte offset."""
        self._brake_offset.setValue(value)

    def set_steering_offset(self, value: int) -> None:
        """Set the steering byte offset."""
        self._steering_offset.setValue(value)

    def set_steering_bits(self, bits: int) -> None:
        """Set the steering bit depth."""
        bits_index = self._steering_bits.findData(bits)
        if bits_index >= 0:
            self._steering_bits.setCurrentIndex(bits_index)

    def set_steering_range(self, degrees: int) -> None:
        """Set the steering range (wheel rotation degrees)."""
        clamped = max(180, min(1080, degrees))
        self._steering_range_slider.setValue(clamped)

    # -------------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the calibration settings layout."""
        layout = QVBoxLayout(self)

        # Setup wizard and calibrate steering buttons
        wizard_row = QWidget()
        wizard_layout = QHBoxLayout(wizard_row)
        wizard_layout.setContentsMargins(0, 0, 0, 0)

        setup_wizard_btn = QPushButton("🔧 Input Setup Wizard")
        setup_wizard_btn.setToolTip("Auto-detect pedal and wheel settings - recommended for first-time setup")
        setup_wizard_btn.clicked.connect(self._on_setup_wizard)
        setup_wizard_btn.setMinimumHeight(32)

        calibrate_steering_btn = QPushButton("🔄 Calibrate Steering")
        calibrate_steering_btn.setToolTip("Full calibration: turn wheel fully left, then right to find center")
        calibrate_steering_btn.clicked.connect(self._on_calibrate_steering)
        calibrate_steering_btn.setMinimumHeight(32)

        wizard_layout.addWidget(setup_wizard_btn)
        wizard_layout.addWidget(calibrate_steering_btn)
        wizard_layout.addStretch()
        layout.addWidget(wizard_row)

        # Steering range slider
        form = QFormLayout()
        layout.addLayout(form)

        self._steering_range_slider = QSlider(Qt.Horizontal)
        self._steering_range_slider.setObjectName("steeringRangeSlider")
        self._steering_range_slider.setRange(180, 1080)
        self._steering_range_slider.setSingleStep(10)
        self._steering_range_slider.setPageStep(90)
        self._steering_range_slider.setTickInterval(90)
        self._steering_range_slider.setTickPosition(QSlider.TicksBelow)
        self._steering_range_slider.setValue(DEFAULT_STEERING_RANGE)
        self._steering_range_slider.valueChanged.connect(self._on_steering_range_changed)

        self._steering_range_label = QLabel(f"{DEFAULT_STEERING_RANGE}°")
        self._steering_range_label.setObjectName("steeringRangeValue")
        self._steering_range_label.setStyleSheet("color: #f97316;")
        self._steering_range_label.setMinimumWidth(52)
        self._steering_range_slider.valueChanged.connect(
            lambda v: self._steering_range_label.setText(f"{int(v)}°")
        )

        steering_range_row = QWidget()
        steering_range_layout = QHBoxLayout(steering_range_row)
        steering_range_layout.setContentsMargins(0, 0, 0, 0)
        steering_range_layout.addWidget(self._steering_range_slider, stretch=1)
        steering_range_layout.addWidget(self._steering_range_label)

        form.addRow("Wheel rotation:", steering_range_row)

        # Advanced settings (collapsible)
        self._advanced_checkbox = QCheckBox("Show advanced settings")
        self._advanced_checkbox.setChecked(False)
        self._advanced_checkbox.stateChanged.connect(self._toggle_advanced_settings)
        layout.addWidget(self._advanced_checkbox)

        self._advanced_widget = self._build_advanced_settings()
        self._advanced_widget.setVisible(False)
        layout.addWidget(self._advanced_widget)

    def _build_advanced_settings(self) -> QWidget:
        """Build the advanced settings widget."""
        widget = QWidget()
        form = QFormLayout(widget)
        form.setContentsMargins(0, 0, 0, 0)

        # Pedals report length
        self._pedals_report_len = QSpinBox()
        self._pedals_report_len.setRange(1, 64)
        self._pedals_report_len.setValue(DEFAULT_PEDALS_REPORT_LEN)
        form.addRow("Pedals report length:", self._pedals_report_len)

        # Wheel report length
        self._wheel_report_len = QSpinBox()
        self._wheel_report_len.setRange(1, 64)
        self._wheel_report_len.setValue(DEFAULT_WHEEL_REPORT_LEN)
        form.addRow("Wheel report length:", self._wheel_report_len)

        # Throttle offset
        self._throttle_offset = QSpinBox()
        self._throttle_offset.setRange(0, 63)
        self._throttle_offset.setValue(DEFAULT_THROTTLE_OFFSET)
        form.addRow("Throttle byte offset:", self._throttle_offset)

        # Brake offset
        self._brake_offset = QSpinBox()
        self._brake_offset.setRange(0, 63)
        self._brake_offset.setValue(DEFAULT_BRAKE_OFFSET)
        form.addRow("Brake byte offset:", self._brake_offset)

        # Steering offset
        self._steering_offset = QSpinBox()
        self._steering_offset.setRange(0, 63)
        self._steering_offset.setValue(DEFAULT_STEERING_OFFSET)
        form.addRow("Steering byte offset:", self._steering_offset)

        # Steering bit depth selector
        self._steering_bits = QComboBox()
        self._steering_bits.addItem("8-bit (1 byte)", 8)
        self._steering_bits.addItem("16-bit (2 bytes)", 16)
        self._steering_bits.addItem("32-bit signed (4 bytes)", 32)
        self._steering_bits.setCurrentIndex(1)  # Default to 16-bit
        self._steering_bits.setToolTip(
            "Select the bit depth of your wheel's steering value.\n"
            "Most wheels use 16-bit. VNM and some direct drive wheels use 32-bit signed."
        )
        form.addRow("Steering format:", self._steering_bits)

        return widget

    def _toggle_advanced_settings(self, state: int) -> None:
        """Toggle visibility of advanced calibration settings."""
        self._advanced_widget.setVisible(state == Qt.Checked.value)
