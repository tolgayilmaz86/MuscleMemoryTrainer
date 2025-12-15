"""Device management for HID input devices.

This module provides high-level device management including session handling
for pedals and wheel devices, separated from UI concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mmt_app.input.hid_backend import HidSession, HidDeviceInfo, enumerate_devices, hid_available
from mmt_app.config import (
    DEFAULT_PEDALS_REPORT_LEN,
    DEFAULT_WHEEL_REPORT_LEN,
    DEFAULT_THROTTLE_OFFSET,
    DEFAULT_BRAKE_OFFSET,
    DEFAULT_STEERING_OFFSET,
    DEFAULT_STEERING_CENTER,
    DEFAULT_STEERING_RANGE,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Device Manager
# ---------------------------------------------------------------------------

@dataclass
class DeviceConfig:
    """Configuration for a single device."""
    report_len: int
    offsets: dict[str, int]


class DeviceManager:
    """Manages HID device sessions for pedals and wheel.
    
    This class encapsulates device enumeration, connection management,
    and report reading for racing sim input devices.
    """

    def __init__(self) -> None:
        """Initialize the device manager."""
        self._devices: list[HidDeviceInfo] = []
        self._pedals_device: HidDeviceInfo | None = None
        self._wheel_device: HidDeviceInfo | None = None
        self._pedals_session = HidSession()
        self._wheel_session = HidSession()
        
        # Configuration
        self._pedals_report_len = DEFAULT_PEDALS_REPORT_LEN
        self._wheel_report_len = DEFAULT_WHEEL_REPORT_LEN
        self._throttle_offset = DEFAULT_THROTTLE_OFFSET
        self._brake_offset = DEFAULT_BRAKE_OFFSET
        self._steering_offset = DEFAULT_STEERING_OFFSET
        self._steering_center = DEFAULT_STEERING_CENTER
        self._steering_range = DEFAULT_STEERING_RANGE

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def pedals_session(self) -> HidSession:
        """Return the pedals HID session."""
        return self._pedals_session

    @property
    def wheel_session(self) -> HidSession:
        """Return the wheel HID session."""
        return self._wheel_session

    @property
    def pedals_device(self) -> HidDeviceInfo | None:
        """Return the selected pedals device."""
        return self._pedals_device

    @property
    def wheel_device(self) -> HidDeviceInfo | None:
        """Return the selected wheel device."""
        return self._wheel_device

    @property
    def devices(self) -> list[HidDeviceInfo]:
        """Return the list of enumerated devices."""
        return self._devices

    @property
    def pedals_report_len(self) -> int:
        """Return configured pedals report length."""
        return self._pedals_report_len

    @pedals_report_len.setter
    def pedals_report_len(self, value: int) -> None:
        """Set pedals report length."""
        self._pedals_report_len = value

    @property
    def wheel_report_len(self) -> int:
        """Return configured wheel report length."""
        return self._wheel_report_len

    @wheel_report_len.setter
    def wheel_report_len(self, value: int) -> None:
        """Set wheel report length."""
        self._wheel_report_len = value

    @property
    def throttle_offset(self) -> int:
        """Return configured throttle offset."""
        return self._throttle_offset

    @throttle_offset.setter
    def throttle_offset(self, value: int) -> None:
        """Set throttle offset."""
        self._throttle_offset = value

    @property
    def brake_offset(self) -> int:
        """Return configured brake offset."""
        return self._brake_offset

    @brake_offset.setter
    def brake_offset(self, value: int) -> None:
        """Set brake offset."""
        self._brake_offset = value

    @property
    def steering_offset(self) -> int:
        """Return configured steering offset."""
        return self._steering_offset

    @steering_offset.setter
    def steering_offset(self, value: int) -> None:
        """Set steering offset."""
        self._steering_offset = value

    @property
    def steering_center(self) -> int:
        """Return configured steering center."""
        return self._steering_center

    @steering_center.setter
    def steering_center(self, value: int) -> None:
        """Set steering center."""
        self._steering_center = value

    @property
    def steering_range(self) -> int:
        """Return configured steering range in degrees."""
        return self._steering_range

    @steering_range.setter
    def steering_range(self, value: int) -> None:
        """Set steering range in degrees."""
        self._steering_range = value

    # -------------------------------------------------------------------------
    # Device operations
    # -------------------------------------------------------------------------

    def refresh_devices(self) -> list[HidDeviceInfo]:
        """Refresh and return the list of available HID devices.
        
        Returns:
            List of available HID devices.
        """
        if not hid_available():
            self._devices = []
            return []
        
        self._devices = enumerate_devices()
        return self._devices

    def select_pedals(self, device: HidDeviceInfo | None) -> None:
        """Select a pedals device.
        
        Args:
            device: The device to select, or None to clear selection.
        """
        self._pedals_device = device

    def select_wheel(self, device: HidDeviceInfo | None) -> None:
        """Select a wheel device.
        
        Args:
            device: The device to select, or None to clear selection.
        """
        self._wheel_device = device

    def connect_pedals(self) -> bool:
        """Open connection to selected pedals device.
        
        Returns:
            True if connection successful, False otherwise.
        """
        if self._pedals_device is None:
            return False
        
        try:
            self._pedals_session.open(self._pedals_device)
            return True
        except Exception:
            return False

    def connect_wheel(self) -> bool:
        """Open connection to selected wheel device.
        
        Returns:
            True if connection successful, False otherwise.
        """
        if self._wheel_device is None:
            return False
        
        try:
            self._wheel_session.open(self._wheel_device)
            return True
        except Exception:
            return False

    def disconnect_all(self) -> None:
        """Close all device connections."""
        self._pedals_session.close()
        self._wheel_session.close()

    def read_pedals_report(self, max_reads: int = 50) -> list[int] | None:
        """Read the latest report from pedals device.
        
        Args:
            max_reads: Maximum reads to drain buffer.
            
        Returns:
            The latest report data, or None if unavailable.
        """
        if not self._pedals_session.is_open:
            return None
        return self._pedals_session.read_latest_report(
            report_len=self._pedals_report_len,
            max_reads=max_reads,
        )

    def read_wheel_report(self, max_reads: int = 50) -> list[int] | None:
        """Read the latest report from wheel device.
        
        Args:
            max_reads: Maximum reads to drain buffer.
            
        Returns:
            The latest report data, or None if unavailable.
        """
        if not self._wheel_session.is_open:
            return None
        return self._wheel_session.read_latest_report(
            report_len=self._wheel_report_len,
            max_reads=max_reads,
        )

    def find_device_by_vid_pid(self, vendor_id: int, product_id: int) -> HidDeviceInfo | None:
        """Find a device by vendor and product ID.
        
        Args:
            vendor_id: USB vendor ID.
            product_id: USB product ID.
            
        Returns:
            The matching device, or None if not found.
        """
        for device in self._devices:
            if (device.device_id.vendor_id == vendor_id and 
                device.device_id.product_id == product_id):
                return device
        return None


def format_device_label(device: HidDeviceInfo) -> str:
    """Format a device for display in UI.
    
    Args:
        device: The device to format.
        
    Returns:
        Formatted string for display.
    """
    vid = device.device_id.vendor_id
    pid = device.device_id.product_id
    return f"{device.product_string} ({vid:04X}:{pid:04X})"
