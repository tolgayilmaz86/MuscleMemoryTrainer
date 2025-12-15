"""Tests for the telemetry module.

This module tests the TelemetrySample dataclass.
"""

from __future__ import annotations

import pytest

from mmt_app.telemetry import TelemetrySample


# ============================================================================
# TelemetrySample Tests
# ============================================================================


class TestTelemetrySample:
    """Tests for the TelemetrySample dataclass."""

    def test_creation(self) -> None:
        """Should create sample with all fields."""
        sample = TelemetrySample(throttle=50.0, brake=30.0, steering=10.0)
        assert sample.throttle == 50.0
        assert sample.brake == 30.0
        assert sample.steering == 10.0

    def test_zero_values(self) -> None:
        """Should accept zero values."""
        sample = TelemetrySample(throttle=0.0, brake=0.0, steering=0.0)
        assert sample.throttle == 0.0
        assert sample.brake == 0.0
        assert sample.steering == 0.0

    def test_max_values(self) -> None:
        """Should accept max percentage values."""
        sample = TelemetrySample(throttle=100.0, brake=100.0, steering=100.0)
        assert sample.throttle == 100.0
        assert sample.brake == 100.0
        assert sample.steering == 100.0

    def test_negative_steering(self) -> None:
        """Steering can be negative (left turn)."""
        sample = TelemetrySample(throttle=50.0, brake=0.0, steering=-100.0)
        assert sample.steering == -100.0

    def test_is_immutable(self) -> None:
        """TelemetrySample should be frozen (immutable)."""
        sample = TelemetrySample(throttle=50.0, brake=30.0, steering=0.0)
        with pytest.raises(AttributeError):
            sample.throttle = 60.0  # type: ignore

    def test_equality(self) -> None:
        """Two samples with same values should be equal."""
        s1 = TelemetrySample(throttle=50.0, brake=30.0, steering=10.0)
        s2 = TelemetrySample(throttle=50.0, brake=30.0, steering=10.0)
        assert s1 == s2

    def test_inequality(self) -> None:
        """Two samples with different values should not be equal."""
        s1 = TelemetrySample(throttle=50.0, brake=30.0, steering=10.0)
        s2 = TelemetrySample(throttle=60.0, brake=30.0, steering=10.0)
        assert s1 != s2

    def test_has_slots(self) -> None:
        """TelemetrySample should use slots for memory efficiency."""
        sample = TelemetrySample(throttle=50.0, brake=30.0, steering=0.0)
        assert hasattr(sample, '__slots__') or not hasattr(sample, '__dict__')

    def test_hashable(self) -> None:
        """Frozen dataclass should be hashable."""
        sample = TelemetrySample(throttle=50.0, brake=30.0, steering=0.0)
        # Should not raise
        hash(sample)

    def test_can_use_in_set(self) -> None:
        """Should be usable in sets (requires hashable)."""
        s1 = TelemetrySample(throttle=50.0, brake=30.0, steering=0.0)
        s2 = TelemetrySample(throttle=50.0, brake=30.0, steering=0.0)
        s3 = TelemetrySample(throttle=60.0, brake=30.0, steering=0.0)
        
        sample_set = {s1, s2, s3}
        assert len(sample_set) == 2  # s1 and s2 are equal

    def test_typical_driving_scenario(self) -> None:
        """Typical scenario: partial throttle, no brake, slight left turn."""
        sample = TelemetrySample(throttle=75.0, brake=0.0, steering=-15.0)
        assert 0 <= sample.throttle <= 100
        assert sample.brake == 0.0
        assert -100 <= sample.steering <= 100

    def test_braking_scenario(self) -> None:
        """Braking scenario: no throttle, heavy brake, centered."""
        sample = TelemetrySample(throttle=0.0, brake=85.0, steering=0.0)
        assert sample.throttle == 0.0
        assert 0 <= sample.brake <= 100
        assert sample.steering == 0.0

    def test_trail_braking_scenario(self) -> None:
        """Trail braking: throttle coming on, brake releasing."""
        sample = TelemetrySample(throttle=30.0, brake=40.0, steering=-25.0)
        assert sample.throttle == 30.0
        assert sample.brake == 40.0
        assert sample.steering == -25.0
