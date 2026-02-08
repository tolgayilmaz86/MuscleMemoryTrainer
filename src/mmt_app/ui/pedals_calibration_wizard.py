"""Pedals calibration wizard for throttle and brake detection.

Provides a guided wizard to auto-detect pedals report length,
throttle offset, and brake offset with improved accuracy.
Supports known device presets for instant configuration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
from mmt_app.input.calibration import MAX_READS_PER_TICK, CALIBRATION_DURATION_MS
from mmt_app.input.device_presets import find_pedals_preset, PedalsPreset


@dataclass
class PedalsCalibrationResult:
    """Result from pedals calibration wizard."""

    report_len: int | None = None
    throttle_offset: int | None = None
    brake_offset: int | None = None
    throttle_score: float = 0.0
    brake_score: float = 0.0


class PedalsCalibrationWizard(QDialog):
    """Wizard dialog for pedals calibration.

    Guides user through:
    1. Detecting report length
    2. Detecting throttle byte offset
    3. Detecting brake byte offset

    Supports known device presets for instant configuration.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        pedals_session: HidSession,
        on_complete: Callable[[PedalsCalibrationResult], None] | None = None,
        on_status_update: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the pedals calibration wizard.

        Args:
            parent: Parent widget.
            pedals_session: HID session for pedals device.
            on_complete: Callback invoked with calibration result when done.
            on_status_update: Callback invoked with status messages.
        """
        super().__init__(parent)

        self._pedals_session = pedals_session
        self._on_complete = on_complete or (lambda _: None)
        self._on_status_update = on_status_update or (lambda _: None)

        self._result = PedalsCalibrationResult()
        self._current_step = 0
        self._steps = [
            "detect_report_len",
            "detect_throttle",
            "detect_brake",
        ]
        self._preset: PedalsPreset | None = None

        # Check for known device preset
        self._check_for_preset()

        # Calibration state
        self._calibration_phase: str | None = None
        self._baseline_samples: list[bytes] = []
        self._active_samples: list[bytes] = []
        self._current_axis: str | None = None

        self._setup_timers()
        self._build_ui()
        self._run_current_step()

    def _check_for_preset(self) -> None:
        """Check if the connected pedals matches a known preset."""
        if not self._pedals_session.is_open:
            return

        vendor_id = self._pedals_session.vendor_id
        product_id = self._pedals_session.product_id

        if vendor_id and product_id:
            self._preset = find_pedals_preset(vendor_id, product_id)

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
            "Known Pedals Detected",
            f"Your pedals '{self._preset.name}' are recognized!\n\n"
            f"Pre-configured settings:\n"
            f"  • Throttle offset: {self._preset.throttle_offset}\n"
            f"  • Brake offset: {self._preset.brake_offset}\n"
            f"  • Report length: {self._preset.report_len}\n\n"
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

        result = PedalsCalibrationResult(
            report_len=self._preset.report_len,
            throttle_offset=self._preset.throttle_offset,
            brake_offset=self._preset.brake_offset,
            throttle_score=1000.0,  # High confidence for preset
            brake_score=1000.0,
        )

        self._on_complete(result)
        self._on_status_update(
            f"Using preset for {self._preset.name}: "
            f"throttle={result.throttle_offset}, brake={result.brake_offset}"
        )
        self.close()

    def show(self) -> None:
        """Show the wizard, offering preset if available."""
        # If we have a preset, offer it before showing the full wizard
        if self._preset and self._offer_preset():
            return  # Preset was accepted, dialog already closed
        super().show()

    def _setup_timers(self) -> None:
        """Configure internal timers."""
        self._calibration_timer = QTimer(self)
        self._calibration_timer.setInterval(20)
        self._calibration_timer.timeout.connect(self._capture_calibration_sample)

    def _build_ui(self) -> None:
        """Construct the wizard dialog layout."""
        self.setWindowTitle("Pedals Calibration")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setMinimumHeight(350)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # Step indicator
        self._step_label = QLabel()
        self._step_label.setAlignment(Qt.AlignCenter)
        self._step_label.setStyleSheet("font-size: 12px; color: #888; padding: 5px;")
        layout.addWidget(self._step_label)

        # Instruction label
        self._instruction_label = QLabel()
        self._instruction_label.setWordWrap(True)
        self._instruction_label.setAlignment(Qt.AlignCenter)
        self._instruction_label.setStyleSheet(
            "font-size: 15px; font-weight: bold; padding: 15px; color: #fff;"
        )
        layout.addWidget(self._instruction_label)

        # Detailed instruction
        self._detail_label = QLabel()
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignCenter)
        self._detail_label.setStyleSheet("font-size: 13px; color: #aaa; padding: 10px;")
        layout.addWidget(self._detail_label)

        # Live input visualization
        self._viz_frame = QFrame()
        self._viz_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self._viz_frame.setStyleSheet("QFrame { background: #1a1a2e; border-radius: 6px; }")
        viz_layout = QVBoxLayout(self._viz_frame)
        viz_layout.setContentsMargins(15, 15, 15, 15)
        viz_layout.setSpacing(10)

        self._value_label = QLabel("Input: --")
        self._value_label.setAlignment(Qt.AlignCenter)
        self._value_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #22c55e; padding: 8px;"
        )
        viz_layout.addWidget(self._value_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 255)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setMinimumHeight(25)
        self._set_progress_style("baseline")
        viz_layout.addWidget(self._progress)

        self._samples_label = QLabel("Samples: 0")
        self._samples_label.setAlignment(Qt.AlignCenter)
        self._samples_label.setStyleSheet("color: #888; font-size: 12px;")
        viz_layout.addWidget(self._samples_label)

        # Confidence indicator
        self._confidence_label = QLabel()
        self._confidence_label.setAlignment(Qt.AlignCenter)
        self._confidence_label.setStyleSheet("color: #888; font-size: 11px;")
        viz_layout.addWidget(self._confidence_label)

        layout.addWidget(self._viz_frame)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self._cancel)
        btn_layout.addWidget(cancel_btn)

        btn_layout.addStretch()

        self._next_btn = QPushButton("Next")
        self._next_btn.setMinimumWidth(100)
        self._next_btn.setMinimumHeight(35)
        self._next_btn.clicked.connect(self._advance)
        btn_layout.addWidget(self._next_btn)

        layout.addLayout(btn_layout)

        self.rejected.connect(self._cancel)

    def _set_progress_style(self, phase: str) -> None:
        """Set progress bar style based on phase."""
        if phase == "active":
            color1, color2 = "#f97316", "#fb923c"
        elif phase == "detecting":
            color1, color2 = "#3b82f6", "#60a5fa"
        else:
            color1, color2 = "#22c55e", "#4ade80"

        self._progress.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #333;
                border-radius: 4px;
                background: #0a0a14;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {color1}, stop:1 {color2});
                border-radius: 3px;
            }}
        """)

    def _run_current_step(self) -> None:
        """Execute the current wizard step."""
        if self._current_step >= len(self._steps):
            self._finish()
            return

        step = self._steps[self._current_step]
        step_num = self._current_step + 1
        total = len(self._steps)

        self._step_label.setText(f"Step {step_num} of {total}")

        if step == "detect_report_len":
            self._run_report_len_detection()
        elif step == "detect_throttle":
            self._run_throttle_detection()
        elif step == "detect_brake":
            self._run_brake_detection()

    def _run_report_len_detection(self) -> None:
        """Start report length detection."""
        self._instruction_label.setText("📏 Detecting Report Length")
        self._detail_label.setText(
            "Keep ALL pedals RELEASED (not pressed).\n"
            "The wizard will automatically detect the correct report length."
        )
        self._viz_frame.setVisible(False)
        self._next_btn.setEnabled(False)
        self._next_btn.setText("Detecting...")
        self._on_status_update("Detecting pedals report length...")

        QTimer.singleShot(500, self._detect_report_length)

    def _detect_report_length(self) -> None:
        """Auto-detect report length."""
        if not self._pedals_session.is_open:
            self._instruction_label.setText("❌ Error: Pedals not connected!")
            self._detail_label.setText("Please connect your pedals device first.")
            QTimer.singleShot(2000, self._advance)
            return

        max_len = 64
        samples = []
        for _ in range(30):  # More samples for better accuracy
            report = self._pedals_session.read_latest_report(report_len=max_len, max_reads=5)
            if not report:
                report = self._pedals_session.read_report(report_len=max_len, timeout_ms=50)
            if report:
                samples.append(len(report))

        if samples:
            # Use most common length
            report_len = max(set(samples), key=samples.count)
            self._result.report_len = report_len
            self._instruction_label.setText(f"✓ Report Length Detected: {report_len} bytes")
            self._detail_label.setText("Continuing to throttle detection...")
            self._on_status_update(f"Pedals report length: {report_len} bytes")
        else:
            self._instruction_label.setText("⚠ Could not detect report length")
            self._detail_label.setText("Using default value. You can adjust in advanced settings.")
            self._result.report_len = 4  # Default

        QTimer.singleShot(2000, self._advance)

    def _run_throttle_detection(self) -> None:
        """Start throttle detection."""
        self._current_axis = "throttle"
        self._instruction_label.setText("🎮 Throttle Pedal Detection")
        self._detail_label.setText(
            "This will detect which byte contains your throttle input.\n"
            "Follow the instructions carefully for best results."
        )
        self._viz_frame.setVisible(True)
        self._next_btn.setText("Start Detection")
        self._next_btn.clicked.disconnect()
        self._next_btn.clicked.connect(self._start_axis_detection)
        self._next_btn.setEnabled(True)  # Enable button for user to start
        self._on_status_update("Ready to detect throttle pedal...")

    def _run_brake_detection(self) -> None:
        """Start brake detection."""
        self._current_axis = "brake"
        self._instruction_label.setText("🛑 Brake Pedal Detection")
        self._detail_label.setText(
            "This will detect which byte contains your brake input.\n"
            "Follow the instructions carefully for best results."
        )
        self._viz_frame.setVisible(True)
        self._next_btn.setText("Start Detection")
        self._next_btn.clicked.disconnect()
        self._next_btn.clicked.connect(self._start_axis_detection)
        self._next_btn.setEnabled(True)  # Enable button for user to start
        self._on_status_update("Ready to detect brake pedal...")

    def _start_axis_detection(self) -> None:
        """Start detecting axis offset for current step."""
        if not self._pedals_session.is_open:
            self._instruction_label.setText("❌ Error: Pedals not connected!")
            return

        report_len = self._result.report_len or 4
        self._calibration_phase = "baseline"
        self._baseline_samples = []
        self._active_samples = []
        self._set_progress_style("baseline")

        axis_name = self._current_axis.upper()
        self._instruction_label.setText(f"📊 Phase 1 of 2: Baseline Capture")
        self._detail_label.setText(
            f"Keep {axis_name} pedal FULLY RELEASED.\n"
            f"Keep the other pedal released too.\n"
            f"Recording resting position for 3 seconds..."
        )

        self._next_btn.setEnabled(False)
        self._next_btn.setText("Capturing baseline...")
        self._confidence_label.setText("")

        self._calibration_timer.start()
        QTimer.singleShot(3000, self._switch_to_active_capture)  # 3 seconds baseline

    def _switch_to_active_capture(self) -> None:
        """Switch from baseline to active capture."""
        self._calibration_phase = "active"
        self._set_progress_style("active")

        axis_name = self._current_axis.upper()
        self._instruction_label.setText(f"📊 Phase 2 of 2: Active Capture")
        self._detail_label.setText(
            f"Now SLOWLY press and release {axis_name} pedal repeatedly.\n"
            f"Move it through its FULL range (0% to 100%).\n"
            f"Keep the other pedal released.\n"
            f"Recording for 4 seconds..."
        )

        QTimer.singleShot(4000, self._finish_axis_detection)  # 4 seconds active

    def _finish_axis_detection(self) -> None:
        """Complete axis detection and compute offset."""
        self._calibration_timer.stop()
        self._calibration_phase = None

        if not self._baseline_samples or not self._active_samples:
            self._instruction_label.setText(f"⚠ {self._current_axis.capitalize()} detection failed")
            self._detail_label.setText("Not enough data captured. Please try again.")
            self._next_btn.setEnabled(True)
            self._next_btn.setText("Retry")
            self._next_btn.clicked.disconnect()
            self._next_btn.clicked.connect(self._start_axis_detection)
            return

        offset, score = self._compute_best_offset_improved()

        # Store result
        if self._current_axis == "throttle":
            self._result.throttle_offset = offset
            self._result.throttle_score = score
        elif self._current_axis == "brake":
            self._result.brake_offset = offset
            self._result.brake_score = score

        self._viz_frame.setVisible(False)

        if score > 200:  # High confidence threshold
            confidence = "High"
            color = "#22c55e"
        elif score > 100:
            confidence = "Medium"
            color = "#fbbf24"
        else:
            confidence = "Low"
            color = "#f97316"

        self._instruction_label.setText(
            f"✓ {self._current_axis.capitalize()} detected at byte {offset}"
        )
        self._detail_label.setText(
            f"Confidence: {confidence} (score: {score:.1f})\n"
            f"Continuing to next step..."
        )
        self._confidence_label.setText(f"Confidence: {confidence}")

        self._on_status_update(
            f"{self._current_axis.capitalize()} detected at byte {offset} (confidence: {confidence})"
        )

        self._next_btn.setEnabled(True)
        self._next_btn.setText("Next")
        self._next_btn.clicked.disconnect()
        self._next_btn.clicked.connect(self._advance)

        QTimer.singleShot(2000, lambda: None)  # Show result for 2 seconds

    def _capture_calibration_sample(self) -> None:
        """Capture a sample during calibration."""
        if not self._pedals_session.is_open or not self._calibration_phase:
            return

        report_len = self._result.report_len or 4
        report = self._pedals_session.read_latest_report(
            report_len=report_len, max_reads=MAX_READS_PER_TICK
        )
        if report is None:
            report = self._pedals_session.read_report(report_len=report_len, timeout_ms=15)
        if report is None:
            return

        if self._calibration_phase == "active":
            self._active_samples.append(report)
            sample_count = len(self._active_samples)
        else:
            self._baseline_samples.append(report)
            sample_count = len(self._baseline_samples)

        # Update visualization
        if len(report) > 0:
            max_val = max(report)
            self._progress.setValue(max_val)
            self._value_label.setText(f"Input: {max_val}")
        self._samples_label.setText(f"Samples: {sample_count}")

    def _compute_best_offset_improved(self) -> tuple[int, float]:
        """Compute best byte offset with improved algorithm."""
        if not self._baseline_samples or not self._active_samples:
            return (0, 0.0)

        min_len = min(len(b) for b in self._baseline_samples + self._active_samples)
        best_offset = 0
        best_score = 0.0

        for offset in range(min_len):
            baseline_vals = [b[offset] for b in self._baseline_samples]
            active_vals = [a[offset] for a in self._active_samples]

            # Improved scoring: variance difference + range difference
            baseline_var = self._variance(baseline_vals)
            active_var = self._variance(active_vals)
            baseline_range = max(baseline_vals) - min(baseline_vals)
            active_range = max(active_vals) - min(active_vals)

            # Variance difference (how much more variation in active)
            variance_score = max(0, active_var - baseline_var)

            # Range difference (how much larger range in active)
            range_score = max(0, active_range - baseline_range) * 0.5

            # Mean difference (how much the mean changed)
            baseline_mean = sum(baseline_vals) / len(baseline_vals)
            active_mean = sum(active_vals) / len(active_vals)
            mean_diff = abs(active_mean - baseline_mean)

            # Combined score (weighted)
            score = variance_score * 2.0 + range_score + mean_diff * 0.3

            # Bonus for large active range (indicates good detection)
            if active_range > 100:
                score *= 1.5

            if score > best_score:
                best_score = score
                best_offset = offset

        return (best_offset, best_score)

    @staticmethod
    def _variance(values: list[int]) -> float:
        """Compute variance of values."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((v - mean) ** 2 for v in values) / len(values)

    def _advance(self) -> None:
        """Advance to the next wizard step."""
        self._current_step += 1
        self._run_current_step()

    def _finish(self) -> None:
        """Complete the wizard."""
        self._calibration_timer.stop()
        self._on_complete(self._result)
        self._on_status_update("Pedals calibration complete! Settings saved.")
        self.close()

    def _cancel(self) -> None:
        """Cancel the wizard."""
        self._calibration_timer.stop()
        self._on_status_update("Pedals calibration canceled.")
        self.close()

    def closeEvent(self, event) -> None:
        """Clean up on close."""
        self._calibration_timer.stop()
        super().closeEvent(event)



