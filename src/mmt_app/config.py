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
    throttle_sound_enabled: bool = True
    throttle_sound_path: str | None = None
    brake_sound_enabled: bool = True
    brake_sound_path: str | None = None


@dataclass(frozen=True)
class StaticBrakeConfig:
    """Persistence for Static Brake mode."""

    selected_trace: str


@dataclass(frozen=True)
class ActiveBrakeConfig:
    """Persistence for Active Brake mode."""

    grid_step_percent: int


def config_path() -> Path:
    config_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.ini"


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
            steering_range=int(data["steering_range"] or 127),
        )
    except Exception:
        return None


def load_input_profile() -> InputProfile:
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
            throttle_sound_enabled=section.getboolean("throttle_sound_enabled", fallback=True),
            throttle_sound_path=section.get("throttle_sound_path", fallback="").strip() or None,
            brake_sound_enabled=section.getboolean("brake_sound_enabled", fallback=True),
            brake_sound_path=section.get("brake_sound_path", fallback="").strip() or None,
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
        "throttle_sound_enabled": "true" if bool(cfg.throttle_sound_enabled) else "false",
        "throttle_sound_path": cfg.throttle_sound_path or "",
        "brake_sound_enabled": "true" if bool(cfg.brake_sound_enabled) else "false",
        "brake_sound_path": cfg.brake_sound_path or "",
    }
    path = config_path()
    with path.open("w", encoding="utf-8") as f:
        parser.write(f)


def load_static_brake_config() -> Optional[StaticBrakeConfig]:
    path = config_path()
    if not path.exists():
        return None
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    if "static_brake" not in parser:
        return None
    section = parser["static_brake"]
    try:
        return StaticBrakeConfig(selected_trace=section.get("selected_trace", "").strip())
    except Exception:
        return None


def save_static_brake_config(cfg: StaticBrakeConfig) -> None:
    parser = configparser.ConfigParser()
    parser.read(config_path(), encoding="utf-8")
    parser["static_brake"] = {"selected_trace": cfg.selected_trace}
    path = config_path()
    with path.open("w", encoding="utf-8") as f:
        parser.write(f)


def load_static_brake_traces() -> dict[str, list[int]]:
    """Load user-defined static brake traces from config.ini."""
    path = config_path()
    if not path.exists():
        return {}
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    if "static_brake_traces" not in parser:
        return {}
    section = parser["static_brake_traces"]
    traces: dict[str, list[int]] = {}
    for name, raw in section.items():
        try:
            points = json.loads(raw)
            if isinstance(points, list) and points and all(isinstance(p, int) for p in points):
                traces[name] = [max(0, min(100, int(p))) for p in points]
        except Exception:
            continue
    return traces


def save_static_brake_trace(name: str, points: list[int]) -> None:
    """Save a user-defined static brake trace to config.ini."""
    safe_name = name.strip()
    if not safe_name:
        raise ValueError("Trace name must not be empty")
    normalized = [max(0, min(100, int(p))) for p in points]

    parser = configparser.ConfigParser()
    parser.read(config_path(), encoding="utf-8")
    if "static_brake_traces" not in parser:
        parser["static_brake_traces"] = {}
    parser["static_brake_traces"][safe_name] = json.dumps(normalized, separators=(",", ":"))
    path = config_path()
    with path.open("w", encoding="utf-8") as f:
        parser.write(f)


def load_active_brake_config() -> ActiveBrakeConfig:
    path = config_path()
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    section = parser["active_brake"] if "active_brake" in parser else {}
    try:
        step = int(section.get("grid_step_percent", "10"))
    except Exception:
        step = 10
    return ActiveBrakeConfig(grid_step_percent=max(5, min(50, step)))


def save_active_brake_config(cfg: ActiveBrakeConfig) -> None:
    parser = configparser.ConfigParser()
    parser.read(config_path(), encoding="utf-8")
    parser["active_brake"] = {"grid_step_percent": str(int(cfg.grid_step_percent))}
    path = config_path()
    with path.open("w", encoding="utf-8") as f:
        parser.write(f)
