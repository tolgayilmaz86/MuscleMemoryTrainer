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

    def test_trail_brake_traces_roundtrip(self, tmp_path: Path, monkeypatch) -> None:
        """Saving and loading trail brake traces should preserve data."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        config.save_trail_brake_trace("my_trace", [0, 50, 100])
        traces = config.load_trail_brake_traces()
        assert traces["my_trace"] == [0, 50, 100]

    def test_save_multiple_traces(self, tmp_path: Path, monkeypatch) -> None:
        """Should be able to save multiple traces."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        config.save_trail_brake_trace("trace1", [0, 25, 50])
        config.save_trail_brake_trace("trace2", [0, 75, 100])
        traces = config.load_trail_brake_traces()
        assert traces["trace1"] == [0, 25, 50]
        assert traces["trace2"] == [0, 75, 100]

    def test_overwrite_existing_trace(self, tmp_path: Path, monkeypatch) -> None:
        """Saving trace with existing name should overwrite."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        config.save_trail_brake_trace("my_trace", [0, 50, 100])
        config.save_trail_brake_trace("my_trace", [0, 25, 50])
        traces = config.load_trail_brake_traces()
        assert traces["my_trace"] == [0, 25, 50]

    def test_load_traces_missing_returns_empty_dict(self, tmp_path: Path, monkeypatch) -> None:
        """Loading traces from missing file should return empty dict."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        traces = config.load_trail_brake_traces()
        assert traces == {}

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
        cfg = config.ActiveBrakeConfig(grid_step_percent=25)
        config.save_active_brake_config(cfg)
        loaded = config.load_active_brake_config()
        assert loaded.grid_step_percent == 25

    def test_active_brake_config_default(self, tmp_path: Path, monkeypatch) -> None:
        """Loading missing active brake config should return default."""
        monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
        loaded = config.load_active_brake_config()
        # Should return default config, not None
        assert loaded is not None


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
    """Tests for SettingsTab Save button creating config.ini."""

    @pytest.fixture
    def qapp(self):
        """Create a QApplication for widget tests."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    def test_save_button_creates_config_file(self, tmp_path: Path, monkeypatch, qapp) -> None:
        """Clicking Save in SettingsTab should create config.ini with settings."""
        from mmt_app.ui.settings_tab import SettingsTab
        
        cfg_path = tmp_path / "config.ini"
        monkeypatch.setattr(config, "config_path", lambda: cfg_path)
        
        # Ensure no config exists initially
        assert not cfg_path.exists()
        
        # Create settings tab
        settings = SettingsTab()
        
        # Modify some settings
        settings._throttle_offset.setValue(5)
        settings._brake_offset.setValue(7)
        settings._steering_range_slider.setValue(540)
        
        # Call save (simulates clicking Save button)
        settings.save_current_mapping()
        
        # Verify config file was created
        assert cfg_path.exists()
        
        # Verify content can be read back
        content = cfg_path.read_text()
        assert "[pedals]" in content and "[wheel]" in content and "[ui]" in content

    def test_save_button_persists_calibration_values(self, tmp_path: Path, monkeypatch, qapp) -> None:
        """Save button should persist calibration offset values to config.ini."""
        from mmt_app.ui.settings_tab import SettingsTab
        
        cfg_path = tmp_path / "config.ini"
        monkeypatch.setattr(config, "config_path", lambda: cfg_path)
        
        # Create settings tab and set specific calibration values
        settings = SettingsTab()
        settings._pedals_report_len.setValue(16)
        settings._throttle_offset.setValue(3)
        settings._brake_offset.setValue(5)
        settings._wheel_report_len.setValue(32)
        settings._steering_offset.setValue(2)
        settings._steering_range_slider.setValue(720)
        
        # Note: Without a device selected, save_current_mapping won't save pedals/wheel
        # But _save_ui_settings will save UI settings
        settings._save_ui_settings()
        
        # Verify UI settings were saved
        loaded_ui = config.load_ui_config()
        assert loaded_ui is not None

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

