"""Sound manager for target sound playback.

Handles audio playback for throttle/brake target hits with file path
resolution and fallback to embedded sounds.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from mmt_app.embedded_sound import get_embedded_sound_path, is_builtin_sound_path

if TYPE_CHECKING:
    from collections.abc import Mapping


class SoundManager:
    """Manages sound playback for target hit notifications.

    Supports throttle and brake sounds with customizable file paths
    and enable/disable toggles per sound type.

    Attributes:
        default_sound_path: Path to the embedded default sound.
    """

    VALID_EXTENSIONS = {".mp3", ".wav", ".ogg"}

    def __init__(self) -> None:
        """Initialize the sound manager with default settings."""
        self._default_sound_path = get_embedded_sound_path()
        self._sound_paths: dict[str, str] = {}
        self._sound_enabled: dict[str, bool] = {}

        # Media player setup
        self._media_player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._media_player.setAudioOutput(self._audio_output)

    @property
    def default_sound_path(self) -> Path:
        """Return the path to the embedded default sound."""
        return self._default_sound_path

    def set_enabled(self, kind: str, enabled: bool) -> None:
        """Enable or disable a sound type.

        Args:
            kind: Sound type identifier (e.g., 'throttle', 'brake').
            enabled: Whether the sound should be enabled.
        """
        self._sound_enabled[kind] = enabled

    def is_enabled(self, kind: str) -> bool:
        """Check if a sound type is enabled.

        Args:
            kind: Sound type identifier.

        Returns:
            True if enabled, False otherwise. Defaults to True.
        """
        return self._sound_enabled.get(kind, True)

    def set_path(self, kind: str, path: str | Path | None) -> None:
        """Set the sound file path for a given type.

        Args:
            kind: Sound type identifier.
            path: Path to the sound file, or None to use the default sound.
        """
        if is_builtin_sound_path(path):
            self._sound_paths.pop(kind, None)
            return
        self._sound_paths[kind] = str(Path(path).expanduser())

    def custom_path(self, kind: str) -> str | None:
        """Return the user-selected sound file, or None when using the default.

        Args:
            kind: Sound type identifier.
        """
        return self._sound_paths.get(kind) or None

    def get_path(self, kind: str) -> str:
        """Get the configured sound path, falling back to default.

        Args:
            kind: Sound type identifier.

        Returns:
            The configured path or the default embedded sound path.
        """
        path = self._sound_paths.get(kind, "").strip()
        if path and Path(path).exists():
            return path
        return str(self._default_sound_path)

    def resolve_path(self, kind: str) -> Path:
        """Resolve the actual path to use for a sound type.

        Falls back to default sound if the configured path doesn't exist.

        Args:
            kind: Sound type identifier.

        Returns:
            Path object to the sound file.
        """
        path = Path(self.get_path(kind))
        if not path.exists():
            path = self._default_sound_path
        return path

    def play(self, kind: str) -> None:
        """Play the sound for a given type if enabled and valid.

        Args:
            kind: Sound type identifier.
        """
        if not self.is_enabled(kind):
            return
        self.preview(kind)

    def preview(self, kind: str) -> None:
        """Play the sound for a given type even if it is disabled.

        Args:
            kind: Sound type identifier.
        """
        path = self.resolve_path(kind)

        if not path.exists() or path.suffix.lower() not in self.VALID_EXTENSIONS:
            return

        try:
            self._media_player.stop()
            self._media_player.setSource(QUrl.fromLocalFile(str(path)))
            self._audio_output.setVolume(1.0)
            self._media_player.play()
        except Exception:
            pass  # Silently fail on playback errors

    def apply_settings(
        self,
        *,
        throttle_enabled: bool,
        throttle_path: str | None,
        brake_enabled: bool,
        brake_path: str | None,
    ) -> None:
        """Apply persisted sound settings.

        Args:
            throttle_enabled: Whether throttle sound is enabled.
            throttle_path: Path to throttle sound file.
            brake_enabled: Whether brake sound is enabled.
            brake_path: Path to brake sound file.
        """
        self.set_enabled("throttle", throttle_enabled)
        self.set_enabled("brake", brake_enabled)
        self.set_path("throttle", throttle_path)
        self.set_path("brake", brake_path)

    def get_settings(self) -> dict[str, bool | str | None]:
        """Get current sound settings for persistence.

        Returns:
            Dictionary with enabled states and custom paths (None = default sound).
        """
        return {
            "throttle_sound_enabled": self.is_enabled("throttle"),
            "throttle_sound_path": self.custom_path("throttle"),
            "brake_sound_enabled": self.is_enabled("brake"),
            "brake_sound_path": self.custom_path("brake"),
        }
