"""Tests for the UI utility module.

This module tests shared UI utilities including helper functions and constants.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from mmt_app.ui.utils import (
    AXIS_MIN,
    AXIS_MAX,
    AXIS_VALUE_MIN,
    AXIS_VALUE_MAX,
    scale_axis,
    clamp,
    clamp_int,
    snap_to_step,
    resource_path,
)


# ============================================================================
# Constants Tests
# ============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_axis_percentage_range(self) -> None:
        """Percentage axis should be 0-100."""
        assert AXIS_MIN == 0
        assert AXIS_MAX == 100

    def test_axis_value_range(self) -> None:
        """Raw axis values should be 0-255."""
        assert AXIS_VALUE_MIN == 0
        assert AXIS_VALUE_MAX == 255


# ============================================================================
# Scale Axis Tests
# ============================================================================


class TestScaleAxis:
    """Tests for the scale_axis function."""

    def test_scale_axis_min_value(self) -> None:
        """Minimum value should scale to 0."""
        assert scale_axis(0) == pytest.approx(0.0)

    def test_scale_axis_max_value(self) -> None:
        """Maximum value should scale to 1."""
        assert scale_axis(255) == pytest.approx(1.0)

    def test_scale_axis_midpoint(self) -> None:
        """Midpoint should scale to approximately 0.5."""
        assert scale_axis(127) == pytest.approx(127 / 255.0)
        assert scale_axis(128) == pytest.approx(128 / 255.0)

    def test_scale_axis_custom_range(self) -> None:
        """Should work with custom lo/hi bounds."""
        assert scale_axis(50, lo=0, hi=100) == pytest.approx(0.5)
        assert scale_axis(0, lo=0, hi=100) == pytest.approx(0.0)
        assert scale_axis(100, lo=0, hi=100) == pytest.approx(1.0)

    def test_scale_axis_clamps_below_min(self) -> None:
        """Values below minimum should clamp to 0."""
        assert scale_axis(-10) == pytest.approx(0.0)

    def test_scale_axis_clamps_above_max(self) -> None:
        """Values above maximum should clamp to 1."""
        assert scale_axis(300) == pytest.approx(1.0)

    def test_scale_axis_equal_bounds(self) -> None:
        """Equal lo/hi bounds should return 0 to avoid division by zero."""
        assert scale_axis(50, lo=50, hi=50) == 0.0


# ============================================================================
# Clamp Tests
# ============================================================================


class TestClamp:
    """Tests for the clamp function."""

    def test_clamp_value_in_range(self) -> None:
        """Value within range should be unchanged."""
        assert clamp(50.0, 0.0, 100.0) == 50.0

    def test_clamp_value_below_min(self) -> None:
        """Value below minimum should be clamped to minimum."""
        assert clamp(-10.0, 0.0, 100.0) == 0.0

    def test_clamp_value_above_max(self) -> None:
        """Value above maximum should be clamped to maximum."""
        assert clamp(150.0, 0.0, 100.0) == 100.0

    def test_clamp_at_boundaries(self) -> None:
        """Values at boundaries should be unchanged."""
        assert clamp(0.0, 0.0, 100.0) == 0.0
        assert clamp(100.0, 0.0, 100.0) == 100.0

    def test_clamp_negative_range(self) -> None:
        """Should work with negative ranges."""
        assert clamp(-50.0, -100.0, 0.0) == -50.0
        assert clamp(50.0, -100.0, 0.0) == 0.0
        assert clamp(-150.0, -100.0, 0.0) == -100.0


class TestClampInt:
    """Tests for the clamp_int function."""

    def test_clamp_int_value_in_range(self) -> None:
        """Integer value within range should be unchanged."""
        assert clamp_int(50, 0, 100) == 50

    def test_clamp_int_value_below_min(self) -> None:
        """Integer below minimum should be clamped to minimum."""
        assert clamp_int(-10, 0, 100) == 0

    def test_clamp_int_value_above_max(self) -> None:
        """Integer above maximum should be clamped to maximum."""
        assert clamp_int(150, 0, 100) == 100

    def test_clamp_int_returns_int(self) -> None:
        """Result should always be an integer."""
        result = clamp_int(50, 0, 100)
        assert isinstance(result, int)


# ============================================================================
# Snap to Step Tests
# ============================================================================


class TestSnapToStep:
    """Tests for the snap_to_step function."""

    def test_snap_exact_step(self) -> None:
        """Value on a step should be unchanged."""
        assert snap_to_step(50, 10) == 50
        assert snap_to_step(100, 25) == 100

    def test_snap_rounds_down(self) -> None:
        """Value just below midpoint should round down."""
        assert snap_to_step(14, 10) == 10

    def test_snap_rounds_up(self) -> None:
        """Value at or above midpoint should round up."""
        assert snap_to_step(15, 10) == 20
        assert snap_to_step(16, 10) == 20

    def test_snap_zero(self) -> None:
        """Zero should stay zero."""
        assert snap_to_step(0, 10) == 0

    def test_snap_step_of_one(self) -> None:
        """Step of 1 should return unchanged value."""
        assert snap_to_step(47, 1) == 47

    def test_snap_various_steps(self) -> None:
        """Should work with various step sizes."""
        assert snap_to_step(7, 5) == 5
        assert snap_to_step(8, 5) == 10
        assert snap_to_step(12, 5) == 10
        assert snap_to_step(13, 5) == 15


# ============================================================================
# Resource Path Tests
# ============================================================================


class TestResourcePath:
    """Tests for the resource_path function."""

    def test_resource_path_returns_path(self) -> None:
        """Should return a Path object."""
        result = resource_path("styles", "theme.qss")
        assert isinstance(result, Path)

    def test_resource_path_single_component(self) -> None:
        """Should work with single path component."""
        result = resource_path("styles")
        assert result.name == "styles"

    def test_resource_path_multiple_components(self) -> None:
        """Should work with multiple path components."""
        result = resource_path("a", "b", "c.txt")
        assert str(result).endswith("a/b/c.txt") or str(result).endswith("a\\b\\c.txt")

    def test_resource_path_theme_exists(self) -> None:
        """Theme file should exist at resource path."""
        theme = resource_path("styles", "theme.qss")
        assert theme.exists()
