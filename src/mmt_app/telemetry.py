from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TelemetrySample:
    """Normalized inputs used across the app.

    - `throttle`/`brake` are percentages in range 0..100.
    - `steering` is normalized in range -100..100 (left..right).
    """

    throttle: float
    brake: float
    steering: float

