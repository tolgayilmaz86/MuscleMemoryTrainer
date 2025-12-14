from __future__ import annotations

from pathlib import Path

import mmt_app.config as config


def test_save_and_load_profile_roundtrip(tmp_path: Path, monkeypatch) -> None:
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
    )
    ui = config.UiConfig(throttle_target=70, brake_target=30, grid_step_percent=15)
    profile = config.InputProfile(pedals=pedals, wheel=wheel, ui=ui)
    config.save_input_profile(profile)

    loaded = config.load_input_profile()
    assert loaded == profile


def test_load_missing_file_returns_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
    assert config.load_pedals_config() is None
    assert config.load_wheel_config() is None


def test_static_brake_traces_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.ini")
    config.save_static_brake_trace("my_trace", [0, 50, 100])
    traces = config.load_static_brake_traces()
    assert traces["my_trace"] == [0, 50, 100]
