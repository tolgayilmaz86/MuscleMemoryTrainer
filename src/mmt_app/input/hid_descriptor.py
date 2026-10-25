"""HID report descriptor parsing: find the axes a game controller reports.

Games (through DirectInput, SDL, ...) never guess byte offsets. They read the
device's report descriptor, which states for every control which report it is
in, at which bit offset, how many bits it uses and its logical range. This
module does the same for the axes of joysticks, wheels and pedals.

Only what is needed for axes is implemented: global/local state, report IDs,
usage ranges, push/pop and Input main items. Buttons, hat switches, outputs,
features and vendor-defined fields are skipped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

# Usage pages
_PAGE_GENERIC_DESKTOP = 0x01
_PAGE_SIMULATION = 0x02

_AXIS_NAMES: dict[tuple[int, int], str] = {
    (_PAGE_GENERIC_DESKTOP, 0x30): "X",
    (_PAGE_GENERIC_DESKTOP, 0x31): "Y",
    (_PAGE_GENERIC_DESKTOP, 0x32): "Z",
    (_PAGE_GENERIC_DESKTOP, 0x33): "Rx",
    (_PAGE_GENERIC_DESKTOP, 0x34): "Ry",
    (_PAGE_GENERIC_DESKTOP, 0x35): "Rz",
    (_PAGE_GENERIC_DESKTOP, 0x36): "Slider",
    (_PAGE_GENERIC_DESKTOP, 0x37): "Dial",
    (_PAGE_GENERIC_DESKTOP, 0x38): "Wheel",
    (_PAGE_SIMULATION, 0xBA): "Rudder",
    (_PAGE_SIMULATION, 0xBB): "Throttle",
    (_PAGE_SIMULATION, 0xC4): "Accelerator",
    (_PAGE_SIMULATION, 0xC5): "Brake",
    (_PAGE_SIMULATION, 0xC6): "Clutch",
    (_PAGE_SIMULATION, 0xC8): "Steering",
}

# Item types and tags (HID 1.11, section 6.2.2)
_TYPE_MAIN, _TYPE_GLOBAL, _TYPE_LOCAL = 0, 1, 2
_MAIN_INPUT = 0x8
_GLOBAL_USAGE_PAGE, _GLOBAL_LOGICAL_MIN, _GLOBAL_LOGICAL_MAX = 0x0, 0x1, 0x2
_GLOBAL_REPORT_SIZE, _GLOBAL_REPORT_ID, _GLOBAL_REPORT_COUNT = 0x7, 0x8, 0x9
_GLOBAL_PUSH, _GLOBAL_POP = 0xA, 0xB
_LOCAL_USAGE, _LOCAL_USAGE_MIN, _LOCAL_USAGE_MAX = 0x0, 0x1, 0x2
_INPUT_CONSTANT, _INPUT_VARIABLE = 0x01, 0x02
_LONG_ITEM_PREFIX = 0xFE
_MAX_USAGE_RANGE = 4096  # Guard against absurd usage ranges in broken descriptors


@dataclass(frozen=True, slots=True)
class AxisField:
    """Location and range of one axis inside a device's input reports.

    Attributes:
        report_id: Report ID, or 0 if the device does not use numbered reports.
        bit_offset: Offset of the value from the start of the report payload
            (i.e. after the report ID byte, if any).
        bit_size: Number of bits the value occupies.
        logical_min: Smallest value the device reports (negative = signed field).
        logical_max: Largest value the device reports.
        usage_page: HID usage page (0 for fields guessed without a descriptor).
        usage: HID usage within the page.
        label: Optional display name overriding the usage name.
    """

    report_id: int
    bit_offset: int
    bit_size: int
    logical_min: int
    logical_max: int
    usage_page: int = _PAGE_GENERIC_DESKTOP
    usage: int = 0
    label: str = ""

    @property
    def name(self) -> str:
        """Human-readable axis name, e.g. 'Rz' or 'Brake'."""
        if self.label:
            return self.label
        return _AXIS_NAMES.get((self.usage_page, self.usage), f"Axis {self.usage:#04x}")

    @property
    def span(self) -> int:
        """Size of the logical range (never 0)."""
        return max(1, self.logical_max - self.logical_min)

    def read(self, report: Sequence[int] | None) -> int | None:
        """Extract this field's raw value from a report as returned by hidapi.

        hidapi returns numbered reports with the report ID as the first byte and
        unnumbered reports without it.

        Returns:
            The (sign-extended) value, or None if the report doesn't contain it.
        """
        if not report:
            return None
        start = self.bit_offset
        if self.report_id:
            if report[0] != self.report_id:
                return None
            start += 8
        end = start + self.bit_size
        if end > len(report) * 8:
            return None
        chunk = int.from_bytes(bytes(report[start // 8:(end + 7) // 8]), "little")
        value = (chunk >> (start % 8)) & ((1 << self.bit_size) - 1)
        if self.logical_min < 0 and value & (1 << (self.bit_size - 1)):
            value -= 1 << self.bit_size
        return value

    def normalized(self, raw: int) -> float:
        """Map a raw value to 0..1 across the logical range."""
        return (raw - self.logical_min) / self.span


@dataclass
class _GlobalState:
    usage_page: int = 0
    logical_min: int = 0
    logical_max: int = 0
    logical_max_unsigned: int = 0
    report_size: int = 0
    report_count: int = 0
    report_id: int = 0


def _unsigned(data: bytes) -> int:
    return int.from_bytes(data, "little") if data else 0


def _signed(data: bytes) -> int:
    return int.from_bytes(data, "little", signed=True) if data else 0


def _iter_items(descriptor: bytes):
    """Yield (item_type, tag, data) for every short item in the descriptor."""
    i = 0
    while i < len(descriptor):
        prefix = descriptor[i]
        if prefix == _LONG_ITEM_PREFIX:  # Long items carry no axis data; skip them.
            size = descriptor[i + 1] if i + 1 < len(descriptor) else 0
            i += 3 + size
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        data = descriptor[i + 1:i + 1 + size]
        yield (prefix >> 2) & 0x03, prefix >> 4, data
        i += 1 + size


def parse_input_axes(descriptor: Sequence[int]) -> list[AxisField]:
    """Return every axis-like Input field declared in a HID report descriptor.

    Args:
        descriptor: Raw report descriptor bytes (e.g. from
            ``hid.device().get_report_descriptor()``).

    Returns:
        Axis fields in descriptor order.
    """
    state = _GlobalState()
    stack: list[_GlobalState] = []
    usages: list[tuple[int, int]] = []
    usage_min: tuple[int, int] | None = None
    offsets: dict[int, int] = {}  # Next free bit per report ID
    axes: list[AxisField] = []

    def full_usage(data: bytes) -> tuple[int, int]:
        # A 4-byte usage carries its own page in the high 16 bits.
        value = _unsigned(data)
        if len(data) == 4:
            return value >> 16, value & 0xFFFF
        return state.usage_page, value

    for item_type, tag, data in _iter_items(bytes(descriptor)):
        if item_type == _TYPE_GLOBAL:
            if tag == _GLOBAL_USAGE_PAGE:
                state.usage_page = _unsigned(data)
            elif tag == _GLOBAL_LOGICAL_MIN:
                state.logical_min = _signed(data)
            elif tag == _GLOBAL_LOGICAL_MAX:
                state.logical_max = _signed(data)
                state.logical_max_unsigned = _unsigned(data)
            elif tag == _GLOBAL_REPORT_SIZE:
                state.report_size = _unsigned(data)
            elif tag == _GLOBAL_REPORT_COUNT:
                state.report_count = _unsigned(data)
            elif tag == _GLOBAL_REPORT_ID:
                state.report_id = _unsigned(data)
            elif tag == _GLOBAL_PUSH:
                stack.append(replace(state))
            elif tag == _GLOBAL_POP and stack:
                state = stack.pop()
        elif item_type == _TYPE_LOCAL:
            if tag == _LOCAL_USAGE:
                usages.append(full_usage(data))
            elif tag == _LOCAL_USAGE_MIN:
                usage_min = full_usage(data)
            elif tag == _LOCAL_USAGE_MAX and usage_min is not None:
                page, last = full_usage(data)
                first = usage_min[1]
                if 0 <= last - first < _MAX_USAGE_RANGE:
                    usages.extend((page, u) for u in range(first, last + 1))
                usage_min = None
        elif item_type == _TYPE_MAIN:
            if tag == _MAIN_INPUT:
                axes.extend(_input_fields(state, usages, _unsigned(data), offsets))
            usages = []  # Local items only apply to the next main item.
            usage_min = None
    return axes


def _input_fields(
    state: _GlobalState, usages: list[tuple[int, int]], flags: int, offsets: dict[int, int]
) -> list[AxisField]:
    """Build axis fields for one Input item and advance the report's bit offset."""
    offset = offsets.get(state.report_id, 0)
    size, count = state.report_size, state.report_count
    offsets[state.report_id] = offset + size * count

    if flags & _INPUT_CONSTANT or not flags & _INPUT_VARIABLE or not usages or size < 8:
        return []  # Padding, arrays (buttons/keys) and bit fields are not axes.

    logical_min, logical_max = state.logical_min, state.logical_max
    if logical_max < logical_min:
        # Common quirk: "Logical Maximum (255)" encoded as the single byte 0xFF (= -1).
        logical_max = state.logical_max_unsigned

    fields = []
    for i in range(count):
        page, usage = usages[min(i, len(usages) - 1)]
        if (page, usage) not in _AXIS_NAMES and page != _PAGE_SIMULATION:
            continue
        fields.append(
            AxisField(
                report_id=state.report_id,
                bit_offset=offset + i * size,
                bit_size=size,
                logical_min=logical_min,
                logical_max=logical_max,
                usage_page=page,
                usage=usage,
            )
        )
    return fields


def guess_axes(report_len: int, report_id: int = 0) -> list[AxisField]:
    """Fallback for devices without a readable descriptor.

    Every byte (8-bit) and every byte pair (16-bit little-endian) is offered as
    a candidate axis; movement-based detection then picks the right one.
    """
    fields = []
    payload_bits = (report_len - (1 if report_id else 0)) * 8
    for byte in range(payload_bits // 8):
        fields.append(AxisField(report_id, byte * 8, 8, 0, 0xFF, 0, 0, f"Byte {byte}"))
        if (byte + 2) * 8 <= payload_bits:
            fields.append(
                AxisField(report_id, byte * 8, 16, 0, 0xFFFF, 0, 0, f"Bytes {byte}-{byte + 1}")
            )
    return fields
