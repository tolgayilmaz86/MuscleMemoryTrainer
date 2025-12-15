"""Embedded default sound for target notifications."""

import base64
import tempfile
from pathlib import Path

# Embedded beep.mp3 as base64 (small notification sound)
_BEEP_MP3_BASE64 = "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"

_temp_sound_file: Path | None = None


def get_embedded_sound_path() -> Path:
    """Get the path to the embedded sound file.

    Creates a temporary file on first call and returns its path.
    The temp file persists for the lifetime of the application.

    Returns:
        Path to the temporary MP3 file.
    """
    global _temp_sound_file

    if _temp_sound_file is None or not _temp_sound_file.exists():
        # Decode base64 and write to temp file
        sound_data = base64.b64decode(_BEEP_MP3_BASE64)
        # Create temp file that won't be auto-deleted
        fd, path = tempfile.mkstemp(suffix=".mp3", prefix="mmt_beep_")
        _temp_sound_file = Path(path)
        with open(fd, "wb") as f:
            f.write(sound_data)

    return _temp_sound_file
