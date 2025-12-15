from __future__ import annotations

import configparser
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStandardPaths


@dataclass(frozen=True)
class DeviceConfig:
    vendor_id: int
    product_id: int
    product_string: str
    report_len: int


@dataclass(frozen=True)
class PedalsConfig(DeviceConfig):
    throttle_offset: int
    brake_offset: int


@dataclass(frozen=True)
class WheelConfig(DeviceConfig):
    steering_offset: int
    steering_center: int
    steering_range: int
    steering_half_range: int  # Raw value half-range (center to full lock)
    steering_16bit: bool = False


@dataclass(frozen=True)
class InputProfile:
    """Full input mapping for the application."""

    pedals: Optional[PedalsConfig]
    wheel: Optional[WheelConfig]
    ui: Optional["UiConfig"]


@dataclass(frozen=True)
class UiConfig:
    """UI/training settings persisted to config.ini."""

    throttle_target: int
    brake_target: int
    grid_step_percent: int
    update_hz: int = 20
    show_steering: bool = False
    show_watermark: bool = True
    throttle_sound_enabled: bool = True
    throttle_sound_path: str | None = None
    brake_sound_enabled: bool = True
    brake_sound_path: str | None = None
    window_width: int = 1080
    window_height: int = 600


@dataclass(frozen=True)
class TrailBrakeConfig:
    """Persistence for Trail Brake mode."""

    selected_trace: str


@dataclass(frozen=True)
class ActiveBrakeConfig:
    """Persistence for Active Brake mode."""

    speed: int  # Speed/update rate in Hz (30-120)


# -------------------------------------------------------------------------
# Default values for all settings
# -------------------------------------------------------------------------

# Device defaults
DEFAULT_PEDALS_REPORT_LEN: int = 4
DEFAULT_WHEEL_REPORT_LEN: int = 8
DEFAULT_THROTTLE_OFFSET: int = 1
DEFAULT_BRAKE_OFFSET: int = 2
DEFAULT_STEERING_OFFSET: int = 0
DEFAULT_STEERING_CENTER: int = 128
DEFAULT_STEERING_RANGE: int = 900
DEFAULT_STEERING_HALF_RANGE: int = 32767  # Default for 16-bit (0-65535)
DEFAULT_STEERING_16BIT: bool = True

# UI defaults
DEFAULT_THROTTLE_TARGET: int = 60
DEFAULT_BRAKE_TARGET: int = 40
DEFAULT_GRID_STEP_PERCENT: int = 10
DEFAULT_UPDATE_HZ: int = 60
DEFAULT_SHOW_STEERING: bool = True
DEFAULT_SHOW_WATERMARK: bool = True
DEFAULT_WINDOW_WIDTH: int = 1080
DEFAULT_WINDOW_HEIGHT: int = 600

# Active Brake defaults
DEFAULT_ACTIVE_BRAKE_SPEED: int = 60  # Update rate in Hz (30-120)


def config_path() -> Path:
    # e.g., C:\Users\<user>\AppData\Local\Muscle Memory Trainer on Windows
    config_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.ini"


def ensure_config_exists() -> None:
    """Create config.ini with all default values if it doesn't exist."""
    path = config_path()
    if path.exists():
        return

    parser = configparser.ConfigParser()

    # Pedals section (no device selected by default, but include calibration defaults)
    parser["pedals"] = {
        "vendor_id": "0x0",
        "product_id": "0x0",
        "product_string": "",
        "report_len": str(DEFAULT_PEDALS_REPORT_LEN),
        "throttle_offset": str(DEFAULT_THROTTLE_OFFSET),
        "brake_offset": str(DEFAULT_BRAKE_OFFSET),
    }

    # Wheel section
    parser["wheel"] = {
        "vendor_id": "0x0",
        "product_id": "0x0",
        "product_string": "",
        "report_len": str(DEFAULT_WHEEL_REPORT_LEN),
        "steering_offset": str(DEFAULT_STEERING_OFFSET),
        "steering_center": str(DEFAULT_STEERING_CENTER),
        "steering_range": str(DEFAULT_STEERING_RANGE),
        "steering_half_range": str(DEFAULT_STEERING_HALF_RANGE),
        "steering_16bit": "true" if DEFAULT_STEERING_16BIT else "false",
    }

    # UI section
    parser["ui"] = {
        "throttle_target": str(DEFAULT_THROTTLE_TARGET),
        "brake_target": str(DEFAULT_BRAKE_TARGET),
        "grid_step_percent": str(DEFAULT_GRID_STEP_PERCENT),
        "update_hz": str(DEFAULT_UPDATE_HZ),
        "show_steering": "true" if DEFAULT_SHOW_STEERING else "false",
        "show_watermark": "true" if DEFAULT_SHOW_WATERMARK else "false",
        "throttle_sound_enabled": "true",
        "throttle_sound_path": "",
        "brake_sound_enabled": "true",
        "brake_sound_path": "",
        "window_width": str(DEFAULT_WINDOW_WIDTH),
        "window_height": str(DEFAULT_WINDOW_HEIGHT),
    }

    # Trail Brake section
    parser["trail_brake"] = {
        "selected_trace": "",
    }

    # Active Brake section
    parser["active_brake"] = {
        "speed": str(DEFAULT_ACTIVE_BRAKE_SPEED),
    }

    with path.open("w", encoding="utf-8") as f:
        parser.write(f)


def _load_device_section(parser: configparser.ConfigParser, section_name: str) -> Optional[dict]:
    if section_name not in parser:
        return None
    section = parser[section_name]
    try:
        return {
            "vendor_id": int(section.get("vendor_id", "").strip(), 0),
            "product_id": int(section.get("product_id", "").strip(), 0),
            "product_string": section.get("product_string", "").strip(),
            "report_len": int(section.get("report_len", "64")),
            "throttle_offset": section.get("throttle_offset"),
            "brake_offset": section.get("brake_offset"),
            "steering_offset": section.get("steering_offset"),
            "steering_center": section.get("steering_center"),
            "steering_range": section.get("steering_range"),
            "steering_half_range": section.get("steering_half_range"),
            "steering_16bit": section.get("steering_16bit", "false").lower() == "true",
        }
    except Exception:
        return None


def load_pedals_config() -> Optional[PedalsConfig]:
    path = config_path()
    if not path.exists():
        return None

    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    data = _load_device_section(parser, "pedals")
    if not data:
        return None
    if data["throttle_offset"] is None or data["brake_offset"] is None:
        return None

    try:
        return PedalsConfig(
            vendor_id=int(data["vendor_id"]),
            product_id=int(data["product_id"]),
            product_string=str(data["product_string"]),
            report_len=int(data["report_len"]),
            throttle_offset=int(data["throttle_offset"]),
            brake_offset=int(data["brake_offset"]),
        )
    except Exception:
        return None


def load_wheel_config() -> Optional[WheelConfig]:
    path = config_path()
    if not path.exists():
        return None

    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    data = _load_device_section(parser, "wheel")
    if not data:
        return None
    if data["steering_offset"] is None:
        return None

    try:
        return WheelConfig(
            vendor_id=int(data["vendor_id"]),
            product_id=int(data["product_id"]),
            product_string=str(data["product_string"]),
            report_len=int(data["report_len"]),
            steering_offset=int(data["steering_offset"]),
            steering_center=int(data["steering_center"] or 128),
            steering_range=int(data["steering_range"] or 900),
            steering_half_range=int(data.get("steering_half_range") or DEFAULT_STEERING_HALF_RANGE),
            steering_16bit=bool(data.get("steering_16bit", False)),
        )
    except Exception:
        return None


def load_input_profile() -> InputProfile:
    """Load the full input profile, creating default config if needed."""
    ensure_config_exists()
    return InputProfile(pedals=load_pedals_config(), wheel=load_wheel_config(), ui=load_ui_config())


def save_pedals_config(cfg: PedalsConfig) -> None:
    parser = configparser.ConfigParser()
    parser.read(config_path(), encoding="utf-8")
    parser["pedals"] = {
        "vendor_id": hex(cfg.vendor_id),
        "product_id": hex(cfg.product_id),
        "product_string": cfg.product_string,
        "report_len": str(cfg.report_len),
        "throttle_offset": str(cfg.throttle_offset),
        "brake_offset": str(cfg.brake_offset),
    }
    path = config_path()
    with path.open("w", encoding="utf-8") as f:
        parser.write(f)


def save_wheel_config(cfg: WheelConfig) -> None:
    parser = configparser.ConfigParser()
    parser.read(config_path(), encoding="utf-8")
    parser["wheel"] = {
        "vendor_id": hex(cfg.vendor_id),
        "product_id": hex(cfg.product_id),
        "product_string": cfg.product_string,
        "report_len": str(cfg.report_len),
        "steering_offset": str(cfg.steering_offset),
        "steering_center": str(int(cfg.steering_center)),
        "steering_range": str(int(cfg.steering_range)),
        "steering_half_range": str(int(cfg.steering_half_range)),
        "steering_16bit": "true" if cfg.steering_16bit else "false",
    }
    path = config_path()
    with path.open("w", encoding="utf-8") as f:
        parser.write(f)


def save_input_profile(profile: InputProfile) -> None:
    if profile.pedals is not None:
        save_pedals_config(profile.pedals)
    if profile.wheel is not None:
        save_wheel_config(profile.wheel)
    if profile.ui is not None:
        save_ui_config(profile.ui)


def load_ui_config() -> Optional[UiConfig]:
    path = config_path()
    if not path.exists():
        return None
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    if "ui" not in parser:
        return None
    section = parser["ui"]
    try:
        return UiConfig(
            throttle_target=int(section.get("throttle_target", "60")),
            brake_target=int(section.get("brake_target", "40")),
            grid_step_percent=int(section.get("grid_step_percent", "10")),
            update_hz=int(section.get("update_hz", "20")),
            show_steering=section.getboolean("show_steering", fallback=False),
            show_watermark=section.getboolean("show_watermark", fallback=True),
            throttle_sound_enabled=section.getboolean("throttle_sound_enabled", fallback=True),
            throttle_sound_path=section.get("throttle_sound_path", fallback="").strip() or None,
            brake_sound_enabled=section.getboolean("brake_sound_enabled", fallback=True),
            brake_sound_path=section.get("brake_sound_path", fallback="").strip() or None,
            window_width=int(section.get("window_width", "1080")),
            window_height=int(section.get("window_height", "600")),
        )
    except Exception:
        return None


def save_ui_config(cfg: UiConfig) -> None:
    parser = configparser.ConfigParser()
    parser.read(config_path(), encoding="utf-8")
    parser["ui"] = {
        "throttle_target": str(int(cfg.throttle_target)),
        "brake_target": str(int(cfg.brake_target)),
        "grid_step_percent": str(int(cfg.grid_step_percent)),
        "update_hz": str(int(cfg.update_hz)),
        "show_steering": "true" if bool(cfg.show_steering) else "false",
        "show_watermark": "true" if bool(cfg.show_watermark) else "false",
        "throttle_sound_enabled": "true" if bool(cfg.throttle_sound_enabled) else "false",
        "throttle_sound_path": cfg.throttle_sound_path or "",
        "brake_sound_enabled": "true" if bool(cfg.brake_sound_enabled) else "false",
        "brake_sound_path": cfg.brake_sound_path or "",
        "window_width": str(int(cfg.window_width)),
        "window_height": str(int(cfg.window_height)),
    }
    path = config_path()
    with path.open("w", encoding="utf-8") as f:
        parser.write(f)


def load_trail_brake_config() -> Optional[TrailBrakeConfig]:
    path = config_path()
    if not path.exists():
        return None
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    if "trail_brake" not in parser:
        return None
    section = parser["trail_brake"]
    try:
        return TrailBrakeConfig(selected_trace=section.get("selected_trace", "").strip())
    except Exception:
        return None


def save_trail_brake_config(cfg: TrailBrakeConfig) -> None:
    parser = configparser.ConfigParser()
    parser.read(config_path(), encoding="utf-8")
    parser["trail_brake"] = {"selected_trace": cfg.selected_trace}
    path = config_path()
    with path.open("w", encoding="utf-8") as f:
        parser.write(f)


def load_active_brake_config() -> ActiveBrakeConfig:
    path = config_path()
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    section = parser["active_brake"] if "active_brake" in parser else {}
    try:
        speed = int(section.get("speed", "60"))
    except Exception:
        speed = 60
    return ActiveBrakeConfig(speed=max(30, min(120, speed)))


def save_active_brake_config(cfg: ActiveBrakeConfig) -> None:
    parser = configparser.ConfigParser()
    parser.read(config_path(), encoding="utf-8")
    parser["active_brake"] = {"speed": str(int(cfg.speed))}
    path = config_path()
    with path.open("w", encoding="utf-8") as f:
        parser.write(f)
