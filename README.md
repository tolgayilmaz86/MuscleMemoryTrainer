# Muscle Memory Trainer

PySide6 desktop app for practicing throttle, brake, and steering muscle memory with live telemetry, device calibration, and training modes.

## Prerequisites
- Python 3.10+
- Windows for packaging via the provided spec (dev also works on other platforms)
- Optional: HID hardware (pedals/wheel). Without it, the app simulates input.

## Quick start (development)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
python -m mmt_app
```

## Build a standalone exe (PyInstaller)
```powershell
pyinstaller --clean --noconfirm mmt_app.spec
```
- Output: `dist/MuscleMemoryTrainer/MuscleMemoryTrainer.exe` (one-folder build).
- Icon: set via `src/mmt_app/resources/appicon.ico` in the spec; replace that file to change the Explorer/taskbar icon.
- One-file option: set `onefile=True` in `EXE(...)` inside `mmt_app.spec` (slower startup).

## Project layout
- `src/mmt_app/`
  - `main.py` – entrypoint for CLI and PyInstaller.
  - `app.py` – Qt application bootstrap (resources, window factory).
  - `ui/` – UI widgets (`main_window.py`, training tabs, charts).
  - `resources/` – icons, styles, sounds (`app.qrc` lists them).
- `mmt_app.spec` – PyInstaller spec (copies resources and embeds icon).
- `tests/` – smoke tests for resource paths.

## Running tests
```powershell
pytest
```

## Key libraries
- PySide6 (Qt for Python)
- hidapi (raw HID access for pedals/wheel)

## App features
- Live telemetry chart with throttle/brake/steering and target lines (steering trace can be toggled).
- Input settings: select HID devices, set report lengths/offsets, and auto-calibrate per axis.
- Static Brake training: follow predefined traces; save/import/export custom traces.
- Active Brake training: react to moving targets; adjustable update rate.
- Sounds: optional cues when targets are hit.

## Configuration persistence
- Settings (targets, grid, sounds, update rate, steering visibility) and device mappings are written to `config.ini` in your user config directory (`QStandardPaths.AppConfigLocation`).
- HID mappings include vendor/product IDs, report lengths, and byte offsets.

## Resources
- Assets live in `src/mmt_app/resources/` and are copied at build time via the spec.
- Optional: compile Qt resources to Python with `pyside6-rcc src/mmt_app/resources/app.qrc -o src/mmt_app/resources/resources_rc.py` (not required for PyInstaller because the spec bundles raw files).

## Troubleshooting
- HID input missing: ensure `hidapi` is installed; otherwise the app falls back to simulated input.
- Blank window in packaged build: confirm `dist/MuscleMemoryTrainer/resources/` exists and contains styles/sounds/icons.
