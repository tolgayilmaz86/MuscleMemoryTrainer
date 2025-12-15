"""Tests for the static_brake module.

This module tests brake trace generation, validation, and preset creation.
"""

from __future__ import annotations

import pytest

from mmt_app.static_brake import (
    BrakeTrace,
    random_trace,
    presets,
    _ease,
    _smooth,
    _jitter,
    _clamp_points,
    _anchors_for_length,
    _interpolate_anchors,
)


# ============================================================================
# BrakeTrace Dataclass Tests
# ============================================================================


class TestBrakeTrace:
    """Tests for the BrakeTrace dataclass."""

    def test_valid_trace_creation(self) -> None:
        """BrakeTrace should accept valid points in range 0-100."""
        trace = BrakeTrace("Test", [0, 50, 100, 50, 0])
        assert trace.name == "Test"
        assert trace.points == [0, 50, 100, 50, 0]

    def test_trace_with_single_point(self) -> None:
        """BrakeTrace should accept a single valid point."""
        trace = BrakeTrace("Single", [50])
        assert len(trace.points) == 1
        assert trace.points[0] == 50

    def test_trace_with_boundary_values(self) -> None:
        """BrakeTrace should accept boundary values 0 and 100."""
        trace = BrakeTrace("Boundaries", [0, 100, 0, 100])
        assert trace.points == [0, 100, 0, 100]

    def test_empty_points_raises_error(self) -> None:
        """BrakeTrace should reject empty points list."""
        with pytest.raises(ValueError, match="must not be empty"):
            BrakeTrace("Empty", [])

    def test_negative_value_raises_error(self) -> None:
        """BrakeTrace should reject negative values."""
        with pytest.raises(ValueError, match="must be within"):
            BrakeTrace("Negative", [0, -1, 50])

    def test_value_over_100_raises_error(self) -> None:
        """BrakeTrace should reject values over 100."""
        with pytest.raises(ValueError, match="must be within"):
            BrakeTrace("Over", [0, 101, 50])

    def test_trace_is_immutable(self) -> None:
        """BrakeTrace should be frozen (immutable)."""
        trace = BrakeTrace("Immutable", [0, 50, 100])
        with pytest.raises(AttributeError):
            trace.name = "Changed"  # type: ignore


# ============================================================================
# Easing Function Tests
# ============================================================================


class TestEaseFunction:
    """Tests for the _ease smoothstep function."""

    def test_ease_at_zero(self) -> None:
        """Easing at t=0 should return 0."""
        assert _ease(0.0) == pytest.approx(0.0)

    def test_ease_at_one(self) -> None:
        """Easing at t=1 should return 1."""
        assert _ease(1.0) == pytest.approx(1.0)

    def test_ease_at_midpoint(self) -> None:
        """Easing at t=0.5 should return 0.5 (inflection point)."""
        assert _ease(0.5) == pytest.approx(0.5)

    def test_ease_is_monotonic(self) -> None:
        """Easing should be monotonically increasing."""
        prev = 0.0
        for i in range(101):
            t = i / 100.0
            current = _ease(t)
            assert current >= prev, f"Ease not monotonic at t={t}"
            prev = current

    def test_ease_clamps_negative_input(self) -> None:
        """Easing should clamp negative inputs to 0."""
        assert _ease(-0.5) == pytest.approx(0.0)

    def test_ease_clamps_input_over_one(self) -> None:
        """Easing should clamp inputs > 1 to 1."""
        assert _ease(1.5) == pytest.approx(1.0)

    def test_ease_symmetry(self) -> None:
        """Ease should be symmetric around the midpoint: ease(t) + ease(1-t) = 1."""
        for i in range(50):
            t = i / 100.0
            assert _ease(t) + _ease(1.0 - t) == pytest.approx(1.0)


# ============================================================================
# Smoothing Function Tests
# ============================================================================


class TestSmoothFunction:
    """Tests for the _smooth weighted average function."""

    def test_smooth_preserves_length(self) -> None:
        """Smoothing should not change the number of values."""
        values = [0.0, 50.0, 100.0, 50.0, 0.0]
        smoothed = _smooth(values)
        assert len(smoothed) == len(values)

    def test_smooth_reduces_spikes(self) -> None:
        """Smoothing should reduce spike magnitudes."""
        # Spike in the middle
        values = [0.0, 0.0, 100.0, 0.0, 0.0]
        smoothed = _smooth(values, passes=1)
        # The spike should be reduced (original neighbors were 0)
        assert smoothed[2] < 100.0

    def test_smooth_with_zero_passes(self) -> None:
        """Smoothing with 0 passes should return original values."""
        values = [10.0, 20.0, 30.0]
        smoothed = _smooth(values, passes=0)
        assert smoothed == values

    def test_smooth_constant_values_unchanged(self) -> None:
        """Smoothing constant values should return approximately same values."""
        values = [50.0, 50.0, 50.0, 50.0, 50.0]
        smoothed = _smooth(values)
        for v in smoothed:
            assert v == pytest.approx(50.0)

    def test_smooth_empty_list(self) -> None:
        """Smoothing empty list should return empty list."""
        assert _smooth([]) == []

    def test_smooth_single_value(self) -> None:
        """Smoothing single value should return that value."""
        smoothed = _smooth([42.0])
        assert len(smoothed) == 1
        assert smoothed[0] == pytest.approx(42.0)


# ============================================================================
# Jitter Function Tests
# ============================================================================


class TestJitterFunction:
    """Tests for the _jitter noise addition function."""

    def test_jitter_preserves_length(self) -> None:
        """Jitter should not change the number of values."""
        values = [0.0, 50.0, 100.0]
        jittered = _jitter(values)
        assert len(jittered) == len(values)

    def test_jitter_stays_within_bounds(self) -> None:
        """Jittered values should stay within 0-100."""
        # Test edge cases that could go out of bounds
        values = [0.0, 1.0, 99.0, 100.0]
        for _ in range(100):  # Run multiple times due to randomness
            jittered = _jitter(values, spread=5.0)
            for v in jittered:
                assert 0.0 <= v <= 100.0

    def test_jitter_with_zero_spread(self) -> None:
        """Jitter with spread=0 should return original values."""
        values = [25.0, 50.0, 75.0]
        jittered = _jitter(values, spread=0.0)
        for orig, jit in zip(values, jittered):
            assert jit == pytest.approx(orig)

    def test_jitter_modifies_values(self) -> None:
        """Jitter with non-zero spread should modify at least some values."""
        values = [50.0] * 100
        jittered = _jitter(values, spread=5.0)
        # With 100 values, at least some should differ
        differences = sum(1 for o, j in zip(values, jittered) if o != j)
        assert differences > 0


# ============================================================================
# Clamping Function Tests
# ============================================================================


class TestClampPoints:
    """Tests for the _clamp_points function."""

    def test_clamp_converts_to_integers(self) -> None:
        """Clamping should convert floats to integers."""
        values = [0.0, 49.5, 50.5, 100.0]
        clamped = _clamp_points(values)
        assert all(isinstance(v, int) for v in clamped)
        assert clamped == [0, 50, 50, 100]  # First is forced to 0

    def test_clamp_forces_first_to_zero(self) -> None:
        """Clamping should always set the first value to 0."""
        values = [75.0, 50.0, 25.0]
        clamped = _clamp_points(values)
        assert clamped[0] == 0

    def test_clamp_force_end_zero(self) -> None:
        """Clamping with force_end_zero should set last value to 0."""
        values = [50.0, 75.0, 100.0]
        clamped = _clamp_points(values, force_end_zero=True)
        assert clamped[-1] == 0

    def test_clamp_without_force_end_zero(self) -> None:
        """Clamping without force_end_zero should preserve last value."""
        values = [50.0, 75.0, 100.0]
        clamped = _clamp_points(values, force_end_zero=False)
        assert clamped[-1] == 100

    def test_clamp_empty_returns_single_zero(self) -> None:
        """Clamping empty list should return [0]."""
        assert _clamp_points([]) == [0]

    def test_clamp_bounds_values(self) -> None:
        """Clamping should bound values to 0-100."""
        values = [-50.0, 150.0, 50.0]
        clamped = _clamp_points(values)
        # First is forced to 0, second is clamped to 100, third stays 50
        assert clamped == [0, 100, 50]


# ============================================================================
# Anchor Generation Tests
# ============================================================================


class TestAnchorsForLength:
    """Tests for the _anchors_for_length function."""

    def test_anchors_start_at_zero(self) -> None:
        """Anchors should always start at position 0 with value 0."""
        anchors = _anchors_for_length(100)
        assert anchors[0] == (0, 0.0)

    def test_anchors_end_at_length_minus_one(self) -> None:
        """Anchors should always end at position length-1 with value 0."""
        length = 100
        anchors = _anchors_for_length(length)
        assert anchors[-1][0] == length - 1
        assert anchors[-1][1] == 0.0

    def test_anchors_sorted_by_position(self) -> None:
        """Anchors should be sorted by position."""
        for _ in range(10):  # Test multiple times due to randomness
            anchors = _anchors_for_length(100)
            positions = [a[0] for a in anchors]
            assert positions == sorted(positions)

    def test_anchors_have_valid_heights(self) -> None:
        """All anchor heights should be in range 0-100."""
        for _ in range(10):
            anchors = _anchors_for_length(100)
            for _, height in anchors:
                assert 0.0 <= height <= 100.0

    def test_anchors_minimum_count(self) -> None:
        """Should have at least 2 anchors (start and end)."""
        anchors = _anchors_for_length(20)
        assert len(anchors) >= 2

    def test_anchors_no_duplicate_positions(self) -> None:
        """Anchors should have unique positions after deduplication."""
        for _ in range(10):
            anchors = _anchors_for_length(100)
            positions = [a[0] for a in anchors]
            assert len(positions) == len(set(positions))


# ============================================================================
# Interpolation Tests
# ============================================================================


class TestInterpolateAnchors:
    """Tests for the _interpolate_anchors function."""

    def test_interpolate_produces_correct_length(self) -> None:
        """Interpolation should produce exactly 'length' values."""
        anchors = [(0, 0.0), (50, 100.0), (100, 0.0)]
        values = _interpolate_anchors(anchors, 101)
        assert len(values) == 101

    def test_interpolate_hits_anchor_points(self) -> None:
        """Interpolation should pass through anchor points."""
        anchors = [(0, 0.0), (50, 100.0), (100, 0.0)]
        values = _interpolate_anchors(anchors, 101)
        assert values[0] == pytest.approx(0.0)
        assert values[50] == pytest.approx(100.0)
        assert values[100] == pytest.approx(0.0)

    def test_interpolate_monotonic_between_anchors(self) -> None:
        """Values should be monotonic between anchors (due to easing)."""
        anchors = [(0, 0.0), (100, 100.0)]
        values = _interpolate_anchors(anchors, 101)
        # Should be monotonically increasing
        for i in range(100):
            assert values[i] <= values[i + 1]

    def test_interpolate_single_segment(self) -> None:
        """Interpolation with just start/end anchors should work."""
        anchors = [(0, 0.0), (99, 50.0)]
        values = _interpolate_anchors(anchors, 100)
        assert len(values) == 100
        assert values[0] == pytest.approx(0.0)
        assert values[99] == pytest.approx(50.0)


# ============================================================================
# Random Trace Generation Tests
# ============================================================================


class TestRandomTrace:
    """Tests for the random_trace function."""

    def test_random_trace_respects_length(self) -> None:
        """Random trace should have the requested length."""
        for length in [20, 50, 100, 200]:
            trace = random_trace(length)
            assert len(trace.points) == length

    def test_random_trace_clamps_min_length(self) -> None:
        """Random trace should clamp length to minimum 20."""
        trace = random_trace(5)
        assert len(trace.points) == 20

    def test_random_trace_clamps_max_length(self) -> None:
        """Random trace should clamp length to maximum 500."""
        trace = random_trace(1000)
        assert len(trace.points) == 500

    def test_random_trace_starts_at_zero(self) -> None:
        """Random trace should always start at 0."""
        for _ in range(10):
            trace = random_trace(100)
            assert trace.points[0] == 0

    def test_random_trace_ends_at_zero(self) -> None:
        """Random trace should always end at 0."""
        for _ in range(10):
            trace = random_trace(100)
            assert trace.points[-1] == 0

    def test_random_trace_all_values_valid(self) -> None:
        """All values in random trace should be in range 0-100."""
        for _ in range(10):
            trace = random_trace(100)
            for point in trace.points:
                assert 0 <= point <= 100

    def test_random_trace_has_variation(self) -> None:
        """Random trace should have some variation (not all zeros)."""
        trace = random_trace(100)
        # Should have at least some non-zero values
        non_zero = sum(1 for p in trace.points if p > 0)
        assert non_zero > 0

    def test_random_trace_name(self) -> None:
        """Random trace should have correct name."""
        trace = random_trace(100)
        assert trace.name == "Random target"

    def test_random_traces_are_different(self) -> None:
        """Multiple random traces should be different."""
        traces = [random_trace(100) for _ in range(5)]
        # At least some should be different
        unique_traces = set(tuple(t.points) for t in traces)
        assert len(unique_traces) > 1


# ============================================================================
# Preset Traces Tests
# ============================================================================


class TestPresets:
    """Tests for the presets function."""

    def test_presets_returns_dict(self) -> None:
        """Presets should return a dictionary."""
        p = presets()
        assert isinstance(p, dict)

    def test_presets_contains_expected_traces(self) -> None:
        """Presets should contain the expected trace names."""
        p = presets()
        expected = ["Trail brake (example)", "Stab brake (example)", "Plateau release (example)"]
        for name in expected:
            assert name in p

    def test_preset_traces_are_valid(self) -> None:
        """All preset traces should be valid BrakeTrace objects."""
        p = presets()
        for name, trace in p.items():
            assert isinstance(trace, BrakeTrace)
            assert trace.name == name
            assert len(trace.points) > 0

    def test_preset_traces_start_at_zero(self) -> None:
        """All preset traces should start at 0."""
        p = presets()
        for trace in p.values():
            assert trace.points[0] == 0

    def test_preset_traces_end_at_zero(self) -> None:
        """All preset traces should end at 0."""
        p = presets()
        for trace in p.values():
            assert trace.points[-1] == 0

    def test_trail_brake_has_decay_pattern(self) -> None:
        """Trail brake should have a decaying pattern (generally decreasing)."""
        p = presets()
        trail = p["Trail brake (example)"]
        # First few values should be high, last few should be low
        avg_first_10 = sum(trail.points[1:11]) / 10  # Skip forced zero at start
        avg_last_10 = sum(trail.points[-11:-1]) / 10  # Skip forced zero at end
        assert avg_first_10 > avg_last_10

    def test_stab_brake_is_short_duration(self) -> None:
        """Stab brake should have most of its action early then zeros."""
        p = presets()
        stab = p["Stab brake (example)"]
        # After first 25 points, should be mostly zeros
        late_values = stab.points[25:]
        zeros = sum(1 for v in late_values if v == 0)
        assert zeros > len(late_values) * 0.9

    def test_plateau_has_sustained_maximum(self) -> None:
        """Plateau release should have sustained high values in the middle."""
        p = presets()
        plateau = p["Plateau release (example)"]
        # Middle section should have high values
        middle_values = plateau.points[20:60]
        high_values = sum(1 for v in middle_values if v >= 95)
        assert high_values > len(middle_values) * 0.9

    def test_presets_are_deterministic(self) -> None:
        """Presets should return the same traces on each call."""
        p1 = presets()
        p2 = presets()
        for name in p1:
            assert p1[name].points == p2[name].points
