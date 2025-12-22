"""Axis calibration for detecting byte offsets in HID reports.

Provides utilities for auto-detecting throttle, brake, and steering offsets
by comparing baseline vs active samples.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QTimer

from mmt_app.input.hid_backend import HidSession
from mmt_app.input.calibration import (
    CALIBRATION_DURATION_MS,
    MAX_READS_PER_TICK,
)


@dataclass
class CalibrationResult:
    """Result of axis calibration."""

    axis: str
    offset: int
    score: float


@dataclass
class CalibrationSession:
    """State for an active calibration session."""

    device: str  # 'pedals' or 'wheel'
    axis: str    # 'throttle', 'brake', 'steering'
    phase: str = "baseline"  # 'baseline' or 'active'
    baseline_samples: list[bytes] = field(default_factory=list)
    active_samples: list[bytes] = field(default_factory=list)
    callback: Callable[[CalibrationResult], None] | None = None


class AxisCalibrator:
    """Handles axis offset calibration for HID devices.

    Uses a two-phase approach:
    1. Baseline: Capture samples with axis at rest
    2. Active: Capture samples with axis being used

    The byte offset with the largest variance difference between
    phases is selected as the axis offset.
    """

    def __init__(
        self,
        *,
        pedals_session: HidSession,
        wheel_session: HidSession,
        get_pedals_report_len: Callable[[], int],
        get_wheel_report_len: Callable[[], int],
        on_status_update: Callable[[str], None] | None = None,
        on_phase_changed: Callable[[str, str], None] | None = None,
        on_sample_captured: Callable[[bytes, int], None] | None = None,
    ) -> None:
        """Initialize the axis calibrator.

        Args:
            pedals_session: HID session for pedals device.
            wheel_session: HID session for wheel device.
            get_pedals_report_len: Callback to get current pedals report length.
            get_wheel_report_len: Callback to get current wheel report length.
            on_status_update: Callback for status messages.
            on_phase_changed: Callback when calibration phase changes (phase, axis).
            on_sample_captured: Callback when sample captured (report, sample_count).
        """
        self._pedals_session = pedals_session
        self._wheel_session = wheel_session
        self._get_pedals_report_len = get_pedals_report_len
        self._get_wheel_report_len = get_wheel_report_len
        self._on_status_update = on_status_update or (lambda _: None)
        self._on_phase_changed = on_phase_changed or (lambda _, __: None)
        self._on_sample_captured = on_sample_captured or (lambda _, __: None)

        self._session: CalibrationSession | None = None

        self._timer = QTimer()
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._capture_sample)

    @property
    def is_active(self) -> bool:
        """Return True if calibration is currently running."""
        return self._session is not None

    def start(
        self,
        device: str,
        axis: str,
        *,
        on_complete: Callable[[CalibrationResult], None] | None = None,
    ) -> bool:
        """Start calibration for a given axis.

        Args:
            device: Either 'pedals' or 'wheel'.
            axis: The axis name (e.g., 'throttle', 'brake', 'steering').
            on_complete: Callback invoked with result when done.

        Returns:
            True if calibration started, False if device not connected.
        """
        session = self._pedals_session if device == "pedals" else self._wheel_session
        if not session.is_open:
            self._on_status_update(f"Cannot calibrate {axis}: {device} device not connected.")
            return False

        if self._session:
            self._on_status_update("Calibration already running. Please wait.")
            return False

        self._session = CalibrationSession(
            device=device,
            axis=axis,
            callback=on_complete,
        )

        self._on_status_update(f"Phase 1/2: Keep {axis.upper()} released...")
        self._on_phase_changed("baseline", axis)

        self._timer.start()
        QTimer.singleShot(CALIBRATION_DURATION_MS, self._switch_to_active)

        return True

    def cancel(self) -> None:
        """Cancel any active calibration."""
        self._timer.stop()
        self._session = None

    def _switch_to_active(self) -> None:
        """Transition from baseline to active capture."""
        if not self._session:
            return

        self._session.phase = "active"
        axis = self._session.axis

        self._on_status_update(f"Phase 2/2: Press/move {axis.upper()} now!")
        self._on_phase_changed("active", axis)

        QTimer.singleShot(CALIBRATION_DURATION_MS, self._finish)

    def _finish(self) -> None:
        """Complete calibration and compute best offset."""
        self._timer.stop()

        session = self._session
        if not session:
            return

        self._session = None

        if not session.baseline_samples or not session.active_samples:
            self._on_status_update(f"{session.axis} calibration failed: not enough samples.")
            return

        offset, score = compute_best_offset(
            session.baseline_samples, session.active_samples
        )

        result = CalibrationResult(
            axis=session.axis,
            offset=offset,
            score=score,
        )

        self._on_status_update(
            f"{session.axis.capitalize()} offset detected at byte {offset} (score: {score:.1f})."
        )

        if session.callback:
            session.callback(result)

    def _capture_sample(self) -> None:
        """Capture a single calibration sample."""
        if not self._session:
            return

        session = self._session
        hid_session = (
            self._pedals_session if session.device == "pedals" else self._wheel_session
        )

        if not hid_session.is_open:
            return

        report_len = (
            self._get_pedals_report_len()
            if session.device == "pedals"
            else self._get_wheel_report_len()
        )

        # Try non-blocking first, fall back to blocking
        report = hid_session.read_latest_report(
            report_len=report_len, max_reads=MAX_READS_PER_TICK
        )
        if report is None:
            report = hid_session.read_report(report_len=report_len, timeout_ms=15)
        if report is None:
            return

        # Append to correct sample list
        if session.phase == "active":
            session.active_samples.append(report)
            sample_count = len(session.active_samples)
        else:
            session.baseline_samples.append(report)
            sample_count = len(session.baseline_samples)

        self._on_sample_captured(report, sample_count)


def compute_best_offset(
    baseline: list[bytes], active: list[bytes]
) -> tuple[int, float]:
    """Find the byte offset with the largest variance difference.

    Args:
        baseline: Samples captured at rest.
        active: Samples captured during use.

    Returns:
        Tuple of (best_offset, score).
    """
    if not baseline or not active:
        return (0, 0.0)

    min_len = min(len(b) for b in baseline + active)
    best_offset = 0
    best_score = 0.0

    for offset in range(min_len):
        baseline_vals = [b[offset] for b in baseline]
        active_vals = [a[offset] for a in active]

        baseline_var = variance(baseline_vals)
        active_var = variance(active_vals)

        score = active_var - baseline_var
        if score > best_score:
            best_score = score
            best_offset = offset

    return (best_offset, best_score)


def variance(values: list[int]) -> float:
    """Compute the variance of a list of integers."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)
