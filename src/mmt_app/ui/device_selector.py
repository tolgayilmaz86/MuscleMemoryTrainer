"""Device selector widget for HID device selection and connection.

Provides UI controls for selecting and connecting to pedals and wheel devices.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

from mmt_app.input.hid_backend import (
    HidSession,
    HidDeviceInfo,
    hid_available,
    enumerate_devices,
)


class DeviceSelector(QGroupBox):
    """Widget for selecting and connecting HID devices.

    Provides controls for:
    - Pedals device selection
    - Wheel device selection
    - Refresh device list
    - Connect to selected devices
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_status_update: Callable[[str], None] | None = None,
        on_devices_connected: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the device selector.

        Args:
            parent: Parent widget.
            on_status_update: Callback invoked with status messages.
            on_devices_connected: Callback invoked after sessions are (re)opened.
        """
        super().__init__("Device Selection", parent)

        self._on_status_update = on_status_update or (lambda _: None)
        self._on_devices_connected = on_devices_connected or (lambda: None)

        # HID device sessions and state
        self._devices: list[HidDeviceInfo] = []
        self._pedals_device: HidDeviceInfo | None = None
        self._wheel_device: HidDeviceInfo | None = None
        self._pedals_session = HidSession()
        self._wheel_session = HidSession()

        self._build_ui()

    # -------------------------------------------------------------------------
    # Public properties
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
        """Return the connected pedals device info."""
        return self._pedals_device

    @property
    def wheel_device(self) -> HidDeviceInfo | None:
        """Return the connected wheel device info."""
        return self._wheel_device

    @property
    def devices(self) -> list[HidDeviceInfo]:
        """Return the list of discovered HID devices."""
        return self._devices

    # -------------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Construct the device selector layout."""
        form = QFormLayout(self)

        # Pedals device combo
        self._pedals_combo = QComboBox()
        self._pedals_combo.setMinimumWidth(280)
        self._pedals_combo.setToolTip("Selecting a device connects to it immediately.")
        self._pedals_combo.activated.connect(lambda _: self.connect_devices())
        form.addRow("Pedals HID:", self._pedals_combo)

        # Wheel device combo
        self._wheel_combo = QComboBox()
        self._wheel_combo.setMinimumWidth(280)
        self._wheel_combo.setToolTip("Selecting a device connects to it immediately.")
        self._wheel_combo.activated.connect(lambda _: self.connect_devices())
        form.addRow("Wheel HID:", self._wheel_combo)

        # Button row: Refresh and Connect
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setToolTip("Rescan USB devices (keeps the current selection).")
        refresh_btn.clicked.connect(self.refresh_devices)
        btn_layout.addWidget(refresh_btn)

        connect_btn = QPushButton("Reconnect")
        connect_btn.setToolTip("Reopen the selected devices, e.g. after unplugging them.")
        connect_btn.clicked.connect(self.connect_devices)
        btn_layout.addWidget(connect_btn)

        btn_layout.addStretch()

        form.addRow("", btn_row)

    # -------------------------------------------------------------------------
    # Device management
    # -------------------------------------------------------------------------

    def refresh_devices(self) -> None:
        """Refresh the list of available HID devices."""
        if not hid_available():
            self._set_status("hidapi not available. Install hidapi to enable device selection.")
            return

        # Remember the current choices so a rescan does not silently deselect them.
        previous = [
            (self._pedals_combo, self.get_selected_pedals_device() or self._pedals_device),
            (self._wheel_combo, self.get_selected_wheel_device() or self._wheel_device),
        ]
        self._devices = enumerate_devices()
        for combo, device in previous:
            self._populate_combo(combo, "(none)")
            if device is not None:
                self._select_matching(
                    combo, device.device_id.vendor_id, device.device_id.product_id, path=device.path
                )
        self._set_status(f"Found {len(self._devices)} HID device(s).")

    def _populate_combo(self, combo: QComboBox, placeholder: str) -> None:
        """Populate a device combo box with available devices."""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(placeholder, None)
        for idx, dev in enumerate(self._devices):
            label = f"{dev.product_string} (VID:{dev.device_id.vendor_id:04x} PID:{dev.device_id.product_id:04x})"
            combo.addItem(label, idx)
        combo.blockSignals(False)

    def connect_devices(self) -> None:
        """Open/close HID sessions based on current combo selections."""
        # Close existing sessions
        self._pedals_session.close()
        self._wheel_session.close()
        self._pedals_device = None
        self._wheel_device = None

        connected: list[str] = []
        errors: list[str] = []

        # Open pedals session
        pedals_idx = self._pedals_combo.currentData()
        if pedals_idx is not None and pedals_idx < len(self._devices):
            try:
                self._pedals_device = self._devices[pedals_idx]
                if self._pedals_device is not None:
                    self._pedals_session.open(self._pedals_device)
                    connected.append(f"pedals ({self._pedals_device.product_string})")
            except Exception as e:
                errors.append(f"pedals: {e}")
                self._pedals_device = None

        # Open wheel session
        wheel_idx = self._wheel_combo.currentData()
        if wheel_idx is not None and wheel_idx < len(self._devices):
            try:
                self._wheel_device = self._devices[wheel_idx]
                if self._wheel_device is not None:
                    self._wheel_session.open(self._wheel_device)
                    connected.append(f"wheel ({self._wheel_device.product_string})")
            except Exception as e:
                errors.append(f"wheel: {e}")
                self._wheel_device = None

        if errors:
            self._set_status("Failed to open " + "; ".join(errors))
        elif connected:
            self._set_status("Connected " + " and ".join(connected) + ".")
        else:
            self._set_status("No devices selected. Running in simulator mode.")
        self._on_devices_connected()

    def select_device_by_vid_pid(
        self, device_type: str, vid: int, pid: int
    ) -> None:
        """Select a device in the combo by VID/PID match.

        Args:
            device_type: Either 'pedals' or 'wheel'.
            vid: Vendor ID to match.
            pid: Product ID to match.
        """
        if vid == 0 and pid == 0:
            return

        combo = self._pedals_combo if device_type == "pedals" else self._wheel_combo
        self._select_matching(combo, vid, pid)

    def _select_matching(
        self, combo: QComboBox, vid: int, pid: int, *, path: object = None
    ) -> None:
        """Select the combo entry matching `path` (preferred) or VID/PID."""
        fallback: int | None = None
        for i in range(combo.count()):
            idx = combo.itemData(i)
            if idx is None or idx >= len(self._devices):
                continue
            dev = self._devices[idx]
            if path is not None and dev.path == path:
                combo.setCurrentIndex(i)
                return
            ids = (dev.device_id.vendor_id, dev.device_id.product_id)
            if fallback is None and ids == (vid, pid):
                fallback = i
        if fallback is not None:
            combo.setCurrentIndex(fallback)

    def get_selected_pedals_device(self) -> HidDeviceInfo | None:
        """Get the currently selected pedals device from combo."""
        idx = self._pedals_combo.currentData()
        if idx is not None and idx < len(self._devices):
            return self._devices[idx]
        return None

    def get_selected_wheel_device(self) -> HidDeviceInfo | None:
        """Get the currently selected wheel device from combo."""
        idx = self._wheel_combo.currentData()
        if idx is not None and idx < len(self._devices):
            return self._devices[idx]
        return None

    def close_sessions(self) -> None:
        """Close all HID sessions (call on application exit)."""
        self._pedals_session.close()
        self._wheel_session.close()

    def _set_status(self, message: str) -> None:
        """Update status via callback."""
        self._on_status_update(message)
