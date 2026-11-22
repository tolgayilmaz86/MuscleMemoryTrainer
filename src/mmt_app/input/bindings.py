"""Map controller axes to throttle / brake / steering, the way games do it.

Binding works by movement instead of byte offsets: the user presses the pedal
(or turns the wheel) they want, and whichever axis on whichever controller
moved the most is bound. The press also calibrates the pedal: the released
position becomes 0% and the deepest point becomes 100%, which handles inverted
pedals and load-cell brakes that never reach the end of their logical range.
"""

from __future__ import annotations

import configparser
from collections.abc import Iterable
from dataclasses import dataclass

from mmt_app import config as app_config
from mmt_app.input.controllers import Controller, InputHub
from mmt_app.input.hid_descriptor import AxisField

ROLES = ("throttle", "brake", "steering")
ROLE_LABELS = {"throttle": "Throttle", "brake": "Brake", "steering": "Steering"}

PEDAL_MIN_TRAVEL = 0.25  # A pedal press must cover this fraction of the axis range
STEERING_MIN_TRAVEL = 0.05  # ~half a turn even on a wheel base set to 2520 degrees
_PEDAL_RELEASE_TOLERANCE = 0.15  # "Released" = back within this fraction of the travel
_STEERING_RETURN_TOLERANCE = 0.3
_NOISE_TRAVEL = 0.01  # Movement below this is sensor noise
_MIN_SAMPLES = 3
_PEDAL_DEADZONE_LOW = 0.02  # Ensures a released pedal reads exactly 0%
_PEDAL_DEADZONE_HIGH = 0.02  # Makes 100% reachable without crushing the pedal


def _is_pedal(role: str) -> bool:
    return role != "steering"


@dataclass(frozen=True, slots=True)
class AxisBinding:
    """One controller axis bound to a role, with its calibration.

    Attributes:
        rest: Raw value with the pedal released / wheel centered.
        full: Raw value with the pedal fully pressed (pedals only).
    """

    vendor_id: int
    product_id: int
    product_string: str
    field: AxisField
    rest: int
    full: int

    @property
    def label(self) -> str:
        return f"{self.product_string} · {self.field.name}"

    def same_axis(self, other: AxisBinding) -> bool:
        return (self.vendor_id, self.product_id, self.field) == (
            other.vendor_id, other.product_id, other.field
        )

    def pedal_percent(self, raw: int) -> float:
        """Raw value -> 0..100 using the calibrated rest/full points."""
        travel = self.full - self.rest
        if travel == 0:
            return 0.0
        fraction = (raw - self.rest) / travel
        usable = 1.0 - _PEDAL_DEADZONE_LOW - _PEDAL_DEADZONE_HIGH
        return max(0.0, min(1.0, (fraction - _PEDAL_DEADZONE_LOW) / usable)) * 100.0

    def steering_percent(self, raw: int) -> float:
        """Raw value -> -100 (full left) .. 100 (full right)."""
        half_range = self.field.span / 2
        return max(-1.0, min(1.0, (raw - self.rest) / half_range)) * 100.0

    def percent(self, role: str, raw: int) -> float:
        return self.pedal_percent(raw) if _is_pedal(role) else self.steering_percent(raw)


# -----------------------------------------------------------------------------
# Detection
# -----------------------------------------------------------------------------


class _Track:
    """Movement statistics of one axis since detection started."""

    def __init__(self, controller: Controller, field: AxisField, raw: int) -> None:
        self.controller = controller
        self.field = field
        value = field.normalized(raw)
        self.start = self.last = self.low = self.high = value
        self.start_raw = self.last_raw = self.extreme_raw = raw
        self.low_raw = self.high_raw = raw
        self.variation = 0.0
        self.samples = 1

    def add(self, raw: int) -> None:
        value = self.field.normalized(raw)
        self.variation += abs(value - self.last)
        self.last, self.last_raw = value, raw
        self.low, self.high = min(self.low, value), max(self.high, value)
        self.low_raw, self.high_raw = min(self.low_raw, raw), max(self.high_raw, raw)
        if abs(raw - self.start_raw) > abs(self.extreme_raw - self.start_raw):
            self.extreme_raw = raw
        self.samples += 1

    @property
    def travel(self) -> float:
        """Total range covered, as a fraction of the axis range."""
        return self.high - self.low

    @property
    def deflection(self) -> float:
        """Current distance from the starting position (fraction of range)."""
        return abs(self.last - self.start)

    @property
    def score(self) -> float:
        if self.field.usage_page or self.variation == 0:
            return self.travel
        # Guessed byte fields: a low byte of a 16-bit value wraps around constantly;
        # penalize paths that are much longer than a press-and-release.
        return self.travel * min(1.0, 2 * self.travel / self.variation)


class AxisDetector:
    """Finds the axis the user is moving for a role ("press the brake now")."""

    def __init__(self, role: str, *, exclude: Iterable[AxisBinding] = ()) -> None:
        """Create a detector.

        Args:
            role: One of ROLES.
            exclude: Bindings whose axes must not be picked (e.g. already assigned).
        """
        self.role = role
        self.min_travel = PEDAL_MIN_TRAVEL if _is_pedal(role) else STEERING_MIN_TRAVEL
        self._return_tolerance = (
            _PEDAL_RELEASE_TOLERANCE if _is_pedal(role) else _STEERING_RETURN_TOLERANCE
        )
        self._exclude = {(b.vendor_id, b.product_id, b.field) for b in exclude}
        self._tracks: dict[tuple[bytes, AxisField], _Track] = {}

    def update(self, controllers: Iterable[Controller]) -> None:
        """Sample every axis of every controller once."""
        for controller in controllers:
            info = controller.info
            for field in controller.axes:
                if (info.vendor_id, info.product_id, field) in self._exclude:
                    continue
                raw = controller.value(field)
                if raw is None:
                    continue
                key = (info.path, field)
                track = self._tracks.get(key)
                if track is None:
                    self._tracks[key] = _Track(controller, field, raw)
                else:
                    track.add(raw)

    def leader(self) -> _Track | None:
        """The axis that has moved the most so far (None until something moves)."""
        moving = [
            t for t in self._tracks.values()
            if t.samples >= _MIN_SAMPLES and t.travel > _NOISE_TRAVEL
        ]
        if not moving:
            return None
        # Prefer wider fields on near-ties (a 16-bit axis over its own high byte).
        return max(moving, key=lambda t: (round(t.score * 20), t.field.bit_size, t.score))

    def reached_travel(self) -> bool:
        track = self.leader()
        return track is not None and track.travel >= self.min_travel

    def result(self) -> AxisBinding | None:
        """The binding once the axis moved far enough and came back, else None."""
        track = self.leader()
        if track is None or track.travel < self.min_travel:
            return None
        if track.deflection > self._return_tolerance * track.travel:
            return None  # Still pressed / turned.
        field = track.field
        if _is_pedal(self.role):
            # Detection completes while the pedal is still coming back up, so the last
            # sample isn't the released position; use the far end of what was seen.
            rest = track.low_raw if track.extreme_raw >= track.start_raw else track.high_raw
        elif field.usage_page:
            rest = round((field.logical_min + field.logical_max) / 2)
        else:
            rest = track.start_raw  # Guessed field: assume the wheel started centered.
        info = track.controller.info
        return AxisBinding(
            vendor_id=info.vendor_id,
            product_id=info.product_id,
            product_string=info.product_string,
            field=field,
            rest=rest,
            full=track.extreme_raw,
        )


# -----------------------------------------------------------------------------
# Reading bound axes
# -----------------------------------------------------------------------------


class InputMapper:
    """Reads throttle, brake and steering from the bound controller axes."""

    def __init__(self, hub: InputHub, bindings: dict[str, AxisBinding] | None = None) -> None:
        self._hub = hub
        self._bindings: dict[str, AxisBinding] = dict(bindings or {})

    @property
    def hub(self) -> InputHub:
        return self._hub

    @property
    def bindings(self) -> dict[str, AxisBinding]:
        return dict(self._bindings)

    def binding(self, role: str) -> AxisBinding | None:
        return self._bindings.get(role)

    def set_binding(self, role: str, binding: AxisBinding | None) -> None:
        if binding is None:
            self._bindings.pop(role, None)
        else:
            self._bindings[role] = binding

    def has_bindings(self) -> bool:
        return bool(self._bindings)

    def poll(self) -> list[str]:
        """Poll all controllers; returns names of controllers that were unplugged."""
        return [c.info.product_string for c in self._hub.poll()]

    def controller_for(self, role: str) -> Controller | None:
        binding = self._bindings.get(role)
        if binding is None:
            return None
        return self._hub.find(binding.vendor_id, binding.product_id, binding.field)

    def value(self, role: str) -> float | None:
        """Current value (pedals 0..100, steering -100..100), or None if unavailable."""
        binding = self._bindings.get(role)
        controller = self.controller_for(role)
        if binding is None or controller is None:
            return None
        raw = controller.value(binding.field)
        return None if raw is None else binding.percent(role, raw)

    def missing_devices(self) -> list[str]:
        """Names of bound controllers that are not connected."""
        missing: list[str] = []
        for role, binding in self._bindings.items():
            if self.controller_for(role) is None and binding.product_string not in missing:
                missing.append(binding.product_string)
        return missing


# -----------------------------------------------------------------------------
# Persistence (config.ini sections "binding.<role>")
# -----------------------------------------------------------------------------


def _section(role: str) -> str:
    return f"binding.{role}"


def _read_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(app_config.config_path(), encoding="utf-8")
    return parser


def load_bindings() -> dict[str, AxisBinding]:
    """Load saved axis bindings, skipping malformed sections."""
    parser = _read_parser()
    bindings: dict[str, AxisBinding] = {}
    for role in ROLES:
        if _section(role) not in parser:
            continue
        s = parser[_section(role)]
        try:
            field = AxisField(
                report_id=int(s["report_id"]),
                bit_offset=int(s["bit_offset"]),
                bit_size=int(s["bit_size"]),
                logical_min=int(s["logical_min"]),
                logical_max=int(s["logical_max"]),
                usage_page=int(s["usage_page"], 0),
                usage=int(s["usage"], 0),
                label=s.get("label", ""),
            )
            bindings[role] = AxisBinding(
                vendor_id=int(s["vendor_id"], 0),
                product_id=int(s["product_id"], 0),
                product_string=s.get("product_string", ""),
                field=field,
                rest=int(s["rest"]),
                full=int(s["full"]),
            )
        except (KeyError, ValueError):
            continue
    return bindings


def save_binding(role: str, binding: AxisBinding | None) -> None:
    """Persist (or remove, when None) the binding for a role."""
    parser = _read_parser()
    if binding is None:
        parser.remove_section(_section(role))
    else:
        field = binding.field
        parser[_section(role)] = {
            "vendor_id": hex(binding.vendor_id),
            "product_id": hex(binding.product_id),
            "product_string": binding.product_string,
            "report_id": str(field.report_id),
            "bit_offset": str(field.bit_offset),
            "bit_size": str(field.bit_size),
            "logical_min": str(field.logical_min),
            "logical_max": str(field.logical_max),
            "usage_page": hex(field.usage_page),
            "usage": hex(field.usage),
            "label": field.label,
            "rest": str(binding.rest),
            "full": str(binding.full),
        }
    app_config.write_config(parser)
