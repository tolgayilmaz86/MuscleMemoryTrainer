"""Trail brake trace generation and management.

This module provides functionality for creating brake pressure traces used in
trail brake training. It includes:
- Random trace generation with smooth, realistic curves
- Preset traces for common braking patterns (trail braking, stab braking, etc.)
- Mathematical utilities for smoothing and interpolation

Brake traces represent brake pressure over time as a list of integer percentages
(0-100), where each index represents a discrete time step.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from math import exp
from typing import Dict, List

# ============================================================================
# Constants
# ============================================================================

# Brake percentage bounds
_BRAKE_MIN = 0
_BRAKE_MAX = 100

# Trace length constraints
_MIN_TRACE_LENGTH = 20
_MAX_TRACE_LENGTH = 500
_DEFAULT_TRACE_LENGTH = 101

# Random generation parameters
_MIN_PEAKS = 1
_MAX_PEAKS = 3
_PEAK_SPACING_DIVISOR = 40  # Higher = fewer peaks for given length
_MIN_ANCHOR_SPACING = 6
_JITTER_RATIO = 0.35  # Position jitter as fraction of spacing

# Peak height ranges (percentage)
_PEAK_HEIGHT_MIN_NORMAL = 45.0
_PEAK_HEIGHT_MAX_NORMAL = 100.0
_PEAK_HEIGHT_MIN_LOW = 20.0
_PEAK_HEIGHT_MAX_LOW = 70.0
_LOW_PEAK_PROBABILITY = 0.2  # 20% chance of a lower peak

# Smoothing parameters
_DEFAULT_SMOOTH_PASSES = 4  # More passes for smoother curves
_DEFAULT_JITTER_SPREAD = 1.0  # Reduced jitter for cleaner shapes


@dataclass(frozen=True, slots=True)
class BrakeTrace:
    """A fixed-length brake trace representing brake pressure over time.

    Each point in the trace represents the brake pressure percentage (0-100)
    at a discrete time step. The trace is immutable once created.

    Attributes:
        name: Human-readable name for the trace (e.g., "Trail brake").
        points: List of brake pressure values (0-100) at each time step.

    Example:
        >>> trace = BrakeTrace("My trace", [0, 50, 100, 50, 0])
        >>> len(trace.points)  # 5 time steps
        5
    """

    name: str
    points: List[int]

    def __post_init__(self) -> None:
        """Validate trace data on creation."""
        if not self.points:
            raise ValueError("BrakeTrace.points must not be empty")
        for p in self.points:
            if not _BRAKE_MIN <= int(p) <= _BRAKE_MAX:
                raise ValueError(f"BrakeTrace points must be within {_BRAKE_MIN}..{_BRAKE_MAX}")


# ============================================================================
# Mathematical Utilities
# ============================================================================


def ease(t: float) -> float:
    """Apply smooth easing (ease-in-out) to a normalized input.

    This function converts a linear input (0 to 1) into a smooth S-curve,
    making transitions look more natural. It uses a cosine-based formula
    that produces gradual acceleration at the start and deceleration at the end.

    Mathematical explanation:
    - cos(0) = 1, cos(π) = -1
    - As t goes from 0 to 1, (π * t) goes from 0 to π
    - cos(π * t) goes from 1 to -1
    - 0.5 - 0.5 * cos(π * t) transforms this to go from 0 to 1
    - The result is an S-shaped curve (slow-fast-slow)

    Visual representation:
        Input (linear):  0 -------- 0.5 -------- 1
        Output (eased):  0 ---___--- 0.5 ---___--- 1
                            (slow)       (slow)
                                 (fast)

    Args:
        t: Input value, typically in range [0, 1].

    Returns:
        Eased value in range [0, 1], following an S-curve.

    Example:
        >>> ease(0.0)   # Start: returns 0.0
        >>> ease(0.5)   # Middle: returns 0.5 (inflection point)
        >>> ease(1.0)   # End: returns 1.0
    """
    # Clamp input to valid range to prevent unexpected results
    t = max(0.0, min(1.0, t))

    # Cosine easing formula:
    # - At t=0: cos(0) = 1, so result = 0.5 - 0.5*1 = 0
    # - At t=0.5: cos(π/2) = 0, so result = 0.5 - 0 = 0.5
    # - At t=1: cos(π) = -1, so result = 0.5 - 0.5*(-1) = 1
    return 0.5 - 0.5 * math.cos(math.pi * t)


def smooth(values: list[float], *, passes: int = _DEFAULT_SMOOTH_PASSES) -> list[float]:
    """Apply weighted moving average smoothing to reduce noise.

    This uses a 3-point weighted kernel [1, 2, 1] / 4, which gives more
    weight to the center value while still incorporating neighbors.
    Multiple passes increase smoothness.

    Mathematical explanation:
    For each point, the new value is calculated as:
        new_value = (left + 2*center + right) / 4

    This is equivalent to a weighted average where:
    - Left neighbor contributes 25%
    - Center value contributes 50%
    - Right neighbor contributes 25%

    Why this works:
    - The center value has the most influence (preserves overall shape)
    - Neighbors pull the value toward local average (reduces noise)
    - Multiple passes compound the effect for smoother results

    Example with values [10, 50, 20]:
        new_middle = (10 + 2*50 + 20) / 4 = 130 / 4 = 32.5
        The spike at 50 is reduced toward the average.

    Args:
        values: List of values to smooth.
        passes: Number of smoothing iterations (default: 4).

    Returns:
        Smoothed list of values (same length as input).
    """
    if not values:
        return values
    smoothed = list(values)

    for _ in range(max(0, passes)):
        buf: list[float] = []
        for i, v in enumerate(smoothed):
            # Handle boundaries: use current value if no neighbor exists
            left = smoothed[i - 1] if i > 0 else v
            right = smoothed[i + 1] if i + 1 < len(smoothed) else v

            # Apply weighted kernel: [1, 2, 1] / 4
            # This gives 25% weight to each neighbor and 50% to center
            smoothed_value = (left + v * 2 + right) / 4.0
            buf.append(smoothed_value)

        smoothed = buf

    return [max(0.0, min(100.0, v)) for v in smoothed]


def jitter(values: list[float], *, spread: float = _DEFAULT_JITTER_SPREAD) -> list[float]:
    """Add small random variations to values for a more natural appearance.

    Real-world brake inputs are never perfectly smooth - there's always
    slight variation from pedal feedback, foot movement, etc. This function
    simulates that natural variation.

    Mathematical explanation:
    For each value, add a random offset uniformly distributed in [-spread, +spread].
    The result is then clamped to [0, 100] to stay within valid brake range.

    Example with spread=1.0:
        Original value: 50.0
        Random offset: anywhere from -1.0 to +1.0
        Result: between 49.0 and 51.0

    Args:
        values: List of values to add jitter to.
        spread: Maximum deviation in either direction (default: 1.0).

    Returns:
        List of jittered values, clamped to [0, 100].
    """
    return [
        max(0.0, min(100.0, v + random.uniform(-spread, spread)))
        for v in values
    ]


# ============================================================================
# Anchor Point Generation
# ============================================================================


def _anchors_for_length(length: int) -> list[tuple[int, float]]:
    """Generate anchor points that define the shape of a random brake trace.

    This function creates a sparse set of key points (anchors) that will be
    interpolated to form the full trace. Think of anchors as the "skeleton"
    of the curve - they define where peaks and valleys occur.

    Strategy:
    1. Always start at (0, 0) - trace begins with no braking
    2. Place 1-3 peaks at roughly even intervals with random heights
    3. Always end at (length-1, 0) - trace ends with no braking
    4. Add position jitter so peaks don't fall on exact grid points

    Mathematical explanation:
    - Number of peaks scales with length: peaks = length / 40 (capped at 1-3)
    - Spacing between peaks: spacing = length / (peaks + 1)
    - Position jitter: ±35% of spacing to add randomness

    Example for length=100 with 2 peaks:
        Base spacing = 100 / 3 ≈ 33
        Jitter range = ±11 (±35% of 33)
        Peak 1 position: ~33 ± 11 = somewhere in [22, 44]
        Peak 2 position: ~66 ± 11 = somewhere in [55, 77]

    Args:
        length: Total number of points in the trace.

    Returns:
        List of (position, height) tuples, sorted by position.
        Always includes (0, 0) and (length-1, 0) as endpoints.
    """
    # Start with origin anchor - braking always starts at 0%
    anchors: list[tuple[int, float]] = [(0, 0.0)]

    # Calculate number of peaks based on trace length
    # Longer traces get more peaks, but capped at 1-3 for realism
    peaks = max(_MIN_PEAKS, min(_MAX_PEAKS, length // _PEAK_SPACING_DIVISOR))

    # Calculate spacing between peaks
    # We divide by (peaks + 1) to leave room at start and end
    spacing = max(_MIN_ANCHOR_SPACING, length / float(peaks + 1))

    # Position jitter: random offset to avoid mechanical-looking regular intervals
    jitter = max(1, int(spacing * _JITTER_RATIO))

    # Generate peak anchors
    for i in range(1, peaks + 1):
        # Base position: evenly spaced
        pos = int(i * spacing + random.randint(-jitter, jitter))
        # Clamp to valid range (leave room for start/end anchors)
        pos = max(1, min(length - 2, pos))

        # Peak height: 80% chance of high peak (45-100%), 20% chance of lower (20-70%)
        # This creates variety while ensuring most traces have strong braking zones
        if random.random() < _LOW_PEAK_PROBABILITY:
            height = random.uniform(_PEAK_HEIGHT_MIN_LOW, _PEAK_HEIGHT_MAX_LOW)
        else:
            height = random.uniform(_PEAK_HEIGHT_MIN_NORMAL, _PEAK_HEIGHT_MAX_NORMAL)

        anchors.append((pos, height))

    # End anchor - braking always returns to 0%
    anchors.append((length - 1, 0.0))

    # Sort by position to ensure proper interpolation order
    anchors.sort(key=lambda p: p[0])

    # Remove duplicate positions (keep highest value if overlapping)
    deduped: list[tuple[int, float]] = []
    for x, y in anchors:
        if deduped and x == deduped[-1][0]:
            # Duplicate position: keep the higher value
            prev_x, prev_y = deduped[-1]
            deduped[-1] = (prev_x, max(prev_y, y))
        else:
            deduped.append((x, y))

    # Ensure we have at least start and end points
    if len(deduped) < 2:
        deduped = [(0, 0.0), (length - 1, 0.0)]

    return deduped


# ============================================================================
# Interpolation
# ============================================================================


def _interpolate_anchors(anchors: list[tuple[int, float]], length: int) -> list[float]:
    """Interpolate between anchor points to create a smooth continuous curve.

    This function fills in all the values between anchor points using
    eased interpolation. The result is a smooth curve that passes through
    (or near) all anchor points.

    Algorithm:
    1. Walk through each x position from 0 to length-1
    2. Find which two anchors the current x falls between
    3. Calculate how far between them we are (as fraction t from 0 to 1)
    4. Apply easing to t for smooth acceleration/deceleration
    5. Linearly interpolate the y value using the eased t

    Mathematical explanation of interpolation:
    Given two anchors (x1, y1) and (x2, y2) and current position x:
        t = (x - x1) / (x2 - x1)     # Linear fraction (0 to 1)
        t_eased = _ease(t)            # Apply S-curve for smoothness
        y = y1 + (y2 - y1) * t_eased  # Interpolated value

    Visual example:
        Anchors: (0, 0), (50, 100), (100, 0)

        Without easing (linear):    With easing (smooth):
        100|    /\\                 100|    _/\\_
           |   /  \\                   |   /    \\
           |  /    \\                  |  /      \\
         0 | /      \\               0 |_/        \\_
           +----------                +----------
             0  50 100                  0  50 100

    Args:
        anchors: List of (position, height) tuples defining key points.
        length: Total number of output values.

    Returns:
        List of interpolated values for each position 0 to length-1.
    """
    values: list[float] = []

    # Start with first anchor as the "left" boundary
    left = anchors[0]
    right_index = 1
    right = anchors[right_index]

    for x in range(length):
        # Advance to next anchor segment if we've passed the current right boundary
        while right_index + 1 < len(anchors) and x > right[0]:
            left = right
            right_index += 1
            right = anchors[right_index]

        if right[0] == left[0]:
            # Anchors at same position (edge case): just use left value
            y = left[1]
        else:
            # Calculate interpolation parameter t (0 to 1)
            # t = 0 at left anchor, t = 1 at right anchor
            t = (x - left[0]) / float(right[0] - left[0])

            # Apply easing for smooth transitions
            # This makes the curve slow down near anchors and speed up between them
            t_eased = ease(t)

            # Linear interpolation with eased parameter
            # y = y1 + (y2 - y1) * t = start + (change * progress)
            y = left[1] + (right[1] - left[1]) * t_eased

        values.append(y)

    return values


# ============================================================================
# Value Clamping and Finalization
# ============================================================================


def _clamp_points(values: list[float], *, force_end_zero: bool = False) -> list[int]:
    """Convert float values to integers and enforce valid brake range.

    This is the final step in trace generation - converting smooth float
    values to the integer percentages used by the training system.

    Operations:
    1. Round each value to nearest integer
    2. Clamp to valid range [0, 100]
    3. Force first value to 0 (braking always starts at rest)
    4. Optionally force last value to 0 (full release at end)

    Args:
        values: List of float values to convert.
        force_end_zero: If True, ensure last point is 0%.

    Returns:
        List of integer brake percentages in range [0, 100].
    """
    if not values:
        return [0]

    # Round and clamp each value to valid integer range
    clamped = [int(round(max(0.0, min(100.0, v)))) for v in values]

    # Ensure trace starts at 0% (no initial braking)
    clamped[0] = 0

    # Optionally ensure trace ends at 0% (full brake release)
    if force_end_zero:
        clamped[-1] = 0

    return clamped


# ============================================================================
# Public API
# ============================================================================


def random_trace(length: int = _DEFAULT_TRACE_LENGTH) -> BrakeTrace:
    """Generate a random static brake trace that always starts/ends at 0%.

    This is the main function for creating practice traces. It generates
    realistic-looking brake pressure curves using a multi-step process:

    Generation Pipeline:
    1. Create anchor points (sparse key positions with peak heights)
    2. Interpolate between anchors using smooth easing
    3. Add small jitter for natural variation
    4. Apply smoothing to blend the jitter
    5. Clamp all values to valid range and convert to integers

    The result mimics real braking patterns seen in motorsport:
    - Gradual pressure build-up (not instant jumps)
    - Peak pressure zones followed by trail-off
    - Natural micro-variations in pressure

    Args:
        length: Number of points in the trace (clamped to 20-500).
                Default is 101 (matching 0-100 percentage scale).

    Returns:
        BrakeTrace with the generated points, named "Random target".

    Example:
        >>> trace = random_trace(100)
        >>> len(trace.points)
        100
        >>> trace.points[0]  # Always starts at 0
        0
        >>> trace.points[-1]  # Always ends at 0
        0
    """
    # Clamp length to valid range
    length = max(_MIN_TRACE_LENGTH, min(_MAX_TRACE_LENGTH, int(length)))

    # Step 1: Generate anchor points (sparse skeleton of the curve)
    anchors = _anchors_for_length(length)

    # Step 2: Interpolate to fill in all values between anchors
    values = _interpolate_anchors(anchors, length)

    # Step 3: Apply smoothing first to get clean curves from interpolation
    values = smooth(values, passes=3)

    # Step 4: Add subtle jitter for natural variation, then smooth again to blend
    values = smooth(jitter(values, spread=0.8), passes=2)

    # Step 5: Ensure endpoints are exactly zero (may have drifted from jitter)
    values[0] = 0.0
    values[-1] = 0.0

    return BrakeTrace("Random target", _clamp_points(values, force_end_zero=True))


def presets() -> Dict[str, BrakeTrace]:
    """Get built-in example traces demonstrating common braking techniques.

    These presets represent fundamental braking patterns used in motorsport:

    1. Trail Brake:
       - Heavy initial braking that gradually releases
       - Uses exponential decay: pressure = 100 * e^(-x/28)
       - Common in corner entry to maintain front grip while rotating
       - The decay constant (28) controls how quickly pressure drops

    2. Stab Brake:
       - Quick, aggressive application then immediate release
       - Linear ramp up over 10 steps, linear ramp down over 10 steps
       - Used for quick speed scrubs before chicanes or obstacles
       - Total brake zone is only 20 steps out of 101

    3. Plateau Release:
       - Build pressure, hold at maximum, then gradually release
       - Ramp to 100% over 20 steps, hold for 40 steps, release over 40 steps
       - Common in heavy braking zones where maximum deceleration is needed
       - The hold phase represents ABS-limited maximum braking

    Returns:
        Dictionary mapping trace names to BrakeTrace objects.
    """
    length = _DEFAULT_TRACE_LENGTH  # x: 0..100 (101 points)
    x = list(range(length))

    # -------------------------------------------------------------------------
    # Trail Brake: Exponential decay from peak braking
    # -------------------------------------------------------------------------
    # Formula: pressure = 100 * e^(-i/28)
    #
    # Mathematical explanation:
    # - e^0 = 1, so at i=0: pressure = 100 * 1 = 100%
    # - e^(-1) ≈ 0.37, so at i=28: pressure ≈ 37%
    # - e^(-2) ≈ 0.14, so at i=56: pressure ≈ 14%
    # - The larger the divisor (28), the slower the decay
    #
    # This models the driver progressively releasing the brake while
    # turning into a corner, maintaining balance as grip shifts to steering.
    trail = [int(round(_BRAKE_MAX * exp(-i / 28.0))) for i in x]

    # -------------------------------------------------------------------------
    # Stab Brake: Quick on, quick off
    # -------------------------------------------------------------------------
    # Shape: /\ (sharp triangle)
    #
    # Steps 0-9:   Ramp up   (i * 10) -> 0, 10, 20...90
    # Step 10:     Peak at 100
    # Steps 10-19: Ramp down (100 - (i-10)*10) -> 100, 90, 80...10
    # Steps 20+:   Zero
    #
    # This is used for quick speed adjustments where sustained braking
    # isn't needed - just a brief scrub of speed.
    stab = [0] * length
    for i in range(length):
        if i < 10:
            # Ramp up: 10% per step
            stab[i] = int(round(i * 10))
        elif i < 20:
            # Ramp down: 10% per step from peak
            stab[i] = int(round(_BRAKE_MAX - (i - 10) * 10))
        else:
            # No braking for remainder
            stab[i] = 0

    # -------------------------------------------------------------------------
    # Plateau Release: Build, hold, release
    # -------------------------------------------------------------------------
    # Shape: __/‾‾‾‾\_
    #
    # Steps 0-19:  Ramp up (i * 5) -> 0, 5, 10...95, 100
    # Steps 20-59: Hold at 100% (40 steps of maximum braking)
    # Steps 60-99: Ramp down (100 - (i-60)*2.5) -> 100, 97.5, 95...
    #
    # This represents threshold braking in heavy brake zones:
    # - Progressive application to find grip limit
    # - Sustained maximum braking for deceleration
    # - Gradual release as corner approaches
    plateau = []
    for i in range(length):
        if i < 20:
            # Ramp up at 5% per step
            plateau.append(int(round(i * 5)))
        elif i < 60:
            # Hold at maximum
            plateau.append(_BRAKE_MAX)
        else:
            # Gradual release at 2.5% per step
            plateau.append(max(0, _BRAKE_MAX - int(round((i - 60) * 2.5))))

    return {
        "Trail brake (example)": BrakeTrace(
            "Trail brake (example)",
            _clamp_points(trail, force_end_zero=True)
        ),
        "Stab brake (example)": BrakeTrace(
            "Stab brake (example)",
            _clamp_points(stab, force_end_zero=True)
        ),
        "Plateau release (example)": BrakeTrace(
            "Plateau release (example)",
            _clamp_points(plateau, force_end_zero=True)
        ),
    }
