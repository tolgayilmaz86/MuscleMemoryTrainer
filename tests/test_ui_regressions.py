"""Regression tests for UI behaviour (training tabs and sound settings)."""

from __future__ import annotations

from pathlib import Path

import pytest

import mmt_app.config as config


@pytest.fixture
def qapp():
    """Create a QApplication for widget tests."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch) -> Path:
    """Redirect config.ini (and the trace library) into a temp directory."""
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
    return tmp_path


# ============================================================================
# Trail Brake
# ============================================================================


class TestTrailBrakeTab:
    """Tests for the Trail Brake tab."""

    def test_length_slider_resizes_random_trace(self, qapp, tmp_config) -> None:
        from mmt_app.ui.trail_brake_tab import TrailBrakeTab

        tab = TrailBrakeTab(read_brake_percent=lambda: 0.0)
        tab._length_slider.setValue(220)
        assert len(tab._state.trace.points) == 220
        assert tab._length_label.text() == "220"

    def test_finished_attempt_is_scored(self, qapp, tmp_config) -> None:
        from mmt_app.ui.trail_brake_tab import TrailBrakeTab

        tab = TrailBrakeTab(read_brake_percent=lambda: 0.0)
        tab._auto_regen_checkbox.setChecked(False)
        points = tab._state.trace.points
        step = {"i": 0}

        def follow_target() -> float:
            step["i"] += 1
            return float(points[min(step["i"], len(points) - 1)])

        tab._read_brake_percent = follow_target
        tab.toggle_recording()
        for _ in range(len(points) + 5):
            tab._on_tick()
        assert len(tab._scores) == 1
        assert tab._scores[0] > 90.0
        assert "Best" in tab._score_label.text()

    def test_brake_tap_is_not_scored_and_keeps_target(self, qapp, tmp_config) -> None:
        from mmt_app.ui.trail_brake_tab import TrailBrakeTab

        taps = iter([20.0, 0.0])
        tab = TrailBrakeTab(read_brake_percent=lambda: next(taps, 0.0))
        target_before = tab._state.trace.points
        tab.toggle_recording()
        for _ in range(5):
            tab._on_tick()
        assert tab._scores == []
        assert tab._state.trace.points == target_before
        assert tab._state.recording  # re-armed for another try

    def test_imported_trace_is_persisted_and_selected(self, qapp, tmp_config, monkeypatch) -> None:
        from mmt_app.ui import trail_brake_tab
        from mmt_app.ui.trail_brake_tab import TrailBrakeTab

        trace_file = tmp_config / "corner.json"
        trace_file.write_text('{"name": "Corner", "points": [0, 30, 70, 10, 0]}', encoding="utf-8")
        monkeypatch.setattr(
            trail_brake_tab.QFileDialog,
            "getOpenFileName",
            staticmethod(lambda *a, **k: (str(trace_file), "")),
        )

        tab = TrailBrakeTab(read_brake_percent=lambda: 0.0)
        tab.import_trace()

        assert tab._trace_combo.currentText() == "Custom: Corner"
        assert tab._delete_btn.isEnabled()
        assert not tab._length_slider.isEnabled()
        assert config.load_custom_traces() == {"Corner": [0, 30, 70, 10, 0]}

        # A new tab instance (i.e. next app start) still has the trace.
        reopened = TrailBrakeTab(read_brake_percent=lambda: 0.0)
        assert "Corner" in reopened._custom


# ============================================================================
# Active Brake
# ============================================================================


class TestActiveBrakeTab:
    """Tests for the Active Brake tab."""

    @pytest.mark.parametrize(
        ("pattern", "shape"),
        [
            ("spike", "_shape_spike"),
            ("double_peak", "_shape_double_peak"),
            ("hill", "_shape_hill"),
            ("trail_brake", "_shape_trail_brake"),
            ("ramp_hold_drop", "_shape_ramp_hold_drop"),
        ],
    )
    def test_segment_uses_requested_pattern(self, qapp, tmp_config, monkeypatch, pattern, shape):
        from mmt_app.ui.active_brake_tab import ActiveBrakeTab

        tab = ActiveBrakeTab(read_brake_percent=lambda: 0.0)
        monkeypatch.setattr(ActiveBrakeTab, shape, staticmethod(lambda length, peak: [42.0] * 30))
        segment = tab._build_segment(pattern)
        assert all(abs(v - 42.0) < 3.0 for v in segment)

    def test_pauses_when_hidden(self, qapp, tmp_config) -> None:
        from mmt_app.ui.active_brake_tab import ActiveBrakeTab

        tab = ActiveBrakeTab(read_brake_percent=lambda: 0.0)
        tab.show()
        tab.toggle_running()
        assert tab._state.running
        tab.hide()
        assert not tab._state.running

    def test_accuracy_is_reported(self, qapp, tmp_config) -> None:
        from mmt_app.ui.active_brake_tab import ActiveBrakeTab

        tab = ActiveBrakeTab(read_brake_percent=lambda: 0.0)
        tab.toggle_running()
        for _ in range(300):
            tab._on_tick()
        assert tab._state.scored_samples > 0
        assert tab._score_label.text().startswith("Accuracy: ")
        assert tab._score_label.text() != "Accuracy: --"


# ============================================================================
# Sounds
# ============================================================================


class TestDefaultSound:
    """The built-in beep must not be persisted as if it were a user file."""

    def test_embedded_sound_path_is_stable(self) -> None:
        from mmt_app.embedded_sound import get_embedded_sound_path

        first = get_embedded_sound_path()
        assert first.exists()
        assert get_embedded_sound_path() == first

    @pytest.mark.parametrize(
        "path",
        [
            None,
            "",
            r"C:\Users\x\AppData\Local\Temp\_MEI199722\resources\beep.mp3",
            r"C:\Users\x\AppData\Local\Temp\mmt_beep_abc123.mp3",
        ],
    )
    def test_builtin_paths_are_treated_as_default(self, qapp, path) -> None:
        from mmt_app.ui.sound_manager import SoundManager

        manager = SoundManager()
        manager.set_path("brake", path)
        assert manager.custom_path("brake") is None

    def test_custom_path_is_kept(self, qapp, tmp_path: Path) -> None:
        from mmt_app.ui.sound_manager import SoundManager

        custom = tmp_path / "ding.wav"
        custom.write_bytes(b"RIFF")
        manager = SoundManager()
        manager.set_path("throttle", custom)
        assert manager.custom_path("throttle") == str(custom)
        assert manager.get_path("throttle") == str(custom)


# ============================================================================
# Wheel & pedal setup
# ============================================================================


class TestInputSetupFlow:
    """The guided 'press throttle, press brake, turn wheel' dialog."""

    def test_full_setup_binds_each_role(self, qapp, tmp_config) -> None:
        from test_input_bindings import RY, RZ, WHEEL_X, FakeController
        from mmt_app.input.bindings import InputMapper, load_bindings
        from mmt_app.input.controllers import InputHub
        from mmt_app.ui.input_setup import AxisDetectDialog, InputBindingsGroup

        pedals = FakeController("mBooster Pedals", 0x346E, 0x0008, [RY, RZ])
        base = FakeController("VNM Direct Drive", 0x0483, 0xA3D5, [WHEEL_X])
        devices = {c.info.path: c for c in (pedals, base)}
        hub = InputHub(
            enumerate_fn=lambda: [c.info for c in devices.values()],
            controller_factory=lambda info: devices[info.path],
        )
        hub.refresh()
        mapper = InputMapper(hub)
        group = InputBindingsGroup(mapper)
        group.open_setup()
        dialog = group.findChild(AxisDetectDialog)
        assert dialog is not None

        def move(controller, field, path):
            for raw in path:
                controller.values[field] = raw
                dialog._tick()

        press = [0, 0, 0, 20000, 40000, 60000, 40000, 20000, 0, 0]
        move(pedals, RY, press)          # Step 1: throttle
        dialog._next_role()
        move(pedals, RY, press)          # Step 2: pressing the throttle again is ignored...
        assert "brake" not in dialog.results
        move(pedals, RZ, press)          # ...the brake is what gets bound
        dialog._next_role()
        move(base, WHEEL_X, [0, -6000, -12000, -6000, 0, 6000, 12000, 6000, 0, 0])
        dialog._next_role()              # Last step completes the dialog

        assert mapper.binding("throttle").field == RY
        assert mapper.binding("brake").field == RZ
        assert mapper.binding("steering").field == WHEEL_X
        assert set(load_bindings()) == {"throttle", "brake", "steering"}

    def test_cancel_changes_nothing(self, qapp, tmp_config) -> None:
        from mmt_app.input.bindings import InputMapper
        from mmt_app.input.controllers import InputHub
        from mmt_app.ui.input_setup import AxisDetectDialog, InputBindingsGroup

        mapper = InputMapper(InputHub(enumerate_fn=lambda: []))
        group = InputBindingsGroup(mapper)
        group.open_setup(["brake"])
        dialog = group.findChild(AxisDetectDialog)
        dialog._tick()
        assert dialog._detected_label.text() == "No wheel or pedals found"
        dialog.reject()
        assert not mapper.has_bindings()
