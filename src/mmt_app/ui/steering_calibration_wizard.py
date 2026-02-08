"""Steering calibration wizard for wheel center and range detection.

Provides a multi-step dialog to capture center, left, and right positions
and auto-detect steering parameters. Supports known device presets for
instant configuration of popular wheels.
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
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mmt_app.input.hid_backend import HidSession
from mmt_app.input.calibration import MAX_READS_PER_TICK, STEERING_CAPTURE_MS
from mmt_app.input.device_presets import find_wheel_preset, WheelPreset


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
        self._preset: WheelPreset | None = None

        # Check for known device preset
        self._check_for_preset()

        self._setup_timers()
        self._build_ui()

    def _check_for_preset(self) -> None:
        """Check if the connected wheel matches a known preset."""
        if not self._wheel_session.is_open:
            return

        vendor_id = self._wheel_session.vendor_id
        product_id = self._wheel_session.product_id

        if vendor_id and product_id:
            self._preset = find_wheel_preset(vendor_id, product_id)

    def _offer_preset(self) -> bool:
        """Offer to use a known preset if available.

        Returns:
            True if user accepted the preset and calibration is complete,
            False if user wants manual calibration.
        """
        if not self._preset:
            return False

        reply = QMessageBox.question(
            self,
            "Known Device Detected",
            f"Your wheel '{self._preset.name}' is recognized!\n\n"
            f"Pre-configured settings:\n"
            f"  • Steering offset: {self._preset.steering_offset}\n"
            f"  • Bit depth: {self._preset.steering_bits}-bit\n\n"
            "Would you like to use these settings?\n"
            "(Click 'No' to run manual calibration instead)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if reply == QMessageBox.Yes:
            self._apply_preset()
            return True
        return False

    def _apply_preset(self) -> None:
        """Apply the detected preset and complete calibration."""
        if not self._preset:
            return

        # Read current center value from wheel
        center = 128  # Default
        if self._wheel_session.is_open:
            report = self._wheel_session.read_latest_report(
                report_len=self._preset.report_len, max_reads=MAX_READS_PER_TICK
            )
            if report and self._preset.steering_offset < len(report):
                if self._preset.steering_bits == 16:
                    offset = self._preset.steering_offset
                    if offset + 2 <= len(report):
                        center = report[offset] | (report[offset + 1] << 8)
                elif self._preset.steering_bits == 8:
                    center = report[self._preset.steering_offset]

        # Calculate reasonable half-range based on bit depth
        if self._preset.steering_bits == 16:
            half_range = 32767  # 16-bit signed half-range
        elif self._preset.steering_bits == 8:
            half_range = 127  # 8-bit half-range
        else:
            half_range = 128

        result = SteeringCalibrationResult(
            offset=self._preset.steering_offset,
            bits=self._preset.steering_bits,
            center=center,
            half_range=half_range,
            report_len=self._preset.report_len,
        )

        self._on_complete(result)
        self._on_status_update(
            f"Using preset for {self._preset.name}: offset {result.offset}, "
            f"{result.bits}-bit, center={result.center}"
        )
        self.close()

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
        self.setWindowTitle("Wheel Calibration - Step 1 of 3")
        self.setMinimumWidth(500)
        self.setMinimumHeight(380)
        self.setModal(True)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)

        # Step indicator
        self._step_label = QLabel("Step 1 of 3")
        self._step_label.setAlignment(Qt.AlignCenter)
        self._step_label.setStyleSheet("font-size: 12px; color: #888; padding: 5px;")
        layout.addWidget(self._step_label)

        # Main instruction label
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("font-size: 15px; font-weight: bold; padding: 10px; color: #fff;")
        layout.addWidget(self._label)

        # Detailed instruction
        self._detail_label = QLabel()
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignCenter)
        self._detail_label.setStyleSheet("font-size: 13px; color: #aaa; padding: 8px;")
        layout.addWidget(self._detail_label)

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
        self._update_instructions_for_stage("center")
        self._on_status_update("Wheel calibration: Center your wheel and click Start Capture.")

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

    def _update_instructions_for_stage(self, stage: str) -> None:
        """Update instructions for the given stage."""
        step_num = {"center": 1, "left": 2, "right": 3}.get(stage, 1)
        self._step_label.setText(f"Step {step_num} of 3")
        self.setWindowTitle(f"Wheel Calibration - Step {step_num} of 3")

        if stage == "center":
            self._label.setText("🎯 Step 1: Capture Center Position")
            self._detail_label.setText(
                "Hold your wheel perfectly CENTERED (straight ahead).\n"
                "Make sure it's not turned left or right.\n"
                "Click 'Start Capture' when ready."
            )
        elif stage == "left":
            self._label.setText("⬅️ Step 2: Capture Full Left Position")
            self._detail_label.setText(
                "Turn your wheel FULLY to the LEFT (as far as it goes).\n"
                "Hold it steady at the maximum left position.\n"
                "Click 'Start Capture' when ready."
            )
        elif stage == "right":
            self._label.setText("➡️ Step 3: Capture Full Right Position")
            self._detail_label.setText(
                "Turn your wheel FULLY to the RIGHT (as far as it goes).\n"
                "Hold it steady at the maximum right position.\n"
                "Click 'Start Capture' when ready."
            )

    def _start_capture(self) -> None:
        """Begin capture for the current pending stage."""
        stage = self._state.pending_stage
        if not stage:
            return

        self._state.current_stage = stage

        stage_colors = {
            "center": "#3b82f6",
            "left": "#f97316",
            "right": "#22c55e",
        }

        # Clear samples for current stage
        if stage == "center":
            self._state.center_reports = []
            self._label.setText("📍 Capturing CENTER position...")
            self._detail_label.setText("Hold wheel steady at center. Capturing for 2 seconds...")
        elif stage == "left":
            self._state.left_reports = []
            self._label.setText("⬅️ Capturing full LEFT position...")
            self._detail_label.setText("Hold wheel steady at full left. Capturing for 2 seconds...")
        else:
            self._state.right_reports = []
            self._label.setText("➡️ Capturing full RIGHT position...")
            self._detail_label.setText("Hold wheel steady at full right. Capturing for 2 seconds...")

        self._set_progress_color(stage_colors.get(stage, "#3b82f6"))
        self._samples_label.setText("Samples: 0")
        self._start_btn.setEnabled(False)
        self._start_btn.setText("Capturing...")

        step_num = {"center": 1, "left": 2, "right": 3}.get(stage, 1)
        self.setWindowTitle(f"Wheel Calibration - Step {step_num} of 3")

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
            self._label.setText(f"✓ Center captured ({sample_count} samples)")
            self._detail_label.setText("Great! Now proceed to the next step.")
            self._update_instructions_for_stage("left")
            self._start_btn.setEnabled(True)
            self._start_btn.setText("Start Capture")
        elif stage == "left":
            self._state.pending_stage = "right"
            self._label.setText(f"✓ Left captured ({sample_count} samples)")
            self._detail_label.setText("Great! Now proceed to the final step.")
            self._update_instructions_for_stage("right")
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
        """Auto-detect steering byte offset, bit depth, center, and half-range.

        Uses an improved algorithm that:
        1. Prioritizes 8-bit and 16-bit values (most common for steering)
        2. Requires low variance at center (stable when not moving)
        3. Requires distinct left/right values with center between them
        4. Uses a scoring system considering range, stability, and bit preference
        """
        state = self._state

        if not state.center_reports or not state.left_reports or not state.right_reports:
            return None

        report_len = len(state.center_reports[0])
        if report_len < 2:
            return None

        candidates = self._find_steering_candidates(report_len)

        if not candidates:
            return None

        # Sort by score (highest first) and pick the best
        candidates.sort(key=lambda c: c["score"], reverse=True)
        best = candidates[0]

        return SteeringCalibrationResult(
            offset=best["offset"],
            bits=best["bits"],
            center=best["center"],
            half_range=best["half_range"],
            report_len=report_len,
        )

    def _find_steering_candidates(self, report_len: int) -> list[dict]:
        """Find all candidate steering axis configurations.

        Returns:
            List of candidate dicts with offset, bits, center, half_range, and score.
        """
        candidates = []

        # Prioritize 8-bit and 16-bit (most common), then 32-bit as fallback
        # Lower bit depths get a slight bonus in scoring
        bit_priority = {8: 1.2, 16: 1.1, 32: 1.0}

        for bits in [8, 16, 32]:
            num_bytes = bits // 8
            for offset in range(report_len - num_bytes + 1):
                result = self._evaluate_candidate(offset, bits)
                if result:
                    # Apply bit depth priority bonus
                    result["score"] *= bit_priority.get(bits, 1.0)
                    candidates.append(result)

        return candidates

    def _evaluate_candidate(self, offset: int, bits: int) -> dict | None:
        """Evaluate a single offset/bits combination as a steering candidate.

        Returns:
            Dict with offset, bits, center, half_range, score if valid, else None.
        """
        state = self._state

        center_vals = [self._read_value(r, offset, bits) for r in state.center_reports]
        left_vals = [self._read_value(r, offset, bits) for r in state.left_reports]
        right_vals = [self._read_value(r, offset, bits) for r in state.right_reports]

        # Filter out None values
        center_vals = [v for v in center_vals if v is not None]
        left_vals = [v for v in left_vals if v is not None]
        right_vals = [v for v in right_vals if v is not None]

        if not center_vals or not left_vals or not right_vals:
            return None

        # Calculate statistics
        center_avg = sum(center_vals) / len(center_vals)
        left_avg = sum(left_vals) / len(left_vals)
        right_avg = sum(right_vals) / len(right_vals)

        center_var = self._variance(center_vals)
        left_var = self._variance(left_vals)
        right_var = self._variance(right_vals)

        # Total range between left and right
        total_range = abs(right_avg - left_avg)

        # Minimum range requirement (scales with bit depth)
        min_range = {8: 30, 16: 500, 32: 5000}.get(bits, 50)
        if total_range < min_range:
            return None

        # Center should be between left and right (with some margin)
        min_pos = min(left_avg, right_avg)
        max_pos = max(left_avg, right_avg)
        margin = total_range * 0.35  # Allow 35% margin

        if not (min_pos - margin <= center_avg <= max_pos + margin):
            return None

        # Center should be relatively stable (low variance)
        # Steering held still should have low jitter
        max_center_var = {8: 25, 16: 1000, 32: 100000}.get(bits, 100)
        if center_var > max_center_var:
            return None

        # Left and right can have some variance (user might wobble at limits)
        # But shouldn't have extreme variance
        max_extreme_var = {8: 100, 16: 5000, 32: 500000}.get(bits, 500)
        if left_var > max_extreme_var or right_var > max_extreme_var:
            return None

        # Calculate score based on multiple factors:
        # 1. Range magnitude (larger is better, but normalized)
        max_theoretical_range = {8: 255, 16: 65535, 32: 4294967295}.get(bits, 255)
        range_score = (total_range / max_theoretical_range) * 100

        # 2. Center stability (lower variance is better)
        stability_score = max(0, 50 - (center_var / max(center_var, 1)))

        # 3. Symmetry bonus (center closer to midpoint of left-right)
        expected_center = (left_avg + right_avg) / 2
        symmetry_error = abs(center_avg - expected_center) / max(total_range, 1)
        symmetry_score = max(0, 30 * (1 - symmetry_error))

        total_score = range_score + stability_score + symmetry_score

        # Calculate half-range
        half_range = max(abs(center_avg - left_avg), abs(right_avg - center_avg))
        half_range = max(int(half_range), 100)  # Minimum 100

        return {
            "offset": offset,
            "bits": bits,
            "center": int(center_avg),
            "half_range": half_range,
            "score": total_score,
        }

    def _read_value(self, report: bytes, offset: int, bits: int) -> int | None:
        """Read a value from a report at given offset with given bit depth."""
        if bits == 32 and offset + 4 <= len(report):
            raw = (report[offset] | (report[offset + 1] << 8) |
                   (report[offset + 2] << 16) | (report[offset + 3] << 24))
            return raw if raw < 0x80000000 else raw - 0x100000000
        elif bits == 16 and offset + 2 <= len(report):
            return report[offset] | (report[offset + 1] << 8)
        elif bits == 8 and offset + 1 <= len(report):
            return report[offset]
        return None

    @staticmethod
    def _variance(values: list[int | float]) -> float:
        """Calculate variance of a list of values."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / len(values)

    def _cancel(self) -> None:
        """Cancel calibration."""
        self._capture_timer.stop()
        self._preview_timer.stop()
        self._on_status_update("Steering calibration canceled.")
        self.close()

    def show(self) -> None:
        """Show the wizard, offering preset if available."""
        # If we have a preset, offer it before showing the full wizard
        if self._preset and self._offer_preset():
            return  # Preset was accepted, dialog already closed
        super().show()

    def closeEvent(self, event) -> None:
        """Clean up on close."""
        self._capture_timer.stop()
        self._preview_timer.stop()
        super().closeEvent(event)
