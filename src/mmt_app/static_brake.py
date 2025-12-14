from __future__ import annotations

import math
import random
from dataclasses import dataclass
from math import exp
from typing import Dict, List


@dataclass(frozen=True, slots=True)
class BrakeTrace:
    """A fixed-length brake trace (0..100) sampled at uniform steps."""

    name: str
    points: List[int]

    def __post_init__(self) -> None:
        if not self.points:
            raise ValueError("BrakeTrace.points must not be empty")
        for p in self.points:
            if not 0 <= int(p) <= 100:
                raise ValueError("BrakeTrace points must be within 0..100")


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


def _smooth(values: list[float], *, passes: int = 2) -> list[float]:
    smoothed = list(values)
    for _ in range(max(0, passes)):
        buf: list[float] = []
        for i, v in enumerate(smoothed):
            left = smoothed[i - 1] if i > 0 else v
            right = smoothed[i + 1] if i + 1 < len(smoothed) else v
            buf.append((left + v * 2 + right) / 4.0)
        smoothed = buf
    return smoothed


def _jitter(values: list[float], *, spread: float = 1.5) -> list[float]:
    return [max(0.0, min(100.0, v + random.uniform(-spread, spread))) for v in values]


def _anchors_for_length(length: int) -> list[tuple[int, float]]:
    """
    Build a small set of anchor points (start/end at zero) to shape a random trace.
    Peaks are placed roughly across the length with slight jitter.
    """
    anchors: list[tuple[int, float]] = [(0, 0.0)]
    peaks = max(1, min(3, length // 40))
    spacing = max(6, length / float(peaks + 1))
    jitter = max(1, int(spacing * 0.35))
    for i in range(1, peaks + 1):
        pos = int(i * spacing + random.randint(-jitter, jitter))
        pos = max(1, min(length - 2, pos))
        height = random.uniform(45.0, 100.0) if random.random() < 0.8 else random.uniform(20.0, 70.0)
        anchors.append((pos, height))
    anchors.append((length - 1, 0.0))
    anchors.sort(key=lambda p: p[0])

    deduped: list[tuple[int, float]] = []
    for x, y in anchors:
        if deduped and x == deduped[-1][0]:
            prev_x, prev_y = deduped[-1]
            deduped[-1] = (prev_x, max(prev_y, y))
        else:
            deduped.append((x, y))
    if len(deduped) < 2:
        deduped = [(0, 0.0), (length - 1, 0.0)]
    return deduped


def _interpolate_anchors(anchors: list[tuple[int, float]], length: int) -> list[float]:
    values: list[float] = []
    left = anchors[0]
    right_index = 1
    right = anchors[right_index]
    for x in range(length):
        while right_index + 1 < len(anchors) and x > right[0]:
            left = right
            right_index += 1
            right = anchors[right_index]
        if right[0] == left[0]:
            y = left[1]
        else:
            t = (x - left[0]) / float(right[0] - left[0])
            y = left[1] + (right[1] - left[1]) * _ease(t)
        values.append(y)
    return values


def _clamp_points(values: list[float], *, force_end_zero: bool = False) -> list[int]:
    if not values:
        return [0]
    clamped = [int(round(max(0.0, min(100.0, v)))) for v in values]
    clamped[0] = 0
    if force_end_zero:
        clamped[-1] = 0
    return clamped


def random_trace(length: int = 101) -> BrakeTrace:
    """Generate a random static brake trace that always starts/ends at 0%."""
    length = max(20, min(500, int(length)))
    anchors = _anchors_for_length(length)
    values = _interpolate_anchors(anchors, length)
    values = _smooth(_jitter(values))
    values[0] = 0.0
    values[-1] = 0.0
    return BrakeTrace("Random target", _clamp_points(values, force_end_zero=True))


def presets() -> Dict[str, BrakeTrace]:
    """Built-in example traces (can be replaced with real corner data later)."""
    length = 101  # x: 0..100
    x = list(range(length))

    # Heavy initial braking then trail off.
    trail = [int(round(100 * exp(-i / 28.0))) for i in x]

    # Quick stab then release.
    stab = [0] * length
    for i in range(length):
        if i < 10:
            stab[i] = int(round(i * 10))
        elif i < 20:
            stab[i] = int(round(100 - (i - 10) * 10))
        else:
            stab[i] = 0

    # Plateau then gradual release.
    plateau = []
    for i in range(length):
        if i < 20:
            plateau.append(int(round(i * 5)))
        elif i < 60:
            plateau.append(100)
        else:
            plateau.append(max(0, 100 - int(round((i - 60) * 2.5))))

    return {
        "Trail brake (example)": BrakeTrace("Trail brake (example)", _clamp_points(trail, force_end_zero=True)),
        "Stab brake (example)": BrakeTrace("Stab brake (example)", _clamp_points(stab, force_end_zero=True)),
        "Plateau release (example)": BrakeTrace(
            "Plateau release (example)", _clamp_points(plateau, force_end_zero=True)
        ),
    }
