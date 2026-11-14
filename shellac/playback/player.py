"""Audio playback driven by Qt signals instead of polling."""
from __future__ import annotations

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

MAX_VOLUME = 150  # the volume slider's top end, in percent


class AudioPlayer(QObject):
    """One long-lived QMediaPlayer. Times are in seconds."""

    positionChanged = pyqtSignal(float)
    durationChanged = pyqtSignal(float)
    playingChanged = pyqtSignal(bool)
    ended = pyqtSignal()
    errorOccurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._output = QAudioOutput(self)
        self._player.setAudioOutput(self._output)
        self._devices = QMediaDevices(self)
        self._volume = 100
        self._muted = False
        self._pending_position = None  # seconds to seek to once the media has loaded
        self._apply_volume()

        self._player.positionChanged.connect(lambda ms: self.positionChanged.emit(ms / 1000))
        self._player.durationChanged.connect(lambda ms: self.durationChanged.emit(ms / 1000))
        self._player.playbackStateChanged.connect(
            lambda state: self.playingChanged.emit(state == QMediaPlayer.PlaybackState.PlayingState))
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(self._on_error)
        # Follow the system default output when devices are plugged in, removed, or switched.
        self._devices.audioOutputsChanged.connect(self._follow_default_device)

    # --- state -------------------------------------------------------------------------------

    @property
    def has_media(self) -> bool:
        return not self._player.source().isEmpty()

    @property
    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @property
    def position(self) -> float:
        return self._player.position() / 1000

    @property
    def duration(self) -> float:
        return self._player.duration() / 1000

    @property
    def volume(self) -> int:
        return self._volume

    @property
    def muted(self) -> bool:
        return self._muted

    # --- control -----------------------------------------------------------------------------

    def play_file(self, path: str):
        self._pending_position = None
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def load(self, path: str, position: float = 0.0):
        """Load a file paused, ready to resume at `position` (used to restore the last session)."""
        self._pending_position = position if position > 0 else None
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.pause()

    def play(self):
        if self.has_media:
            self._player.play()

    def pause(self):
        self._player.pause()

    def toggle(self):
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def stop(self):
        # Clearing the source stops playback too. Calling QMediaPlayer.stop() first can deadlock in Qt's
        # FFmpeg backend when a track was started moments earlier (reproduced with Qt 6.11).
        self._pending_position = None
        self._player.setSource(QUrl())

    def seek(self, seconds: float):
        if self.has_media:
            self._player.setPosition(max(0, round(seconds * 1000)))

    def set_volume(self, percent: int):
        self._volume = max(0, min(MAX_VOLUME, int(percent)))
        self._apply_volume()

    def set_muted(self, muted: bool):
        self._muted = bool(muted)
        self._apply_volume()

    def _apply_volume(self):
        # The slider's 0..150% maps linearly onto Qt's 0..1
        self._output.setVolume(0.0 if self._muted else self._volume / MAX_VOLUME)

    # --- signal handlers ---------------------------------------------------------------------

    def _on_status(self, status):
        loaded = status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia)
        if loaded and self._pending_position is not None:
            position, self._pending_position = self._pending_position, None
            self.seek(position)
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.ended.emit()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia and self._player.error() == QMediaPlayer.Error.NoError:
            # Usually errorOccurred reports this; only speak up if it didn't.
            self.errorOccurred.emit(f'Cannot play {self._player.source().toLocalFile()}')

    def _on_error(self, error, message):
        if error != QMediaPlayer.Error.NoError:
            self.errorOccurred.emit(message or f'Playback error: {error.name}')

    def _follow_default_device(self):
        self._output.setDevice(QMediaDevices.defaultAudioOutput())
