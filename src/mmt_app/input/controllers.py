"""Game controller access: open wheels/pedals/joysticks and decode their axes.

Only HID interfaces that declare themselves as game controllers are used (the
same ones games list), which skips keyboards, mice, receivers and the
vendor-specific configuration interfaces many wheels and pedals also expose.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from mmt_app.input import hid_backend
from mmt_app.input.hid_descriptor import AxisField, guess_axes, parse_input_axes

# (usage page, usage) of joystick, gamepad and multi-axis controller collections
GAME_CONTROLLER_USAGES = frozenset({(0x01, 0x04), (0x01, 0x05), (0x01, 0x08)})

_READ_SIZE = 1024
_MAX_READS_PER_POLL = 256  # Drain fully: 1 kHz devices queue ~17 reports per 60 Hz tick

# hid.enumerate() can take ~200 ms on Windows; background refreshes use this worker.
_enumerate_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hid-enumerate")


@dataclass(frozen=True, slots=True)
class ControllerInfo:
    """Identity of one game controller HID interface."""

    vendor_id: int
    product_id: int
    product_string: str
    path: bytes


def enumerate_controllers() -> list[ControllerInfo]:
    """Return the HID interfaces that are joysticks, gamepads or multi-axis controllers."""
    if hid_backend.hid is None:
        return []
    controllers: list[ControllerInfo] = []
    seen: set[bytes] = set()
    for d in hid_backend.hid.enumerate():
        if (d.get("usage_page"), d.get("usage")) not in GAME_CONTROLLER_USAGES:
            continue
        path = d.get("path")
        if not path or path in seen:
            continue
        seen.add(path)
        controllers.append(
            ControllerInfo(
                vendor_id=int(d.get("vendor_id") or 0),
                product_id=int(d.get("product_id") or 0),
                product_string=(d.get("product_string") or "").strip() or "Game controller",
                path=path,
            )
        )
    return controllers


class Controller:
    """An opened game controller that remembers the latest report per report ID.

    Any number of callers may `poll()`; the decoded state is shared, so readers
    never steal reports from each other.
    """

    def __init__(self, info: ControllerInfo) -> None:
        self.info = info
        self.axes: list[AxisField] = []
        self.axes_guessed = False
        self._handle = None
        self._numbered = False
        self._reports: dict[int, list[int]] = {}

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    def open(self) -> None:
        """Open the device and read its axis layout from the report descriptor."""
        if hid_backend.hid is None:
            raise RuntimeError("hidapi is not installed")
        handle = hid_backend.hid.device()
        handle.open_path(self.info.path)
        handle.set_nonblocking(True)
        self._handle = handle
        try:
            descriptor = handle.get_report_descriptor()
        except (OSError, ValueError, AttributeError):
            descriptor = []
        self.axes = parse_input_axes(descriptor)
        self._numbered = any(axis.report_id for axis in self.axes)

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.close()
        finally:
            self._handle = None
            self._reports.clear()

    def poll(self) -> None:
        """Drain pending input reports.

        Raises:
            OSError: If the device was disconnected.
        """
        if self._handle is None:
            return
        for _ in range(_MAX_READS_PER_POLL):
            data = self._handle.read(_READ_SIZE, timeout_ms=0)
            if not data:
                break
            self._reports[data[0] if self._numbered else 0] = list(data)
        if not self.axes and self._reports:
            # No usable descriptor: offer every byte / byte pair as a candidate axis.
            self.axes = guess_axes(max(len(r) for r in self._reports.values()))
            self.axes_guessed = True

    def value(self, field: AxisField) -> int | None:
        """Return the latest raw value of `field`, or None if no report has it yet."""
        return field.read(self._reports.get(field.report_id))

    def has_axis(self, field: AxisField) -> bool:
        return field in self.axes


class InputHub:
    """Keeps every connected game controller open and polled."""

    def __init__(
        self,
        *,
        enumerate_fn: Callable[[], list[ControllerInfo]] = enumerate_controllers,
        controller_factory: Callable[[ControllerInfo], Controller] = Controller,
    ) -> None:
        self._enumerate = enumerate_fn
        self._factory = controller_factory
        self._controllers: list[Controller] = []
        self._pending: Future[list[ControllerInfo]] | None = None

    @property
    def controllers(self) -> list[Controller]:
        return list(self._controllers)

    def refresh(self) -> None:
        """Open newly connected controllers and forget unplugged ones (blocking)."""
        self._apply(self._enumerate())

    def start_background_refresh(self) -> None:
        """Enumerate devices on a worker thread; apply later with `finish_background_refresh`."""
        if self._pending is None:
            self._pending = _enumerate_worker.submit(self._enumerate)

    def finish_background_refresh(self) -> bool:
        """Apply a completed background enumeration.

        Returns:
            True if a refresh was applied, False if none was pending or it is still running.
        """
        if self._pending is None or not self._pending.done():
            return False
        future, self._pending = self._pending, None
        try:
            infos = future.result()
        except Exception:
            return False
        self._apply(infos)
        return True

    def _apply(self, infos: list[ControllerInfo]) -> None:
        paths = {info.path for info in infos}
        for controller in list(self._controllers):
            if controller.info.path not in paths:
                controller.close()
                self._controllers.remove(controller)
        known = {c.info.path for c in self._controllers}
        for info in infos:
            if info.path in known:
                continue
            controller = self._factory(info)
            try:
                controller.open()
            except (OSError, ValueError, RuntimeError):
                continue  # Busy or inaccessible; try again on the next refresh.
            self._controllers.append(controller)

    def poll(self) -> list[Controller]:
        """Poll every controller.

        Returns:
            Controllers that failed (unplugged); they are closed and dropped.
        """
        dropped = []
        for controller in list(self._controllers):
            try:
                controller.poll()
            except (OSError, ValueError):
                controller.close()
                self._controllers.remove(controller)
                dropped.append(controller)
        return dropped

    def find(self, vendor_id: int, product_id: int, field: AxisField | None = None) -> Controller | None:
        """Find a connected controller by VID/PID, preferring one that has `field`."""
        matches = [
            c for c in self._controllers
            if (c.info.vendor_id, c.info.product_id) == (vendor_id, product_id)
        ]
        if field is not None:
            for controller in matches:
                if controller.has_axis(field):
                    return controller
        return matches[0] if matches else None

    def close(self) -> None:
        for controller in self._controllers:
            controller.close()
        self._controllers.clear()
