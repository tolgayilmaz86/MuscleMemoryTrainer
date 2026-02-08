"""Known device presets for popular sim racing hardware.

This module provides pre-configured byte offsets and parameters for
common wheels and pedals, eliminating the need for manual calibration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class DeviceId(NamedTuple):
    """Unique identifier for a HID device."""

    vendor_id: int
    product_id: int


@dataclass(frozen=True, slots=True)
class WheelPreset:
    """Pre-configured settings for a known wheel."""

    name: str
    vendor_id: int
    product_id: int
    steering_offset: int
    steering_bits: int = 8
    report_len: int = 64


@dataclass(frozen=True, slots=True)
class PedalsPreset:
    """Pre-configured settings for known pedals."""

    name: str
    vendor_id: int
    product_id: int
    throttle_offset: int
    brake_offset: int
    clutch_offset: int | None = None
    report_len: int = 64


# ---------------------------------------------------------------------------
# Known Wheel Presets
# ---------------------------------------------------------------------------
# Vendor IDs:
#   Logitech: 0x046D
#   Fanatec: 0x0EB7
#   Thrustmaster: 0x044F
#   Simagic: 0x0483 (STMicroelectronics - used by many Chinese manufacturers)
#   MOZA: 0x346E
#   Cammus: 0x3416
#   Simucube: 0x16D0 (MCS Electronics)
#   VNM: 0x0483 (STMicroelectronics - shared VID)
#   Asetek: 0x2433
#   VRS DirectForce Pro: 0x0483

WHEEL_PRESETS: dict[DeviceId, WheelPreset] = {
    # Logitech wheels
    DeviceId(0x046D, 0xC24F): WheelPreset(
        name="Logitech G29",
        vendor_id=0x046D,
        product_id=0xC24F,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC260): WheelPreset(
        name="Logitech G29 (PS Mode)",
        vendor_id=0x046D,
        product_id=0xC260,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC262): WheelPreset(
        name="Logitech G920",
        vendor_id=0x046D,
        product_id=0xC262,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC266): WheelPreset(
        name="Logitech G923 (PS)",
        vendor_id=0x046D,
        product_id=0xC266,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC267): WheelPreset(
        name="Logitech G923 (Xbox)",
        vendor_id=0x046D,
        product_id=0xC267,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC294): WheelPreset(
        name="Logitech Driving Force Pro",
        vendor_id=0x046D,
        product_id=0xC294,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC295): WheelPreset(
        name="Logitech Momo Force",
        vendor_id=0x046D,
        product_id=0xC295,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC298): WheelPreset(
        name="Logitech Driving Force GT",
        vendor_id=0x046D,
        product_id=0xC298,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC299): WheelPreset(
        name="Logitech G25",
        vendor_id=0x046D,
        product_id=0xC299,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC29A): WheelPreset(
        name="Logitech Driving Force GT (PS3)",
        vendor_id=0x046D,
        product_id=0xC29A,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC29B): WheelPreset(
        name="Logitech G27",
        vendor_id=0x046D,
        product_id=0xC29B,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC29C): WheelPreset(
        name="Logitech Speed Force Wireless",
        vendor_id=0x046D,
        product_id=0xC29C,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x046D, 0xCA03): WheelPreset(
        name="Logitech G Pro Racing Wheel",
        vendor_id=0x046D,
        product_id=0xCA03,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    # Thrustmaster wheels
    DeviceId(0x044F, 0xB651): WheelPreset(
        name="Thrustmaster T150",
        vendor_id=0x044F,
        product_id=0xB651,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x044F, 0xB653): WheelPreset(
        name="Thrustmaster T150 (PS Mode)",
        vendor_id=0x044F,
        product_id=0xB653,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x044F, 0xB654): WheelPreset(
        name="Thrustmaster TX",
        vendor_id=0x044F,
        product_id=0xB654,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x044F, 0xB65D): WheelPreset(
        name="Thrustmaster T300RS",
        vendor_id=0x044F,
        product_id=0xB65D,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x044F, 0xB65E): WheelPreset(
        name="Thrustmaster T300RS GT Edition",
        vendor_id=0x044F,
        product_id=0xB65E,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x044F, 0xB664): WheelPreset(
        name="Thrustmaster T-GT",
        vendor_id=0x044F,
        product_id=0xB664,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x044F, 0xB669): WheelPreset(
        name="Thrustmaster T-GT II",
        vendor_id=0x044F,
        product_id=0xB669,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x044F, 0xB66E): WheelPreset(
        name="Thrustmaster T248",
        vendor_id=0x044F,
        product_id=0xB66E,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x044F, 0xB66F): WheelPreset(
        name="Thrustmaster T248 (Xbox)",
        vendor_id=0x044F,
        product_id=0xB66F,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x044F, 0xB675): WheelPreset(
        name="Thrustmaster T818",
        vendor_id=0x044F,
        product_id=0xB675,
        steering_offset=4,
        steering_bits=16,
        report_len=64,
    ),
    # Fanatec wheels/bases
    DeviceId(0x0EB7, 0x0001): WheelPreset(
        name="Fanatec Wheel (Generic)",
        vendor_id=0x0EB7,
        product_id=0x0001,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x0EB7, 0x0004): WheelPreset(
        name="Fanatec ClubSport Wheel Base",
        vendor_id=0x0EB7,
        product_id=0x0004,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x0EB7, 0x0005): WheelPreset(
        name="Fanatec ClubSport Wheel Base V2",
        vendor_id=0x0EB7,
        product_id=0x0005,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x0EB7, 0x0006): WheelPreset(
        name="Fanatec CSL Elite",
        vendor_id=0x0EB7,
        product_id=0x0006,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x0EB7, 0x0011): WheelPreset(
        name="Fanatec Podium DD1/DD2",
        vendor_id=0x0EB7,
        product_id=0x0011,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x0EB7, 0x0020): WheelPreset(
        name="Fanatec CSL DD",
        vendor_id=0x0EB7,
        product_id=0x0020,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x0EB7, 0x0E03): WheelPreset(
        name="Fanatec CSL Elite PS4",
        vendor_id=0x0EB7,
        product_id=0x0E03,
        steering_offset=2,
        steering_bits=16,
        report_len=64,
    ),
    # MOZA wheels
    DeviceId(0x346E, 0x0001): WheelPreset(
        name="MOZA R9",
        vendor_id=0x346E,
        product_id=0x0001,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x346E, 0x0002): WheelPreset(
        name="MOZA R5",
        vendor_id=0x346E,
        product_id=0x0002,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x346E, 0x0003): WheelPreset(
        name="MOZA R12",
        vendor_id=0x346E,
        product_id=0x0003,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x346E, 0x0004): WheelPreset(
        name="MOZA R16",
        vendor_id=0x346E,
        product_id=0x0004,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x346E, 0x0005): WheelPreset(
        name="MOZA R21",
        vendor_id=0x346E,
        product_id=0x0005,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    # Simagic wheels
    DeviceId(0x0483, 0x0522): WheelPreset(
        name="Simagic Alpha",
        vendor_id=0x0483,
        product_id=0x0522,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x0483, 0x0528): WheelPreset(
        name="Simagic Alpha Mini",
        vendor_id=0x0483,
        product_id=0x0528,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x0483, 0x052A): WheelPreset(
        name="Simagic Alpha Ultimate",
        vendor_id=0x0483,
        product_id=0x052A,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    # Cammus wheels
    DeviceId(0x3416, 0x0301): WheelPreset(
        name="Cammus C5",
        vendor_id=0x3416,
        product_id=0x0301,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x3416, 0x0302): WheelPreset(
        name="Cammus C12",
        vendor_id=0x3416,
        product_id=0x0302,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    # Simucube wheels
    # Vendor ID: 0x16D0 (MCS Electronics)
    DeviceId(0x16D0, 0x0D5A): WheelPreset(
        name="Simucube 1",
        vendor_id=0x16D0,
        product_id=0x0D5A,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x16D0, 0x0D5F): WheelPreset(
        name="Simucube 2 Ultimate",
        vendor_id=0x16D0,
        product_id=0x0D5F,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x16D0, 0x0D60): WheelPreset(
        name="Simucube 2 Pro",
        vendor_id=0x16D0,
        product_id=0x0D60,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    DeviceId(0x16D0, 0x0D61): WheelPreset(
        name="Simucube 2 Sport",
        vendor_id=0x16D0,
        product_id=0x0D61,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
    # VNM Simulation wheels
    # VNM typically uses STM32 VID (0x0483) with custom PIDs
    DeviceId(0x0483, 0x5750): WheelPreset(
        name="VNM Simulation Wheel",
        vendor_id=0x0483,
        product_id=0x5750,
        steering_offset=0,
        steering_bits=16,
        report_len=64,
    ),
}


# ---------------------------------------------------------------------------
# Known Pedals Presets
# ---------------------------------------------------------------------------

PEDALS_PRESETS: dict[DeviceId, PedalsPreset] = {
    # Logitech pedals (usually part of wheel, but can be separate)
    DeviceId(0x046D, 0xC24F): PedalsPreset(
        name="Logitech G29 Pedals",
        vendor_id=0x046D,
        product_id=0xC24F,
        throttle_offset=6,
        brake_offset=7,
        clutch_offset=8,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC262): PedalsPreset(
        name="Logitech G920 Pedals",
        vendor_id=0x046D,
        product_id=0xC262,
        throttle_offset=6,
        brake_offset=7,
        clutch_offset=8,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC266): PedalsPreset(
        name="Logitech G923 Pedals (PS)",
        vendor_id=0x046D,
        product_id=0xC266,
        throttle_offset=6,
        brake_offset=7,
        clutch_offset=8,
        report_len=64,
    ),
    DeviceId(0x046D, 0xC267): PedalsPreset(
        name="Logitech G923 Pedals (Xbox)",
        vendor_id=0x046D,
        product_id=0xC267,
        throttle_offset=6,
        brake_offset=7,
        clutch_offset=8,
        report_len=64,
    ),
    DeviceId(0x046D, 0xCA04): PedalsPreset(
        name="Logitech G Pro Pedals",
        vendor_id=0x046D,
        product_id=0xCA04,
        throttle_offset=2,
        brake_offset=4,
        clutch_offset=6,
        report_len=64,
    ),
    # Fanatec pedals
    DeviceId(0x0EB7, 0x183B): PedalsPreset(
        name="Fanatec ClubSport Pedals V3",
        vendor_id=0x0EB7,
        product_id=0x183B,
        throttle_offset=2,
        brake_offset=4,
        clutch_offset=6,
        report_len=64,
    ),
    DeviceId(0x0EB7, 0x0001): PedalsPreset(
        name="Fanatec CSL Pedals",
        vendor_id=0x0EB7,
        product_id=0x0001,
        throttle_offset=2,
        brake_offset=4,
        clutch_offset=None,
        report_len=64,
    ),
    # Thrustmaster pedals
    DeviceId(0x044F, 0xB653): PedalsPreset(
        name="Thrustmaster T3PA",
        vendor_id=0x044F,
        product_id=0xB653,
        throttle_offset=6,
        brake_offset=7,
        clutch_offset=8,
        report_len=64,
    ),
    DeviceId(0x044F, 0xB65A): PedalsPreset(
        name="Thrustmaster T-LCM",
        vendor_id=0x044F,
        product_id=0xB65A,
        throttle_offset=2,
        brake_offset=4,
        clutch_offset=6,
        report_len=64,
    ),
    # MOZA pedals
    DeviceId(0x346E, 0x0010): PedalsPreset(
        name="MOZA CRP Pedals",
        vendor_id=0x346E,
        product_id=0x0010,
        throttle_offset=2,
        brake_offset=4,
        clutch_offset=6,
        report_len=64,
    ),
    DeviceId(0x346E, 0x0011): PedalsPreset(
        name="MOZA SR-P Pedals",
        vendor_id=0x346E,
        product_id=0x0011,
        throttle_offset=2,
        brake_offset=4,
        clutch_offset=6,
        report_len=64,
    ),
    # Heusinkveld pedals
    DeviceId(0x30B7, 0x1001): PedalsPreset(
        name="Heusinkveld Sprint",
        vendor_id=0x30B7,
        product_id=0x1001,
        throttle_offset=1,
        brake_offset=3,
        clutch_offset=5,
        report_len=64,
    ),
    DeviceId(0x30B7, 0x1002): PedalsPreset(
        name="Heusinkveld Ultimate",
        vendor_id=0x30B7,
        product_id=0x1002,
        throttle_offset=1,
        brake_offset=3,
        clutch_offset=5,
        report_len=64,
    ),
    # VNM Simulation pedals
    # VNM typically uses STM32 VID (0x0483) with custom PIDs
    DeviceId(0x0483, 0x5751): PedalsPreset(
        name="VNM Simulation Pedals",
        vendor_id=0x0483,
        product_id=0x5751,
        throttle_offset=1,
        brake_offset=3,
        clutch_offset=5,
        report_len=64,
    ),
    # Asetek SimSports pedals
    # Vendor ID: 0x2433
    DeviceId(0x2433, 0xF100): PedalsPreset(
        name="Asetek Invicta Pedals",
        vendor_id=0x2433,
        product_id=0xF100,
        throttle_offset=2,
        brake_offset=4,
        clutch_offset=6,
        report_len=64,
    ),
    DeviceId(0x2433, 0xF101): PedalsPreset(
        name="Asetek Forte Pedals",
        vendor_id=0x2433,
        product_id=0xF101,
        throttle_offset=2,
        brake_offset=4,
        clutch_offset=6,
        report_len=64,
    ),
    DeviceId(0x2433, 0xF102): PedalsPreset(
        name="Asetek La Prima Pedals",
        vendor_id=0x2433,
        product_id=0xF102,
        throttle_offset=2,
        brake_offset=4,
        clutch_offset=None,
        report_len=64,
    ),
    # MOZA MBooster pedals
    DeviceId(0x346E, 0x0012): PedalsPreset(
        name="MOZA MBooster Pedals",
        vendor_id=0x346E,
        product_id=0x0012,
        throttle_offset=2,
        brake_offset=4,
        clutch_offset=6,
        report_len=64,
    ),
}


# ---------------------------------------------------------------------------
# Lookup functions
# ---------------------------------------------------------------------------

def find_wheel_preset(vendor_id: int, product_id: int) -> WheelPreset | None:
    """Look up a wheel preset by vendor and product ID.

    Args:
        vendor_id: USB vendor ID.
        product_id: USB product ID.

    Returns:
        The matching WheelPreset, or None if not found.
    """
    return WHEEL_PRESETS.get(DeviceId(vendor_id, product_id))


def find_pedals_preset(vendor_id: int, product_id: int) -> PedalsPreset | None:
    """Look up a pedals preset by vendor and product ID.

    Args:
        vendor_id: USB vendor ID.
        product_id: USB product ID.

    Returns:
        The matching PedalsPreset, or None if not found.
    """
    return PEDALS_PRESETS.get(DeviceId(vendor_id, product_id))


def get_all_wheel_presets() -> list[WheelPreset]:
    """Return all known wheel presets.

    Returns:
        List of all WheelPreset objects.
    """
    return list(WHEEL_PRESETS.values())


def get_all_pedals_presets() -> list[PedalsPreset]:
    """Return all known pedals presets.

    Returns:
        List of all PedalsPreset objects.
    """
    return list(PEDALS_PRESETS.values())
