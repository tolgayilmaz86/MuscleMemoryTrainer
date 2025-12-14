from __future__ import annotations

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
        "Trail brake (example)": BrakeTrace("Trail brake (example)", trail),
        "Stab brake (example)": BrakeTrace("Stab brake (example)", stab),
        "Plateau release (example)": BrakeTrace("Plateau release (example)", plateau),
    }

