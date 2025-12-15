"""Tests for the calibration module.

This module tests calibration algorithms and state management for
detecting pedal/wheel byte offsets.
"""

from __future__ import annotations

import pytest

from mmt_app.input.calibration import (
    CalibrationState,
    CalibrationResult,
    SteeringCalibrationState,
    compute_best_offset,
    variance,
    compute_steering_center,
    detect_changing_byte,
    CALIBRATION_DURATION_MS,
    STEERING_CAPTURE_MS,
    MAX_READS_PER_TICK,
)


# ============================================================================
# Constants Tests
# ============================================================================


class TestConstants:
    """Tests for calibration constants."""

    def test_calibration_duration_positive(self) -> None:
        """Calibration duration should be positive."""
        assert CALIBRATION_DURATION_MS > 0

    def test_steering_capture_positive(self) -> None:
        """Steering capture duration should be positive."""
        assert STEERING_CAPTURE_MS > 0

    def test_max_reads_positive(self) -> None:
        """Max reads per tick should be positive."""
        assert MAX_READS_PER_TICK > 0


# ============================================================================
# Variance Tests
# ============================================================================


class TestVariance:
    """Tests for the variance function."""

    def test_variance_empty_list(self) -> None:
        """Empty list should return 0."""
        assert variance([]) == 0.0

    def test_variance_single_value(self) -> None:
        """Single value should return 0 (needs at least 2)."""
        assert variance([50]) == 0.0

    def test_variance_identical_values(self) -> None:
        """All identical values should have 0 variance."""
        assert variance([50, 50, 50, 50]) == 0.0

    def test_variance_two_values(self) -> None:
        """Two different values should have non-zero variance."""
        # Mean = 50, variance = ((0-50)^2 + (100-50)^2) / 2 = 2500
        assert variance([0, 100]) == pytest.approx(2500.0)

    def test_variance_simple_set(self) -> None:
        """Simple set of values should compute correct variance."""
        # Values: [2, 4, 6], Mean = 4
        # Variance = ((2-4)^2 + (4-4)^2 + (6-4)^2) / 3 = (4 + 0 + 4) / 3 = 8/3
        assert variance([2, 4, 6]) == pytest.approx(8 / 3)

    def test_variance_known_set(self) -> None:
        """Known variance calculation."""
        # Values: [10, 20, 30, 40, 50], Mean = 30
        # Variance = (400 + 100 + 0 + 100 + 400) / 5 = 200
        assert variance([10, 20, 30, 40, 50]) == pytest.approx(200.0)

    def test_variance_returns_float(self) -> None:
        """Variance should return float even for integer inputs."""
        result = variance([1, 2, 3])
        assert isinstance(result, float)


# ============================================================================
# Compute Best Offset Tests
# ============================================================================


class TestComputeBestOffset:
    """Tests for the compute_best_offset function."""

    def test_empty_baseline_returns_zero(self) -> None:
        """Empty baseline should return offset 0 with score 0."""
        offset, score = compute_best_offset([], [b'\x00\x50'])
        assert offset == 0
        assert score == 0.0

    def test_empty_active_returns_zero(self) -> None:
        """Empty active samples should return offset 0 with score 0."""
        offset, score = compute_best_offset([b'\x00\x50'], [])
        assert offset == 0
        assert score == 0.0

    def test_both_empty_returns_zero(self) -> None:
        """Both empty should return offset 0 with score 0."""
        offset, score = compute_best_offset([], [])
        assert offset == 0
        assert score == 0.0

    def test_detects_changing_byte(self) -> None:
        """Should detect the byte that changes between baseline and active."""
        # Baseline: byte 0 varies, byte 1 is constant at 0
        # Active: byte 0 varies, byte 1 varies a lot
        baseline = [
            b'\x80\x00',
            b'\x81\x00',
            b'\x82\x00',
        ]
        active = [
            b'\x80\x50',
            b'\x81\x60',
            b'\x82\x70',
        ]
        offset, score = compute_best_offset(baseline, active)
        # Byte 1 has more variance in active (varies 0x50-0x70) vs baseline (constant 0)
        assert offset == 1
        assert score > 0

    def test_throttle_detection_scenario(self) -> None:
        """Simulate throttle detection: pedal released vs pressed."""
        # Released: throttle byte stays at 0
        baseline = [b'\x00\x00\x00'] * 5
        # Pressed: throttle byte at offset 1 goes to high values
        active = [
            b'\x00\x80\x00',
            b'\x00\x90\x00',
            b'\x00\xa0\x00',
            b'\x00\xb0\x00',
            b'\x00\xc0\x00',
        ]
        offset, score = compute_best_offset(baseline, active)
        assert offset == 1  # Throttle is at byte 1
        assert score > 0

    def test_brake_detection_scenario(self) -> None:
        """Simulate brake detection: pedal released vs pressed."""
        # Released: brake byte stays at 0
        baseline = [b'\x00\x00\x00'] * 5
        # Pressed: brake byte at offset 2 goes to high values
        active = [
            b'\x00\x00\x50',
            b'\x00\x00\x60',
            b'\x00\x00\x70',
            b'\x00\x00\x80',
            b'\x00\x00\x90',
        ]
        offset, score = compute_best_offset(baseline, active)
        assert offset == 2  # Brake is at byte 2
        assert score > 0

    def test_handles_different_length_samples(self) -> None:
        """Should handle samples of different lengths."""
        # Need multiple samples for variance calculation
        baseline = [b'\x00\x00\x00\x00', b'\x00\x00\x00\x00', b'\x00\x00\x00\x00']
        active = [b'\x00\xff\x00', b'\x00\xfe\x00', b'\x00\xfd\x00']  # Shorter, byte 1 varies
        offset, score = compute_best_offset(baseline, active)
        # Should use minimum length (3 bytes) and detect byte 1
        assert offset == 1
        assert score > 0

    def test_score_reflects_variance_difference(self) -> None:
        """Higher variance difference should give higher score."""
        baseline = [b'\x00\x00'] * 5
        
        # Low variance in active
        active_low = [b'\x00\x10', b'\x00\x11', b'\x00\x12']
        _, score_low = compute_best_offset(baseline, active_low)
        
        # High variance in active
        active_high = [b'\x00\x00', b'\x00\x80', b'\x00\xff']
        _, score_high = compute_best_offset(baseline, active_high)
        
        assert score_high > score_low


# ============================================================================
# Compute Steering Center Tests
# ============================================================================


class TestComputeSteeringCenter:
    """Tests for the compute_steering_center function."""

    def test_empty_samples_returns_default(self) -> None:
        """Empty samples should return default center (128)."""
        assert compute_steering_center([]) == 128

    def test_single_sample(self) -> None:
        """Single sample should return that value."""
        assert compute_steering_center([100]) == 100

    def test_average_of_samples(self) -> None:
        """Should return integer average of samples."""
        # Average of [100, 110, 120] = 110
        assert compute_steering_center([100, 110, 120]) == 110

    def test_rounds_to_integer(self) -> None:
        """Should return integer result."""
        # Average of [100, 101] = 100.5 -> 100
        result = compute_steering_center([100, 101])
        assert isinstance(result, int)
        assert result == 100

    def test_centered_wheel(self) -> None:
        """Typical centered wheel scenario."""
        # Slight noise around center
        samples = [127, 128, 128, 129, 128, 127, 128]
        center = compute_steering_center(samples)
        assert 127 <= center <= 129


# ============================================================================
# Detect Changing Byte Tests (Legacy)
# ============================================================================


class TestDetectChangingByte:
    """Tests for the detect_changing_byte legacy function."""

    def test_empty_baseline_returns_none(self) -> None:
        """Empty baseline should return None."""
        result = detect_changing_byte([], [[0, 50]])
        assert result is None

    def test_empty_active_returns_none(self) -> None:
        """Empty active should return None."""
        result = detect_changing_byte([[0, 50]], [])
        assert result is None

    def test_detects_changing_index(self) -> None:
        """Should detect the index that changes most."""
        baseline = [[0, 0, 0]] * 5
        active = [[0, 100, 0], [0, 110, 0], [0, 120, 0]]
        result = detect_changing_byte(baseline, active)
        assert result is not None
        assert result.offset == 1

    def test_returns_calibration_result(self) -> None:
        """Should return CalibrationResult dataclass."""
        baseline = [[0, 0]] * 5
        active = [[0, 100]] * 5
        result = detect_changing_byte(baseline, active)
        assert result is not None
        assert isinstance(result, CalibrationResult)
        assert hasattr(result, 'offset')
        assert hasattr(result, 'score')

    def test_below_min_score_returns_none(self) -> None:
        """Score below minimum should return None."""
        # Minimal change
        baseline = [[50, 50]]
        active = [[51, 51]]
        result = detect_changing_byte(baseline, active, min_score=100.0)
        assert result is None


# ============================================================================
# CalibrationState Tests
# ============================================================================


class TestCalibrationState:
    """Tests for the CalibrationState dataclass."""

    def test_default_state(self) -> None:
        """Default state should have None values and empty lists."""
        state = CalibrationState()
        assert state.device is None
        assert state.axis is None
        assert state.callback is None
        assert state.baseline_samples == []
        assert state.active_samples == []

    def test_is_active_when_device_set(self) -> None:
        """Should be active when device is set."""
        state = CalibrationState(device="pedals")
        assert state.is_active is True

    def test_is_active_when_axis_set(self) -> None:
        """Should be active when axis is set."""
        state = CalibrationState(axis="throttle")
        assert state.is_active is True

    def test_not_active_when_empty(self) -> None:
        """Should not be active when both device and axis are None."""
        state = CalibrationState()
        assert state.is_active is False

    def test_reset_clears_state(self) -> None:
        """Reset should clear all state."""
        state = CalibrationState(
            device="pedals",
            axis="throttle",
            baseline_samples=[b'\x00'],
            active_samples=[b'\xff'],
        )
        state.reset()
        assert state.device is None
        assert state.axis is None
        assert state.baseline_samples == []
        assert state.active_samples == []
        assert state.is_active is False


# ============================================================================
# SteeringCalibrationState Tests
# ============================================================================


class TestSteeringCalibrationState:
    """Tests for the SteeringCalibrationState dataclass."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        state = SteeringCalibrationState()
        assert state.center == 128
        assert state.range_degrees == 900
        assert state.center_samples == []
        assert state.left_samples == []
        assert state.right_samples == []
        assert state.pending_stage is None
        assert state.current_stage is None

    def test_custom_values(self) -> None:
        """Should accept custom values."""
        state = SteeringCalibrationState(center=120, range_degrees=540)
        assert state.center == 120
        assert state.range_degrees == 540

    def test_reset_clears_samples(self) -> None:
        """Reset should clear sample lists and stages."""
        state = SteeringCalibrationState()
        state.center_samples = [100, 110, 120]
        state.left_samples = [50, 60]
        state.right_samples = [200, 210]
        state.pending_stage = "left"
        state.current_stage = "center"
        
        state.reset()
        
        assert state.center_samples == []
        assert state.left_samples == []
        assert state.right_samples == []
        assert state.pending_stage is None
        assert state.current_stage is None

    def test_reset_preserves_center_and_range(self) -> None:
        """Reset should NOT clear center and range values."""
        state = SteeringCalibrationState(center=100, range_degrees=720)
        state.center_samples = [100, 110]
        state.reset()
        # center and range_degrees should be preserved
        assert state.center == 100
        assert state.range_degrees == 720
