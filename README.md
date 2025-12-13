# Muscle Memory Trainer (PySide6)

A minimal PySide6 desktop starter that you can run directly or package as a standalone executable with PyInstaller.

## Setup
- Create a virtual environment and install deps:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -e .[dev]
  ```
- Run the app:
  ```powershell
  python -m mmt_app
  ```

## Project layout
- `src/mmt_app/` — application package
  - `main.py` — entry point used by CLI and PyInstaller
  - `app.py` — application bootstrap (paths, style, main window factory)
  - `ui/` — UI widgets (starts with `main_window.py`)
  - `resources/` — assets; `app.qrc` lists them for Qt's resource system
- `mmt_app.spec` — PyInstaller spec checked in for repeatable builds
- `tests/` — minimal smoke test for resource paths

## Resources
- Keep canonical assets listed in `src/mmt_app/resources/app.qrc`.
- Optional: compile to Python with `pyside6-rcc src/mmt_app/resources/app.qrc -o src/mmt_app/resources/resources_rc.py`.
- When packaging with PyInstaller, assets are copied via the spec (`datas` entry) so no compile step is required.

## Build an executable (PyInstaller)
- One-folder build using the provided spec:
  ```powershell
  pyinstaller mmt_app.spec --noconfirm
  ```
- Output appears under `dist/MuscleMemoryTrainer/`. Test on a clean machine to confirm Qt plugins and resources are present.
- Customize:
  - Add an icon via `icon="path/to/app.ico"` inside `EXE(...)`.
  - Switch to one-file by setting `onefile=True` in `EXE(...)` (trade-off: slower startup due to extraction).

## Development tips
- Keep business logic out of UI slots; place it in `services/` or `models/` modules if the app grows.
- Use `resource_path()` from `app.py` whenever you need to read bundled assets, so paths work both in dev and in packaged builds.
- Run `pytest` for quick checks; add more tests around non-UI logic as the app evolves.
