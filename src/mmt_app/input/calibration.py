"""Calibration logic for HID input devices.

This module provides calibration algorithms and state management for
detecting pedal/wheel byte offsets and steering center positions,
separated from UI concerns.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mmt_app.input.hid_backend import HidSession


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CALIBRATION_DURATION_MS: int = 5000
"""Duration (ms) for each calibration sample capture phase."""

STEERING_CAPTURE_MS: int = 5000
"""Duration (ms) for each steering calibration stage."""

MAX_READS_PER_TICK: int = 50
"""Maximum HID reads per tick to drain the buffer."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CalibrationResult:
    """Result of detecting which report byte corresponds to a control."""

    offset: int
    score: float


@dataclass
class CalibrationState:
    """Mutable state for an ongoing calibration."""
    device: str | None = None
    axis: str | None = None
    callback: Callable[[str, int, float], None] | None = None
    baseline_samples: list[bytes] = field(default_factory=list)
    active_samples: list[bytes] = field(default_factory=list)
    
    def reset(self) -> None:
        """Reset calibration state."""
        self.device = None
        self.axis = None
        self.callback = None
        self.baseline_samples = []
        self.active_samples = []

    @property
    def is_active(self) -> bool:
        """Check if calibration is currently running."""
        return self.device is not None or self.axis is not None


@dataclass
class SteeringCalibrationState:
    """Mutable state for steering calibration."""
    center: int = 128
    range_degrees: int = 900
    center_samples: list[int] = field(default_factory=list)
    left_samples: list[int] = field(default_factory=list)
    right_samples: list[int] = field(default_factory=list)
    pending_stage: str | None = None
    current_stage: str | None = None
    
    def reset(self) -> None:
        """Reset steering calibration state."""
        self.center_samples = []
        self.left_samples = []
        self.right_samples = []
        self.pending_stage = None
        self.current_stage = None


# ---------------------------------------------------------------------------
# Calibration algorithms
# ---------------------------------------------------------------------------

def compute_best_offset(baseline: list[bytes], active: list[bytes]) -> tuple[int, float]:
    """Find the byte offset with the largest variance difference.

    Compares variance in baseline (released) vs active (pressed) samples
    to detect which byte position corresponds to the input axis.

    Args:
        baseline: Sample data when input is released.
        active: Sample data when input is pressed/moved.

    Returns:
        A tuple of (best_offset, score) where score indicates confidence.
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

        # Score is how much more variance exists in active vs baseline
        score = active_var - baseline_var
        if score > best_score:
            best_score = score
            best_offset = offset

    return (best_offset, best_score)


def variance(values: list[int]) -> float:
    """Compute the variance of a list of integers.

    Args:
        values: List of integer values.

    Returns:
        The statistical variance, or 0.0 if fewer than 2 values.
    """
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)


def compute_steering_center(samples: list[int]) -> int:
    """Compute steering center from samples.

    Args:
        samples: List of steering position samples.

    Returns:
        The average steering center position.
    """
    if not samples:
        return 128  # Default center
    return int(sum(samples) / len(samples))


def detect_report_length(
    session: "HidSession",
    max_report_len: int = 64,
    sample_count: int = 10,
    max_reads: int = 5,
) -> int | None:
    """Auto-detect the report length for a device.

    Args:
        session: An open HID session.
        max_report_len: Maximum report length to try.
        sample_count: Number of samples to collect.
        max_reads: Max reads per sample attempt.

    Returns:
        The most common report length found, or None if detection failed.
    """
    if not session.is_open:
        return None

    samples = []
    for _ in range(sample_count):
        report = session.read_latest_report(report_len=max_report_len, max_reads=max_reads)
        if report:
            samples.append(len(report))

    if not samples:
        return None

    # Return the most common report length
    return max(set(samples), key=samples.count)


def read_steering_value(
    session: "HidSession",
    report_len: int,
    steering_offset: int,
    max_reads: int = MAX_READS_PER_TICK,
) -> int | None:
    """Read the current steering value from the wheel.

    Args:
        session: An open HID session for the wheel.
        report_len: Expected report length.
        steering_offset: Byte offset for steering data.
        max_reads: Maximum reads to drain buffer.

    Returns:
        The steering value (0-255), or None if read failed.
    """
    if not session.is_open:
        return None

    report = session.read_latest_report(report_len=report_len, max_reads=max_reads)
    if not report:
        return None

    if steering_offset >= len(report):
        return None

    return int(report[steering_offset])


# Legacy function for backwards compatibility
def detect_changing_byte(
    baseline: list[list[int]],
    active: list[list[int]],
    *,
    min_score: float = 8.0,
) -> Optional[CalibrationResult]:
    """Find the report byte index with the strongest change from baseline -> active.

    This is a heuristic for 'press to bind' style calibration.
    """
    if not baseline or not active:
        return None

    min_len = min(min(len(x) for x in baseline), min(len(x) for x in active))
    if min_len <= 0:
        return None

    def mean_at(samples: list[list[int]], idx: int) -> float:
        return sum(s[idx] for s in samples) / float(len(samples))

    best_idx: Optional[int] = None
    best_score = 0.0
    for idx in range(min_len):
        baseline_mean = mean_at(baseline, idx)
        active_vals = [s[idx] for s in active]
        active_mean = sum(active_vals) / float(len(active_vals))
        active_range = float(max(active_vals) - min(active_vals))
        score = abs(active_mean - baseline_mean) + active_range
        if score > best_score:
            best_score = score
            best_idx = idx

    if best_idx is None or best_score < min_score:
        return None
    return CalibrationResult(offset=best_idx, score=best_score)

