"""Input setup wizard for comprehensive device configuration.

Guides users through auto-detecting report lengths, axis offsets,
and steering center position.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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
from mmt_app.input.calibration import MAX_READS_PER_TICK, CALIBRATION_DURATION_MS


@dataclass
class WizardStep:
    """Definition of a wizard step."""

    type: str  # 'detect_report_len', 'detect_axis', 'set_center'
    device: str  # 'pedals' or 'wheel'
    title: str
    instruction: str
    axis: str | None = None  # For 'detect_axis' steps


@dataclass
class InputSetupResult:
    """Result from the input setup wizard."""

    pedals_report_len: int | None = None
    wheel_report_len: int | None = None
    throttle_offset: int | None = None
    brake_offset: int | None = None
    steering_offset: int | None = None
    steering_center: int | None = None


class InputSetupWizard(QDialog):
    """Wizard dialog for comprehensive input device setup.

    Guides user through:
    1. Detecting report lengths for connected devices
    2. Auto-detecting axis byte offsets
    3. Capturing steering center position
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        pedals_session: HidSession,
        wheel_session: HidSession,
        get_pedals_report_len: Callable[[], int],
        get_wheel_report_len: Callable[[], int],
        get_steering_offset: Callable[[], int],
        get_steering_bits: Callable[[], int],
        on_axis_detected: Callable[[str, str, int, float], None] | None = None,
        on_report_len_detected: Callable[[str, int], None] | None = None,
        on_steering_center_captured: Callable[[int], None] | None = None,
        on_complete: Callable[[InputSetupResult], None] | None = None,
        on_status_update: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the input setup wizard.

        Args:
            parent: Parent widget.
            pedals_session: HID session for pedals.
            wheel_session: HID session for wheel.
            get_pedals_report_len: Callback to get current pedals report length.
            get_wheel_report_len: Callback to get current wheel report length.
            get_steering_offset: Callback to get current steering offset.
            get_steering_bits: Callback to get current steering bit depth.
            on_axis_detected: Callback when axis offset detected (device, axis, offset, score).
            on_report_len_detected: Callback when report length detected (device, length).
            on_steering_center_captured: Callback when steering center captured.
            on_complete: Callback when wizard completes.
            on_status_update: Callback for status messages.
        """
        super().__init__(parent)

        self._pedals_session = pedals_session
        self._wheel_session = wheel_session
        self._get_pedals_report_len = get_pedals_report_len
        self._get_wheel_report_len = get_wheel_report_len
        self._get_steering_offset = get_steering_offset
        self._get_steering_bits = get_steering_bits
        self._on_axis_detected = on_axis_detected or (lambda *_: None)
        self._on_report_len_detected = on_report_len_detected or (lambda *_: None)
        self._on_steering_center_captured = on_steering_center_captured or (lambda _: None)
        self._on_complete = on_complete or (lambda _: None)
        self._on_status_update = on_status_update or (lambda _: None)

        self._result = InputSetupResult()
        self._steps: list[WizardStep] = []
        self._current_step = 0

        # Calibration state
        self._calibration_phase: str | None = None
        self._baseline_samples: list[bytes] = []
        self._active_samples: list[bytes] = []

        self._setup_timers()
        self._build_steps()
        self._build_ui()

    def _setup_timers(self) -> None:
        """Configure internal timers."""
        self._calibration_timer = QTimer(self)
        self._calibration_timer.setInterval(20)
        self._calibration_timer.timeout.connect(self._capture_calibration_sample)

        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(50)
        self._preview_timer.timeout.connect(self._update_steering_preview)

    def _build_steps(self) -> None:
        """Build wizard steps based on connected devices."""
        if self._pedals_session.is_open:
            self._steps.append(WizardStep(
                type="detect_report_len",
                device="pedals",
                title="Detecting Pedals",
                instruction="Keep all pedals RELEASED.\n\nDetecting report length...",
            ))
            self._steps.append(WizardStep(
                type="detect_axis",
                device="pedals",
                axis="throttle",
                title="Throttle Pedal",
                instruction="Keep brake RELEASED.\n\nSlowly press and release THROTTLE several times.",
            ))
            self._steps.append(WizardStep(
                type="detect_axis",
                device="pedals",
                axis="brake",
                title="Brake Pedal",
                instruction="Keep throttle RELEASED.\n\nSlowly press and release BRAKE several times.",
            ))

        if self._wheel_session.is_open:
            self._steps.append(WizardStep(
                type="detect_report_len",
                device="wheel",
                title="Detecting Wheel",
                instruction="Keep wheel CENTERED and still.\n\nDetecting report length...",
            ))
            self._steps.append(WizardStep(
                type="detect_axis",
                device="wheel",
                axis="steering",
                title="Steering Wheel",
                instruction="Slowly turn wheel LEFT and RIGHT several times.\n\nFull rotation not required.",
            ))
            self._steps.append(WizardStep(
                type="set_center",
                device="wheel",
                title="Steering Center",
                instruction="Hold wheel perfectly CENTERED.\n\nClick Next when ready.",
            ))

    def _build_ui(self) -> None:
        """Construct the wizard dialog layout."""
        self.setWindowTitle("Input Setup Wizard")
        self.setModal(True)
        self.setMinimumWidth(450)
        self.setMinimumHeight(280)

        layout = QVBoxLayout(self)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setStyleSheet("font-size: 14px; padding: 10px;")
        layout.addWidget(self._label)

        # Live input visualization
        self._viz_frame = QFrame()
        self._viz_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self._viz_frame.setStyleSheet("QFrame { background: #1a1a2e; border-radius: 6px; }")
        viz_layout = QVBoxLayout(self._viz_frame)
        viz_layout.setContentsMargins(15, 10, 15, 10)

        self._value_label = QLabel("Input: --")
        self._value_label.setAlignment(Qt.AlignCenter)
        self._value_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #22c55e; padding: 5px;"
        )
        viz_layout.addWidget(self._value_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 255)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setMinimumHeight(20)
        self._set_progress_style("baseline")
        viz_layout.addWidget(self._progress)

        self._samples_label = QLabel("Samples: 0")
        self._samples_label.setAlignment(Qt.AlignCenter)
        self._samples_label.setStyleSheet("color: #888; font-size: 11px;")
        viz_layout.addWidget(self._samples_label)

        layout.addWidget(self._viz_frame)
        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._cancel)
        btn_layout.addWidget(cancel_btn)

        btn_layout.addStretch()

        self._next_btn = QPushButton("Next")
        self._next_btn.clicked.connect(self._advance)
        btn_layout.addWidget(self._next_btn)

        layout.addLayout(btn_layout)

        self.rejected.connect(self._cancel)

        # Start first step
        self._run_current_step()

    def _set_progress_style(self, phase: str) -> None:
        """Set progress bar style based on phase."""
        if phase == "active":
            color1, color2 = "#f97316", "#fb923c"
        elif phase == "steering":
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

    # -------------------------------------------------------------------------
    # Step execution
    # -------------------------------------------------------------------------

    def _run_current_step(self) -> None:
        """Execute the current wizard step."""
        if self._current_step >= len(self._steps):
            self._finish()
            return

        step = self._steps[self._current_step]
        step_num = self._current_step + 1
        total = len(self._steps)

        self.setWindowTitle(f"Input Setup Wizard - Step {step_num}/{total}: {step.title}")
        self._label.setText(step.instruction)

        # Reset visualization
        self._value_label.setText("Input: --")
        self._progress.setValue(0)
        self._samples_label.setText("Samples: 0")

        if step.type == "detect_report_len":
            self._viz_frame.setVisible(False)
            self._next_btn.setEnabled(False)
            self._next_btn.setText("Detecting...")
            self._on_status_update(f"Detecting {step.device} report length...")
            QTimer.singleShot(500, self._detect_report_length)

        elif step.type == "detect_axis":
            self._viz_frame.setVisible(True)
            self._next_btn.setEnabled(False)
            self._next_btn.setText("Detecting...")
            self._start_axis_detection()

        elif step.type == "set_center":
            self._viz_frame.setVisible(True)
            self._next_btn.setEnabled(True)
            self._next_btn.setText("Capture Center")
            self._set_progress_style("steering")
            self._preview_timer.start()

    def _detect_report_length(self) -> None:
        """Auto-detect report length for current step's device."""
        step = self._steps[self._current_step]
        session = self._pedals_session if step.device == "pedals" else self._wheel_session

        if not session.is_open:
            self._label.setText("Device not connected!")
            QTimer.singleShot(1000, self._advance)
            return

        max_len = 64
        samples = []
        for _ in range(20):
            report = session.read_latest_report(report_len=max_len, max_reads=5)
            if not report:
                report = session.read_report(report_len=max_len, timeout_ms=50)
            if report:
                samples.append(len(report))

        if samples:
            report_len = max(set(samples), key=samples.count)
            if step.device == "pedals":
                self._result.pedals_report_len = report_len
            else:
                self._result.wheel_report_len = report_len

            self._on_report_len_detected(step.device, report_len)
            self._label.setText(f"Report length detected: {report_len} bytes\n\nContinuing...")
        else:
            self._label.setText("Could not detect report length.\nUsing default.")

        QTimer.singleShot(1000, self._advance)

    def _start_axis_detection(self) -> None:
        """Start detecting axis offset for current step."""
        step = self._steps[self._current_step]
        self._calibration_phase = "baseline"
        self._baseline_samples = []
        self._active_samples = []
        self._set_progress_style("baseline")

        self._label.setText(
            f"📊 Phase 1 of 2: Baseline capture\n\n"
            f"Keep {step.axis.upper()} RELEASED.\n"
            f"Recording resting position..."
        )

        self._calibration_timer.start()
        QTimer.singleShot(CALIBRATION_DURATION_MS, self._switch_to_active_capture)

    def _switch_to_active_capture(self) -> None:
        """Switch from baseline to active capture."""
        step = self._steps[self._current_step]
        self._calibration_phase = "active"
        self._set_progress_style("active")

        self._label.setText(
            f"📊 Phase 2 of 2: Active capture\n\n"
            f"Press and release {step.axis.upper()} repeatedly.\n"
            f"Move it through its full range..."
        )

        QTimer.singleShot(CALIBRATION_DURATION_MS, self._finish_axis_detection)

    def _finish_axis_detection(self) -> None:
        """Complete axis detection and compute offset."""
        self._calibration_timer.stop()
        self._calibration_phase = None

        step = self._steps[self._current_step]

        if not self._baseline_samples or not self._active_samples:
            self._label.setText(f"⚠ {step.axis.capitalize()} detection failed\n\nContinuing...")
            QTimer.singleShot(1000, self._advance)
            return

        offset, score = self._compute_best_offset()

        # Store result
        if step.axis == "throttle":
            self._result.throttle_offset = offset
        elif step.axis == "brake":
            self._result.brake_offset = offset
        elif step.axis == "steering":
            self._result.steering_offset = offset

        self._on_axis_detected(step.device, step.axis, offset, score)
        self._viz_frame.setVisible(False)

        if score > 100:
            self._label.setText(f"✓ {step.axis.capitalize()} detected at byte {offset}\n\nContinuing...")
        else:
            self._label.setText(
                f"⚠ {step.axis.capitalize()} detected at byte {offset}\n"
                f"(low confidence - try again if needed)\n\nContinuing..."
            )

        QTimer.singleShot(1500, self._advance)

    def _capture_calibration_sample(self) -> None:
        """Capture a sample during calibration."""
        step = self._steps[self._current_step]
        session = self._pedals_session if step.device == "pedals" else self._wheel_session

        if not session.is_open:
            return

        report_len = (
            self._get_pedals_report_len()
            if step.device == "pedals"
            else self._get_wheel_report_len()
        )

        report = session.read_latest_report(report_len=report_len, max_reads=MAX_READS_PER_TICK)
        if report is None:
            report = session.read_report(report_len=report_len, timeout_ms=15)
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

    def _compute_best_offset(self) -> tuple[int, float]:
        """Compute best byte offset from samples."""
        if not self._baseline_samples or not self._active_samples:
            return (0, 0.0)

        min_len = min(len(b) for b in self._baseline_samples + self._active_samples)
        best_offset = 0
        best_score = 0.0

        for offset in range(min_len):
            baseline_vals = [b[offset] for b in self._baseline_samples]
            active_vals = [a[offset] for a in self._active_samples]

            baseline_var = self._variance(baseline_vals)
            active_var = self._variance(active_vals)

            score = active_var - baseline_var
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

    def _update_steering_preview(self) -> None:
        """Update live steering position display."""
        if not self._wheel_session.is_open:
            return

        report = self._wheel_session.read_latest_report(
            report_len=self._get_wheel_report_len(),
            max_reads=MAX_READS_PER_TICK,
        )
        if not report:
            return

        s_off = self._get_steering_offset()
        bits = self._get_steering_bits()

        # Read steering value
        if bits == 32:
            if s_off + 3 >= len(report):
                return
            raw = (report[s_off] | (report[s_off + 1] << 8) |
                   (report[s_off + 2] << 16) | (report[s_off + 3] << 24))
            value = raw if raw < 0x80000000 else raw - 0x100000000
            display_val = min(255, max(0, abs(value) % 256))
        elif bits == 16:
            if s_off + 1 >= len(report):
                return
            value = report[s_off] | (report[s_off + 1] << 8)
            display_val = value >> 8
        else:
            if s_off >= len(report):
                return
            value = int(report[s_off])
            display_val = value

        self._value_label.setText(f"Steering: {value}")
        self._progress.setValue(display_val)

    def _capture_steering_center(self) -> None:
        """Capture steering center position."""
        if not self._wheel_session.is_open:
            return

        report = self._wheel_session.read_latest_report(
            report_len=self._get_wheel_report_len(),
            max_reads=MAX_READS_PER_TICK,
        )
        if not report:
            return

        s_off = self._get_steering_offset()
        bits = self._get_steering_bits()

        if bits == 32:
            if s_off + 3 >= len(report):
                return
            raw = (report[s_off] | (report[s_off + 1] << 8) |
                   (report[s_off + 2] << 16) | (report[s_off + 3] << 24))
            center = raw if raw < 0x80000000 else raw - 0x100000000
        elif bits == 16:
            if s_off + 1 >= len(report):
                return
            center = report[s_off] | (report[s_off + 1] << 8)
        else:
            if s_off >= len(report):
                return
            center = int(report[s_off])

        self._result.steering_center = center
        self._on_steering_center_captured(center)

    def _advance(self) -> None:
        """Advance to the next wizard step."""
        self._preview_timer.stop()

        step = self._steps[self._current_step] if self._current_step < len(self._steps) else None

        # Handle set_center step
        if step and step.type == "set_center":
            self._capture_steering_center()

        self._current_step += 1
        self._run_current_step()

    def _finish(self) -> None:
        """Complete the wizard."""
        self._calibration_timer.stop()
        self._preview_timer.stop()
        self._on_complete(self._result)
        self._on_status_update("Input setup complete! Settings saved.")
        self.close()

    def _cancel(self) -> None:
        """Cancel the wizard."""
        self._calibration_timer.stop()
        self._preview_timer.stop()
        self._on_status_update("Setup wizard canceled.")
        self.close()

    def closeEvent(self, event) -> None:
        """Clean up on close."""
        self._calibration_timer.stop()
        self._preview_timer.stop()
        super().closeEvent(event)
