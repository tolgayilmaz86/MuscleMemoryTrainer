from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    """Result of detecting which report byte corresponds to a control."""

    offset: int
    score: float


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

