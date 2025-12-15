from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

try:
    import hid
except ImportError:
    hid = None


@dataclass(frozen=True, slots=True)
class HidDeviceId:
    vendor_id: int
    product_id: int


@dataclass(frozen=True, slots=True)
class HidDeviceInfo:
    """Minimal HID device info needed for selection/opening."""

    device_id: HidDeviceId
    product_string: str
    path: Any  # hidapi uses an opaque bytes-ish path on Windows


def hid_available() -> bool:
    return hid is not None


def enumerate_devices() -> list[HidDeviceInfo]:
    """Return a filtered list of HID devices with a product name."""
    if hid is None:
        return []
    devices = []
    for d in hid.enumerate():
        product = (d.get("product_string") or "").strip()
        if not product:
            continue
        vendor_id = int(d.get("vendor_id") or 0)
        product_id = int(d.get("product_id") or 0)
        path = d.get("path")
        devices.append(
            HidDeviceInfo(
                device_id=HidDeviceId(vendor_id=vendor_id, product_id=product_id),
                product_string=product,
                path=path,
            )
        )
    return devices


class HidSession:
    """Manage a single opened HID device."""

    def __init__(self) -> None:
        self._handle = None

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    def open(self, device: HidDeviceInfo) -> None:
        if hid is None:
            raise RuntimeError("hidapi is not installed")
        self.close()
        handle = hid.device()
        if device.path:
            handle.open_path(device.path)
        else:
            handle.open(device.device_id.vendor_id, device.device_id.product_id)
        handle.set_nonblocking(True)
        self._handle = handle

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.close()
        finally:
            self._handle = None

    def read_latest_report(self, *, report_len: int, max_reads: int = 50) -> Optional[list[int]]:
        """Drain the read queue and return the most recent report (or None)."""
        if self._handle is None:
            return None
        latest: Optional[list[int]] = None
        for _ in range(max_reads):
            data = self._handle.read(int(report_len), timeout_ms=0)
            if not data:
                break
            latest = data
        return latest

    def read_report(self, *, report_len: int, timeout_ms: int = 50) -> Optional[list[int]]:
        """Read a single report with optional blocking timeout.
        
        Use this for devices that only send reports on input change.
        
        Args:
            report_len: Expected report length in bytes.
            timeout_ms: Timeout in milliseconds (0 = non-blocking).
            
        Returns:
            Report data or None if no data available.
        """
        if self._handle is None:
            return None
        data = self._handle.read(int(report_len), timeout_ms=timeout_ms)
        return data if data else None

