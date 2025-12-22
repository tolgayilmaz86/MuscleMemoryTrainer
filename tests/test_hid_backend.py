"""Tests for HID backend device enumeration and filtering."""

from __future__ import annotations

import pytest

from mmt_app.input.hid_backend import (
    HidDeviceId,
    HidDeviceInfo,
    enumerate_devices,
    _FILTERED_DEVICE_NAMES,
)


class TestEnumerateDevicesFiltering:
    """Tests for device filtering in enumerate_devices."""

    def test_filters_usb_receiver(self, monkeypatch) -> None:
        """Test that 'USB Receiver' devices are filtered out."""
        fake_devices = [
            {"product_string": "USB Receiver", "vendor_id": 0x046d, "product_id": 0xc52b, "path": b"path1"},
            {"product_string": "Fanatec ClubSport Pedals", "vendor_id": 0x0eb7, "product_id": 0x0001, "path": b"path2"},
        ]
        monkeypatch.setattr("mmt_app.input.hid_backend.hid.enumerate", lambda: fake_devices)

        devices = enumerate_devices()

        assert len(devices) == 1
        assert devices[0].product_string == "Fanatec ClubSport Pedals"

    def test_filters_wireless_receiver(self, monkeypatch) -> None:
        """Test that 'Wireless Receiver' devices are filtered out."""
        fake_devices = [
            {"product_string": "Wireless Receiver", "vendor_id": 0x046d, "product_id": 0xc534, "path": b"path1"},
            {"product_string": "Logitech G29 Racing Wheel", "vendor_id": 0x046d, "product_id": 0xc24f, "path": b"path2"},
        ]
        monkeypatch.setattr("mmt_app.input.hid_backend.hid.enumerate", lambda: fake_devices)

        devices = enumerate_devices()

        assert len(devices) == 1
        assert devices[0].product_string == "Logitech G29 Racing Wheel"

    def test_filters_nano_receiver(self, monkeypatch) -> None:
        """Test that 'Nano Receiver' devices are filtered out."""
        fake_devices = [
            {"product_string": "Nano Receiver", "vendor_id": 0x046d, "product_id": 0xc52f, "path": b"path1"},
        ]
        monkeypatch.setattr("mmt_app.input.hid_backend.hid.enumerate", lambda: fake_devices)

        devices = enumerate_devices()

        assert len(devices) == 0

    def test_filters_unifying_receiver(self, monkeypatch) -> None:
        """Test that 'Unifying Receiver' devices are filtered out."""
        fake_devices = [
            {"product_string": "Unifying Receiver", "vendor_id": 0x046d, "product_id": 0xc52b, "path": b"path1"},
        ]
        monkeypatch.setattr("mmt_app.input.hid_backend.hid.enumerate", lambda: fake_devices)

        devices = enumerate_devices()

        assert len(devices) == 0

    def test_filter_is_case_insensitive(self, monkeypatch) -> None:
        """Test that filtering works regardless of case."""
        fake_devices = [
            {"product_string": "USB RECEIVER", "vendor_id": 0x046d, "product_id": 0xc52b, "path": b"path1"},
            {"product_string": "usb receiver", "vendor_id": 0x046d, "product_id": 0xc52c, "path": b"path2"},
            {"product_string": "Usb Receiver", "vendor_id": 0x046d, "product_id": 0xc52d, "path": b"path3"},
            {"product_string": "Valid Device", "vendor_id": 0x0eb7, "product_id": 0x0001, "path": b"path4"},
        ]
        monkeypatch.setattr("mmt_app.input.hid_backend.hid.enumerate", lambda: fake_devices)

        devices = enumerate_devices()

        assert len(devices) == 1
        assert devices[0].product_string == "Valid Device"

    def test_filters_multiple_receivers(self, monkeypatch) -> None:
        """Test that multiple receiver devices are all filtered out."""
        fake_devices = [
            {"product_string": "USB Receiver", "vendor_id": 0x046d, "product_id": 0xc52b, "path": b"path1"},
            {"product_string": "USB Receiver", "vendor_id": 0x046d, "product_id": 0xc52c, "path": b"path2"},
            {"product_string": "Wireless Receiver", "vendor_id": 0x046d, "product_id": 0xc534, "path": b"path3"},
            {"product_string": "Nano Receiver", "vendor_id": 0x046d, "product_id": 0xc52f, "path": b"path4"},
            {"product_string": "Thrustmaster T300", "vendor_id": 0x044f, "product_id": 0xb66e, "path": b"path5"},
        ]
        monkeypatch.setattr("mmt_app.input.hid_backend.hid.enumerate", lambda: fake_devices)

        devices = enumerate_devices()

        assert len(devices) == 1
        assert devices[0].product_string == "Thrustmaster T300"

    def test_does_not_filter_partial_match(self, monkeypatch) -> None:
        """Test that devices containing 'Receiver' but not exact match are kept."""
        fake_devices = [
            {"product_string": "Logitech USB Receiver Pro", "vendor_id": 0x046d, "product_id": 0xc52b, "path": b"path1"},
            {"product_string": "My Receiver Device", "vendor_id": 0x046d, "product_id": 0xc52c, "path": b"path2"},
        ]
        monkeypatch.setattr("mmt_app.input.hid_backend.hid.enumerate", lambda: fake_devices)

        devices = enumerate_devices()

        assert len(devices) == 2

    def test_filters_empty_product_string(self, monkeypatch) -> None:
        """Test that devices with empty product string are filtered out."""
        fake_devices = [
            {"product_string": "", "vendor_id": 0x046d, "product_id": 0xc52b, "path": b"path1"},
            {"product_string": "   ", "vendor_id": 0x046d, "product_id": 0xc52c, "path": b"path2"},
            {"product_string": None, "vendor_id": 0x046d, "product_id": 0xc52d, "path": b"path3"},
            {"product_string": "Valid Device", "vendor_id": 0x0eb7, "product_id": 0x0001, "path": b"path4"},
        ]
        monkeypatch.setattr("mmt_app.input.hid_backend.hid.enumerate", lambda: fake_devices)

        devices = enumerate_devices()

        assert len(devices) == 1
        assert devices[0].product_string == "Valid Device"


class TestFilteredDeviceNames:
    """Tests for the filtered device names constant."""

    def test_filtered_names_are_lowercase(self) -> None:
        """Test that all filtered names are stored in lowercase."""
        for name in _FILTERED_DEVICE_NAMES:
            assert name == name.lower(), f"'{name}' should be lowercase"

    def test_contains_expected_receivers(self) -> None:
        """Test that common receiver names are in the filter list."""
        expected = {"usb receiver", "wireless receiver", "nano receiver", "unifying receiver"}
        assert expected.issubset(_FILTERED_DEVICE_NAMES)
