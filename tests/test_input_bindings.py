"""Tests for movement-based axis binding and the controller hub."""

from __future__ import annotations

from pathlib import Path

import pytest

import mmt_app.config as config
from mmt_app.input.bindings import (
    AxisBinding,
    AxisDetector,
    InputMapper,
    load_bindings,
    save_binding,
)
from mmt_app.input.controllers import ControllerInfo, InputHub
from mmt_app.input.hid_descriptor import AxisField, guess_axes

RX = AxisField(0x10, 0, 16, 0, 0xFFFF, 0x01, 0x33)
RY = AxisField(0x10, 16, 16, 0, 0xFFFF, 0x01, 0x34)
RZ = AxisField(0x10, 32, 16, 0, 0xFFFF, 0x01, 0x35)
WHEEL_X = AxisField(0x01, 128, 16, -32768, 32767, 0x01, 0x30)
PADDLE_X = AxisField(0x01, 128, 16, 0, 0xFFFF, 0x01, 0x30)


class FakeController:
    """Stands in for an opened Controller: fixed axes with settable values."""

    def __init__(self, name: str, vid: int, pid: int, axes: list[AxisField]) -> None:
        self.info = ControllerInfo(vid, pid, name, name.encode())
        self.axes = list(axes)
        self.values: dict[AxisField, int] = {axis: 0 for axis in axes}
        self.fail = False
        self.opened = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def poll(self) -> None:
        if self.fail:
            raise OSError("read error")

    def value(self, field: AxisField) -> int | None:
        return self.values.get(field)

    def has_axis(self, field: AxisField) -> bool:
        return field in self.axes


@pytest.fixture
def rig() -> dict[str, FakeController]:
    """mBooster pedals + VNM base + Forte rim, like the real hardware."""
    return {
        "pedals": FakeController("mBooster Pedals", 0x346E, 0x0008, [RX, RY, RZ]),
        "base": FakeController("VNM Direct Drive", 0x0483, 0xA3D5, [WHEEL_X]),
        "rim": FakeController("Forte Formula Pro wheel", 0x2433, 0xF402, [PADDLE_X]),
    }


def _drive(detector: AxisDetector, rig, controller: str, field: AxisField, path: list[int]):
    """Feed a movement path for one axis while other axes jitter slightly."""
    for i, raw in enumerate(path):
        rig[controller].values[field] = raw
        rig["pedals"].values[RY] = 312 + (i % 3) * 20 if field is not RY else rig["pedals"].values[RY]
        rig["base"].values[WHEEL_X] = -224 + (i % 2) * 10 if field is not WHEEL_X else raw
        detector.update(rig.values())


def _press(rest: int, full: int, steps: int = 10) -> list[int]:
    down = [rest + (full - rest) * i // steps for i in range(steps + 1)]
    return [rest] * 3 + down + down[::-1] + [rest] * 3


class TestAxisDetector:
    """'Press the brake now' detection."""

    def test_binds_the_pressed_pedal(self, rig) -> None:
        detector = AxisDetector("brake")
        _drive(detector, rig, "pedals", RZ, _press(0, 62000))
        result = detector.result()
        assert result is not None
        assert result.field == RZ
        assert result.product_string == "mBooster Pedals"
        assert (result.rest, result.full) == (0, 62000)

    def test_waits_until_released(self, rig) -> None:
        detector = AxisDetector("brake")
        press = _press(0, 62000)
        _drive(detector, rig, "pedals", RZ, press[: len(press) // 2])  # Still held down
        assert detector.leader().field == RZ
        assert detector.reached_travel()
        assert detector.result() is None

    def test_light_press_is_not_enough(self, rig) -> None:
        detector = AxisDetector("brake")
        _drive(detector, rig, "pedals", RZ, _press(0, 9000))  # ~14% of the range
        assert detector.result() is None

    def test_jitter_alone_detects_nothing(self, rig) -> None:
        detector = AxisDetector("throttle")
        _drive(detector, rig, "pedals", RX, [0] * 30)
        assert detector.leader() is None

    def test_inverted_pedal(self, rig) -> None:
        detector = AxisDetector("throttle")
        _drive(detector, rig, "pedals", RX, _press(65535, 2000))
        binding = detector.result()
        assert binding is not None and (binding.rest, binding.full) == (65535, 2000)
        assert binding.pedal_percent(65535) == 0.0
        assert binding.pedal_percent(2000) == 100.0

    def test_steering_binds_wheel_not_paddles(self, rig) -> None:
        detector = AxisDetector("steering")
        turn = [0, -4000, -8000, -4000, 0, 4000, 8000, 4000, 0, 0, 0]
        _drive(detector, rig, "base", WHEEL_X, turn)
        binding = detector.result()
        assert binding is not None and binding.field == WHEEL_X
        assert binding.rest == 0  # Logical center of a signed axis
        assert binding.steering_percent(16384) == pytest.approx(50.0, abs=0.01)
        assert binding.steering_percent(-32768) == -100.0

    def test_excluded_axes_are_ignored(self, rig) -> None:
        throttle = AxisBinding(0x346E, 0x0008, "mBooster Pedals", RX, 0, 65535)
        detector = AxisDetector("brake", exclude=[throttle])
        _drive(detector, rig, "pedals", RX, _press(0, 65535))
        assert detector.leader() is None

    def test_guessed_bytes_prefer_the_16bit_value(self) -> None:
        fields = guess_axes(4)  # report: [id, lo, hi, other]
        device = FakeController("Generic pedals", 0x1234, 0x5678, fields)
        detector = AxisDetector("brake")
        for raw in _press(100, 60000, steps=40):
            report = [0x01, raw & 0xFF, raw >> 8, 0x00]
            device.values = {f: f.read(report) for f in fields}
            detector.update([device])
        binding = detector.result()
        assert binding is not None and binding.field.name == "Bytes 1-2"


class TestAxisBinding:
    """Calibrated value mapping."""

    def test_pedal_deadzones(self) -> None:
        binding = AxisBinding(1, 2, "P", RZ, rest=312, full=60312)
        assert binding.pedal_percent(312) == 0.0
        assert binding.pedal_percent(312 + 600) == 0.0  # Within the low deadzone
        assert binding.pedal_percent(60312) == 100.0
        assert binding.pedal_percent(30312) == pytest.approx(50.0)
        assert binding.pedal_percent(65535) == 100.0  # Pressing harder than calibration

    def test_label(self) -> None:
        assert AxisBinding(1, 2, "mBooster Pedals", RZ, 0, 1).label == "mBooster Pedals · Rz"


class TestInputMapper:
    """Reading values through bindings and the hub."""

    def _hub(self, rig) -> InputHub:
        infos = [c.info for c in rig.values()]
        by_path = {c.info.path: c for c in rig.values()}
        hub = InputHub(enumerate_fn=lambda: infos, controller_factory=lambda i: by_path[i.path])
        hub.refresh()
        return hub

    def test_values_from_bound_axes(self, rig) -> None:
        mapper = InputMapper(self._hub(rig), {
            "brake": AxisBinding(0x346E, 0x0008, "mBooster Pedals", RZ, 0, 60000),
            "steering": AxisBinding(0x0483, 0xA3D5, "VNM Direct Drive", WHEEL_X, 0, 0),
        })
        rig["pedals"].values[RZ] = 30000
        rig["base"].values[WHEEL_X] = -16384
        assert mapper.value("brake") == pytest.approx(50.0, abs=0.1)
        assert mapper.value("steering") == pytest.approx(-50.0, abs=0.01)
        assert mapper.value("throttle") is None

    def test_unplugged_device_is_reported(self, rig) -> None:
        hub = self._hub(rig)
        mapper = InputMapper(hub, {"brake": AxisBinding(0x346E, 0x0008, "mBooster Pedals", RZ, 0, 1)})
        rig["pedals"].fail = True
        assert mapper.poll() == ["mBooster Pedals"]
        assert mapper.value("brake") is None
        assert mapper.missing_devices() == ["mBooster Pedals"]

    def test_refresh_drops_removed_and_opens_new(self, rig) -> None:
        present = [rig["pedals"].info]
        by_path = {c.info.path: c for c in rig.values()}
        hub = InputHub(enumerate_fn=lambda: list(present), controller_factory=lambda i: by_path[i.path])
        hub.refresh()
        assert [c.info.product_string for c in hub.controllers] == ["mBooster Pedals"]
        present[:] = [rig["base"].info]
        hub.refresh()
        assert [c.info.product_string for c in hub.controllers] == ["VNM Direct Drive"]
        assert not rig["pedals"].opened

    def test_background_refresh(self, rig) -> None:
        import time

        by_path = {c.info.path: c for c in rig.values()}
        hub = InputHub(
            enumerate_fn=lambda: [rig["pedals"].info], controller_factory=lambda i: by_path[i.path]
        )
        assert not hub.finish_background_refresh()  # Nothing pending
        hub.start_background_refresh()
        deadline = time.monotonic() + 2.0
        while not hub.finish_background_refresh():
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert [c.info.product_string for c in hub.controllers] == ["mBooster Pedals"]


class TestBindingPersistence:
    """config.ini round trip."""

    def test_roundtrip_and_remove(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        brake = AxisBinding(0x346E, 0x0008, "Pedals 100% edition", RZ, 312, 61000)
        guessed = AxisBinding(1, 2, "Generic", guess_axes(3)[1], 10, 50000)
        save_binding("brake", brake)
        save_binding("throttle", guessed)
        assert load_bindings() == {"throttle": guessed, "brake": brake}
        save_binding("brake", None)
        assert load_bindings() == {"throttle": guessed}

    def test_other_sections_survive(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        config.ensure_config_exists()
        save_binding("brake", AxisBinding(1, 2, "P", RZ, 0, 1))
        assert config.load_ui_config() is not None

    def test_malformed_section_is_skipped(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        (tmp_path / "config.ini").write_text("[binding.brake]\nvendor_id = nope\n", encoding="utf-8")
        assert load_bindings() == {}
