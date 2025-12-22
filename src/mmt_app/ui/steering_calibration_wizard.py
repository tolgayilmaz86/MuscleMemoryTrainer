"""Steering calibration wizard for wheel center and range detection.

Provides a multi-step dialog to capture center, left, and right positions
and auto-detect steering parameters.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mmt_app.input.hid_backend import HidSession
from mmt_app.input.calibration import MAX_READS_PER_TICK, STEERING_CAPTURE_MS


@dataclass
class SteeringCalibrationResult:
    """Result of steering calibration."""

    offset: int
    bits: int
    center: int
    half_range: int
    report_len: int


@dataclass
class SteeringCalibrationState:
    """Internal state for steering calibration wizard."""

    center_reports: list[bytes] = field(default_factory=list)
    left_reports: list[bytes] = field(default_factory=list)
    right_reports: list[bytes] = field(default_factory=list)
    pending_stage: str | None = None
    current_stage: str | None = None


class SteeringCalibrationWizard(QDialog):
    """Wizard dialog for steering wheel calibration.

    Guides user through capturing center, left, and right positions
    to auto-detect offset, bit depth, center value, and half-range.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        wheel_session: HidSession,
        on_complete: Callable[[SteeringCalibrationResult], None] | None = None,
        on_status_update: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the steering calibration wizard.

        Args:
            parent: Parent widget.
            wheel_session: HID session for the wheel device.
            on_complete: Callback invoked with calibration result when done.
            on_status_update: Callback invoked with status messages.
        """
        super().__init__(parent)

        self._wheel_session = wheel_session
        self._on_complete = on_complete or (lambda _: None)
        self._on_status_update = on_status_update or (lambda _: None)

        self._state = SteeringCalibrationState()
        self._state.pending_stage = "center"

        self._setup_timers()
        self._build_ui()

    def _setup_timers(self) -> None:
        """Configure internal timers."""
        self._capture_timer = QTimer(self)
        self._capture_timer.setInterval(20)
        self._capture_timer.timeout.connect(self._capture_sample)

        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(50)
        self._preview_timer.timeout.connect(self._update_preview)

    def _build_ui(self) -> None:
        """Construct the wizard dialog layout."""
        self.setWindowTitle("Steering Calibration - Step 1 of 3")
        self.setMinimumWidth(420)
        self.setMinimumHeight(280)
        self.setModal(True)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)

        # Instruction label
        self._label = QLabel(
            "🎯 Hold your wheel at CENTER position\n\n"
            "Click Start to capture the center point."
        )
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("font-size: 13px; padding: 8px;")
        layout.addWidget(self._label)

        # Live input visualization
        viz_frame = QFrame()
        viz_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        viz_frame.setStyleSheet("QFrame { background: #1a1a2e; border-radius: 6px; }")
        viz_layout = QVBoxLayout(viz_frame)
        viz_layout.setContentsMargins(15, 10, 15, 10)

        # Steering value display
        self._value_label = QLabel("Position: --")
        self._value_label.setAlignment(Qt.AlignCenter)
        self._value_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #3b82f6; padding: 5px;"
        )
        viz_layout.addWidget(self._value_label)

        # Progress bar for steering position
        self._progress = QProgressBar()
        self._progress.setRange(0, 255)
        self._progress.setValue(128)
        self._progress.setTextVisible(False)
        self._progress.setMinimumHeight(20)
        self._set_progress_color("#3b82f6")
        viz_layout.addWidget(self._progress)

        # Samples counter
        self._samples_label = QLabel("Samples: 0")
        self._samples_label.setAlignment(Qt.AlignCenter)
        self._samples_label.setStyleSheet("color: #888; font-size: 11px;")
        viz_layout.addWidget(self._samples_label)

        layout.addWidget(viz_frame)
        layout.addStretch()

        # Buttons
        self._start_btn = QPushButton("Start Capture")
        self._start_btn.setMinimumWidth(100)
        self._start_btn.setMinimumHeight(32)
        self._start_btn.clicked.connect(self._start_capture)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(80)
        cancel_btn.clicked.connect(self._cancel)

        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(self._start_btn)
        btns.addWidget(cancel_btn)
        btns.addStretch()
        layout.addLayout(btns)

        self.setLayout(layout)

        # Start live preview
        self._preview_timer.start()
        self._on_status_update("Steering calibration: Center your wheel and click Start.")

    def _set_progress_color(self, color: str) -> None:
        """Set the progress bar chunk color."""
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #333;
                border-radius: 4px;
                background: #0a0a14;
            }}
            QProgressBar::chunk {{
                background: {color};
                border-radius: 3px;
            }}
        """)

    # -------------------------------------------------------------------------
    # Capture workflow
    # -------------------------------------------------------------------------

    def _start_capture(self) -> None:
        """Begin capture for the current pending stage."""
        stage = self._state.pending_stage
        if not stage:
            return

        self._state.current_stage = stage

        stage_texts = {
            "center": "📍 Capturing CENTER position...\n\nHold steady!",
            "left": "⬅️ Capturing full LEFT position...\n\nHold steady!",
            "right": "➡️ Capturing full RIGHT position...\n\nHold steady!",
        }
        stage_colors = {
            "center": "#3b82f6",
            "left": "#f97316",
            "right": "#22c55e",
        }

        # Clear samples for current stage
        if stage == "center":
            self._state.center_reports = []
        elif stage == "left":
            self._state.left_reports = []
        else:
            self._state.right_reports = []

        self._label.setText(stage_texts.get(stage, ""))
        self._set_progress_color(stage_colors.get(stage, "#3b82f6"))
        self._samples_label.setText("Samples: 0")
        self._start_btn.setEnabled(False)
        self._start_btn.setText("Capturing...")

        step_num = {"center": 1, "left": 2, "right": 3}.get(stage, 1)
        self.setWindowTitle(f"Steering Calibration - Step {step_num} of 3")

        self._on_status_update(f"Capturing {stage} position...")

        self._capture_timer.start()
        QTimer.singleShot(STEERING_CAPTURE_MS, self._complete_stage)

    def _complete_stage(self) -> None:
        """Complete the current capture stage and advance."""
        self._capture_timer.stop()
        stage = self._state.current_stage
        self._state.current_stage = None

        # Get sample count
        sample_count = 0
        if stage == "center":
            sample_count = len(self._state.center_reports)
        elif stage == "left":
            sample_count = len(self._state.left_reports)
        elif stage == "right":
            sample_count = len(self._state.right_reports)

        if stage == "center":
            self._state.pending_stage = "left"
            self.setWindowTitle("Steering Calibration - Step 2 of 3")
            self._label.setText(
                f"✓ Center captured ({sample_count} samples)\n\n"
                "⬅️ Now turn wheel fully LEFT and hold.\n"
                "Click Start when ready."
            )
            self._start_btn.setEnabled(True)
            self._start_btn.setText("Start Capture")
        elif stage == "left":
            self._state.pending_stage = "right"
            self.setWindowTitle("Steering Calibration - Step 3 of 3")
            self._label.setText(
                f"✓ Left captured ({sample_count} samples)\n\n"
                "➡️ Now turn wheel fully RIGHT and hold.\n"
                "Click Start when ready."
            )
            self._start_btn.setEnabled(True)
            self._start_btn.setText("Start Capture")
        elif stage == "right":
            self._state.pending_stage = None
            self._finish_calibration()

    def _capture_sample(self) -> None:
        """Capture a raw HID report during calibration."""
        if not self._wheel_session.is_open or not self._state.current_stage:
            return

        report = self._wheel_session.read_latest_report(
            report_len=64, max_reads=MAX_READS_PER_TICK
        )
        if not report:
            return

        stage = self._state.current_stage
        sample_count = 0

        if stage == "center":
            self._state.center_reports.append(bytes(report))
            sample_count = len(self._state.center_reports)
        elif stage == "left":
            self._state.left_reports.append(bytes(report))
            sample_count = len(self._state.left_reports)
        elif stage == "right":
            self._state.right_reports.append(bytes(report))
            sample_count = len(self._state.right_reports)

        # Update visualization
        if len(report) > 0:
            max_val = max(report)
            self._value_label.setText(f"Position: {max_val}")
            self._progress.setValue(max_val)
            self._samples_label.setText(f"Samples: {sample_count}")

    def _update_preview(self) -> None:
        """Update live steering position display."""
        if not self._wheel_session.is_open:
            return
        if self._state.current_stage:
            return  # Don't update during capture

        report = self._wheel_session.read_latest_report(
            report_len=64, max_reads=MAX_READS_PER_TICK
        )
        if not report or len(report) == 0:
            return

        max_val = max(report)
        self._value_label.setText(f"Position: {max_val}")
        self._progress.setValue(max_val)

    def _finish_calibration(self) -> None:
        """Complete calibration with auto-detection."""
        self._capture_timer.stop()
        self._preview_timer.stop()

        state = self._state
        if not state.center_reports or not state.left_reports or not state.right_reports:
            self._on_status_update("Calibration failed: not enough data captured.")
            self.close()
            return

        result = self._detect_parameters()
        if result is None:
            self._on_status_update("Calibration failed: could not detect steering axis. Try turning wheel more.")
            self.close()
            return

        self._on_complete(result)
        self._on_status_update(
            f"Detected: offset {result.offset}, {result.bits}-bit. Center: {result.center}"
        )
        self.close()

    def _detect_parameters(self) -> SteeringCalibrationResult | None:
        """Auto-detect steering byte offset, bit depth, center, and half-range."""
        state = self._state

        if not state.center_reports or not state.left_reports or not state.right_reports:
            return None

        report_len = len(state.center_reports[0])
        if report_len < 2:
            return None

        def read_value(report: bytes, offset: int, bits: int) -> int | None:
            if bits == 32 and offset + 4 <= len(report):
                raw = (report[offset] | (report[offset + 1] << 8) |
                       (report[offset + 2] << 16) | (report[offset + 3] << 24))
                return raw if raw < 0x80000000 else raw - 0x100000000
            elif bits == 16 and offset + 2 <= len(report):
                return report[offset] | (report[offset + 1] << 8)
            elif bits == 8 and offset + 1 <= len(report):
                return report[offset]
            return None

        best_offset = None
        best_bits = None
        best_range = 0

        for bits in [32, 16, 8]:
            num_bytes = bits // 8
            for offset in range(report_len - num_bytes + 1):
                center_vals = [read_value(r, offset, bits) for r in state.center_reports]
                left_vals = [read_value(r, offset, bits) for r in state.left_reports]
                right_vals = [read_value(r, offset, bits) for r in state.right_reports]

                if None in center_vals or None in left_vals or None in right_vals:
                    continue

                center_avg = sum(center_vals) / len(center_vals)
                left_avg = sum(left_vals) / len(left_vals)
                right_avg = sum(right_vals) / len(right_vals)

                total_range = abs(right_avg - left_avg)
                if total_range < 50:
                    continue

                min_val = min(left_avg, right_avg)
                max_val = max(left_avg, right_avg)
                margin = total_range * 0.3
                center_in_range = (min_val - margin) <= center_avg <= (max_val + margin)

                if not center_in_range:
                    continue

                if total_range > best_range:
                    best_range = total_range
                    best_offset = offset
                    best_bits = bits

        if best_offset is None or best_bits is None:
            return None

        # Compute final values
        center_vals = [read_value(r, best_offset, best_bits) for r in state.center_reports]
        left_vals = [read_value(r, best_offset, best_bits) for r in state.left_reports]
        right_vals = [read_value(r, best_offset, best_bits) for r in state.right_reports]

        center_val = int(sum(center_vals) / len(center_vals))
        left_val = int(sum(left_vals) / len(left_vals))
        right_val = int(sum(right_vals) / len(right_vals))

        half_range = max(abs(center_val - left_val), abs(right_val - center_val))
        half_range = max(half_range, 100)

        return SteeringCalibrationResult(
            offset=best_offset,
            bits=best_bits,
            center=center_val,
            half_range=half_range,
            report_len=report_len,
        )

    def _cancel(self) -> None:
        """Cancel calibration."""
        self._capture_timer.stop()
        self._preview_timer.stop()
        self._on_status_update("Steering calibration canceled.")
        self.close()

    def closeEvent(self, event) -> None:
        """Clean up on close."""
        self._capture_timer.stop()
        self._preview_timer.stop()
        super().closeEvent(event)
