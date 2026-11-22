"""Tests for the config module.

This module tests configuration persistence, loading, and validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import mmt_app.config as config


# ============================================================================
# Input Profile Tests
# ============================================================================


class TestInputProfile:
    """Tests for InputProfile save/load functionality."""

    def test_save_and_load_profile_roundtrip(self, tmp_path: Path, monkeypatch) -> None:
        """Saving and loading a profile should preserve all data."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")

        pedals = config.PedalsConfig(
            vendor_id=0x1234,
            product_id=0x5678,
            product_string="Pedals",
            report_len=64,
            throttle_offset=1,
            brake_offset=3,
        )
        wheel = config.WheelConfig(
            vendor_id=0x1111,
            product_id=0x2222,
            product_string="Wheel",
            report_len=32,
            steering_offset=9,
            steering_center=120,
            steering_range=80,
            steering_half_range=16000,
            steering_bits=16,
        )
        ui = config.UiConfig(throttle_target=70, brake_target=30, grid_step_percent=15)
        profile = config.InputProfile(pedals=pedals, wheel=wheel, ui=ui)
        config.save_input_profile(profile)

        loaded = config.load_input_profile()
        assert loaded == profile

    def test_save_profile_with_none_wheel(self, tmp_path: Path, monkeypatch) -> None:
        """Profile with None wheel should save and load correctly."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")

        pedals = config.PedalsConfig(
            vendor_id=0x1234,
            product_id=0x5678,
            product_string="Pedals",
            report_len=64,
            throttle_offset=1,
            brake_offset=3,
        )
        ui = config.UiConfig(throttle_target=50, brake_target=50, grid_step_percent=10)
        profile = config.InputProfile(pedals=pedals, wheel=None, ui=ui)
        config.save_input_profile(profile)

        loaded = config.load_input_profile()
        assert loaded.pedals == pedals
        assert loaded.wheel is None
        assert loaded.ui == ui

    def test_save_profile_with_none_pedals(self, tmp_path: Path, monkeypatch) -> None:
        """Profile with None pedals should save and load correctly."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")

        wheel = config.WheelConfig(
            vendor_id=0x1111,
            product_id=0x2222,
            product_string="Wheel",
            report_len=32,
            steering_offset=9,
            steering_center=120,
            steering_range=80,
            steering_half_range=16000,
            steering_bits=16,
        )
        ui = config.UiConfig(throttle_target=50, brake_target=50, grid_step_percent=10)
        profile = config.InputProfile(pedals=None, wheel=wheel, ui=ui)
        config.save_input_profile(profile)

        loaded = config.load_input_profile()
        assert loaded.pedals is None
        assert loaded.wheel == wheel


# ============================================================================
# Missing File Tests
# ============================================================================


class TestMissingFile:
    """Tests for handling missing configuration files."""

    def test_load_missing_file_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        """Loading from non-existent file should return None."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        assert config.load_pedals_config() is None
        assert config.load_wheel_config() is None

    def test_load_input_profile_creates_default_config(self, tmp_path: Path, monkeypatch) -> None:
        """Loading profile from missing file should create default config with all sections."""
        cfg_path = tmp_path / "config.ini"
        monkeypatch.setattr(config, "config_path", lambda: cfg_path)
        profile = config.load_input_profile()
        
        # Default config should be created
        assert cfg_path.exists()
        
        # Pedals should have default values (VID/PID 0 means no device selected)
        assert profile.pedals is not None
        assert profile.pedals.vendor_id == 0
        assert profile.pedals.product_id == 0
        assert profile.pedals.report_len == config.DEFAULT_PEDALS_REPORT_LEN
        assert profile.pedals.throttle_offset == config.DEFAULT_THROTTLE_OFFSET
        assert profile.pedals.brake_offset == config.DEFAULT_BRAKE_OFFSET
        
        # Wheel should have default values
        assert profile.wheel is not None
        assert profile.wheel.vendor_id == 0
        assert profile.wheel.product_id == 0
        assert profile.wheel.report_len == config.DEFAULT_WHEEL_REPORT_LEN
        assert profile.wheel.steering_offset == config.DEFAULT_STEERING_OFFSET
        assert profile.wheel.steering_center == config.DEFAULT_STEERING_CENTER
        assert profile.wheel.steering_range == config.DEFAULT_STEERING_RANGE
        
        # UI should have default values
        assert profile.ui is not None
        assert profile.ui.throttle_target == config.DEFAULT_THROTTLE_TARGET
        assert profile.ui.brake_target == config.DEFAULT_BRAKE_TARGET


# ============================================================================
# Trail Brake Config Tests
# ============================================================================


class TestTrailBrakeConfig:
    """Tests for Trail Brake configuration persistence."""

    def test_trail_brake_config_selected_trace(self, tmp_path: Path, monkeypatch) -> None:
        """Should save and load selected trace preference."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        cfg = config.TrailBrakeConfig(selected_trace="my_trace")
        config.save_trail_brake_config(cfg)
        loaded = config.load_trail_brake_config()
        assert loaded is not None
        assert loaded.selected_trace == "my_trace"


# ============================================================================
# Active Brake Config Tests
# ============================================================================


class TestActiveBrakeConfig:
    """Tests for Active Brake configuration persistence."""

    def test_active_brake_config_roundtrip(self, tmp_path: Path, monkeypatch) -> None:
        """Saving and loading active brake config should preserve data."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        cfg = config.ActiveBrakeConfig(speed=90)
        config.save_active_brake_config(cfg)
        loaded = config.load_active_brake_config()
        assert loaded.speed == 90

    def test_active_brake_config_default(self, tmp_path: Path, monkeypatch) -> None:
        """Loading missing active brake config should return default."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        loaded = config.load_active_brake_config()
        # Should return default config (speed=60), not None
        assert loaded is not None
        assert loaded.speed == 60


# ============================================================================
# UI Config Tests
# ============================================================================


class TestUiConfig:
    """Tests for UI configuration."""

    def test_ui_config_defaults(self) -> None:
        """UiConfig should have sensible defaults."""
        ui = config.UiConfig(throttle_target=50, brake_target=50, grid_step_percent=10)
        assert ui.update_hz == 20  # Default
        assert ui.show_steering is False  # Default
        assert ui.throttle_sound_enabled is True  # Default
        assert ui.brake_sound_enabled is True  # Default

    def test_ui_config_custom_values(self) -> None:
        """UiConfig should accept custom values."""
        ui = config.UiConfig(
            throttle_target=70,
            brake_target=30,
            grid_step_percent=25,
            update_hz=60,
            show_steering=True,
            throttle_sound_enabled=False,
            brake_sound_enabled=False,
        )
        assert ui.throttle_target == 70
        assert ui.brake_target == 30
        assert ui.grid_step_percent == 25
        assert ui.update_hz == 60
        assert ui.show_steering is True
        assert ui.throttle_sound_enabled is False
        assert ui.brake_sound_enabled is False

    def test_ui_config_with_sound_paths(self, tmp_path: Path, monkeypatch) -> None:
        """UiConfig should preserve custom sound paths."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")

        pedals = config.PedalsConfig(
            vendor_id=0x1234,
            product_id=0x5678,
            product_string="Pedals",
            report_len=64,
            throttle_offset=1,
            brake_offset=3,
        )
        ui = config.UiConfig(
            throttle_target=50,
            brake_target=50,
            grid_step_percent=10,
            throttle_sound_path="/path/to/throttle.wav",
            brake_sound_path="/path/to/brake.wav",
        )
        profile = config.InputProfile(pedals=pedals, wheel=None, ui=ui)
        config.save_input_profile(profile)

        loaded = config.load_input_profile()
        assert loaded.ui is not None
        assert loaded.ui.throttle_sound_path == "/path/to/throttle.wav"
        assert loaded.ui.brake_sound_path == "/path/to/brake.wav"


# ============================================================================
# Device Config Tests
# ============================================================================


class TestDeviceConfig:
    """Tests for device configuration dataclasses."""

    def test_pedals_config_immutable(self) -> None:
        """PedalsConfig should be frozen (immutable)."""
        pedals = config.PedalsConfig(
            vendor_id=0x1234,
            product_id=0x5678,
            product_string="Pedals",
            report_len=64,
            throttle_offset=1,
            brake_offset=3,
        )
        with pytest.raises(AttributeError):
            pedals.vendor_id = 0x9999  # type: ignore

    def test_wheel_config_immutable(self) -> None:
        """WheelConfig should be frozen (immutable)."""
        wheel = config.WheelConfig(
            vendor_id=0x1111,
            product_id=0x2222,
            product_string="Wheel",
            report_len=32,
            steering_offset=9,
            steering_center=120,
            steering_range=80,
            steering_half_range=16000,
            steering_bits=16,
        )
        with pytest.raises(AttributeError):
            wheel.steering_center = 128  # type: ignore

    def test_pedals_config_equality(self) -> None:
        """Two PedalsConfigs with same values should be equal."""
        p1 = config.PedalsConfig(
            vendor_id=0x1234,
            product_id=0x5678,
            product_string="Pedals",
            report_len=64,
            throttle_offset=1,
            brake_offset=3,
        )
        p2 = config.PedalsConfig(
            vendor_id=0x1234,
            product_id=0x5678,
            product_string="Pedals",
            report_len=64,
            throttle_offset=1,
            brake_offset=3,
        )
        assert p1 == p2


# ============================================================================
# Settings Tab Integration Tests
# ============================================================================


class TestSettingsTabSaveButton:
    """Tests for SettingsTab persistence of config.ini and input bindings."""

    @pytest.fixture
    def qapp(self):
        """Create a QApplication for widget tests."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    def test_settings_tab_creates_config_file(self, tmp_path: Path, monkeypatch, qapp) -> None:
        """Opening the Settings tab should create config.ini with defaults."""
        from mmt_app.ui.settings_tab import SettingsTab

        cfg_path = tmp_path / "config.ini"
        monkeypatch.setattr(config, "config_path", lambda: cfg_path)
        assert not cfg_path.exists()

        SettingsTab()

        assert cfg_path.exists()
        assert "[ui]" in cfg_path.read_text()

    def test_settings_tab_loads_saved_bindings(self, tmp_path: Path, monkeypatch, qapp) -> None:
        """Bindings saved earlier are available after a restart."""
        from mmt_app.input.bindings import AxisBinding, save_binding
        from mmt_app.input.hid_descriptor import AxisField
        from mmt_app.ui.settings_tab import SettingsTab

        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        brake = AxisBinding(
            vendor_id=0x346E,
            product_id=0x0008,
            product_string="mBooster Pedals",
            field=AxisField(0x10, 32, 16, 0, 0xFFFF, 0x01, 0x35),
            rest=120,
            full=60000,
        )
        save_binding("brake", brake)

        settings = SettingsTab()

        assert settings.inputs.binding("brake") == brake
        assert settings.inputs.binding("throttle") is None

    def test_save_ui_settings_creates_config(self, tmp_path: Path, monkeypatch, qapp) -> None:
        """UI settings auto-save should create config.ini."""
        from mmt_app.ui.settings_tab import SettingsTab
        
        cfg_path = tmp_path / "config.ini"
        monkeypatch.setattr(config, "config_path", lambda: cfg_path)
        
        # Create settings tab
        settings = SettingsTab()
        
        # Set specific values
        settings._throttle_target_slider.setValue(75)
        settings._brake_target_slider.setValue(35)
        settings._grid_step_slider.setValue(20)
        
        # Trigger UI settings save
        settings._save_ui_settings()
        
        # Verify config file exists
        assert cfg_path.exists()
        
        # Verify values were saved
        loaded_ui = config.load_ui_config()
        assert loaded_ui is not None
        assert loaded_ui.throttle_target == 75
        assert loaded_ui.brake_target == 35
        assert loaded_ui.grid_step_percent == 20



# ============================================================================
# Persistence additions
# ============================================================================


class TestCustomTraces:
    """Tests for the custom brake trace library."""

    def test_roundtrip(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        config.save_custom_traces({"Turn 1": [0, 40, 80, 20, 0]})
        assert config.load_custom_traces() == {"Turn 1": [0, 40, 80, 20, 0]}

    def test_missing_file_gives_empty_library(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        assert config.load_custom_traces() == {}

    def test_malformed_entries_are_skipped(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        config.custom_traces_path().write_text(
            '{"ok": [0, 150, -5], "bad": "nope", "empty": [], "junk": ["x"]}', encoding="utf-8"
        )
        assert config.load_custom_traces() == {"ok": [0, 100, 0]}

    def test_corrupt_file_gives_empty_library(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        config.custom_traces_path().write_text("{not json", encoding="utf-8")
        assert config.load_custom_traces() == {}


class TestUiConfigWindowState:
    """Window size and last tab must survive saves from the Settings tab."""

    @pytest.fixture
    def qapp(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    def test_always_on_top_roundtrip(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        assert config.UiConfig(throttle_target=1, brake_target=1, grid_step_percent=10).always_on_top is False
        config.save_ui_config(
            config.UiConfig(throttle_target=90, brake_target=70, grid_step_percent=20, always_on_top=True)
        )
        loaded = config.load_ui_config()
        assert loaded is not None and loaded.always_on_top is True

    def test_last_tab_roundtrip(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        config.save_ui_config(
            config.UiConfig(throttle_target=90, brake_target=70, grid_step_percent=20, last_tab=3)
        )
        loaded = config.load_ui_config()
        assert loaded is not None and loaded.last_tab == 3

    def test_settings_save_preserves_window_state(self, tmp_path: Path, monkeypatch, qapp) -> None:
        from mmt_app.ui.settings_tab import SettingsTab

        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        settings = SettingsTab()
        config.save_ui_config(
            config.UiConfig(
                throttle_target=90,
                brake_target=70,
                grid_step_percent=20,
                window_width=1400,
                window_height=900,
                last_tab=2,
            )
        )
        settings._brake_target_slider.setValue(55)
        settings._save_ui_settings()

        loaded = config.load_ui_config()
        assert loaded is not None
        assert loaded.brake_target == 55
        assert (loaded.window_width, loaded.window_height, loaded.last_tab) == (1400, 900, 2)
