"""Reading song metadata off the GUI thread."""
from __future__ import annotations

import os

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from ..core.playlist_io import PlaylistEntry
from ..core.song import is_audio_file, song_from_file

BATCH = 50


def expand_paths(paths):
    """Files stay as they are; folders become the audio files inside them, sorted, recursively."""
    for path in paths:
        if isinstance(path, PlaylistEntry):
            yield path
        elif os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs.sort(key=str.casefold)
                for name in sorted(files, key=str.casefold):
                    if is_audio_file(name):
                        yield PlaylistEntry(os.path.join(root, name))
        else:
            yield PlaylistEntry(path)


class _Signals(QObject):
    batch = pyqtSignal(list)
    done = pyqtSignal()


class _ScanTask(QRunnable):
    def __init__(self, items, signals, artist_as_tag):
        super().__init__()
        self._items = items
        self._signals = signals
        self._artist_as_tag = artist_as_tag

    def run(self):
        batch = []
        for entry in expand_paths(self._items):
            # Playlist entries carry the user's own tags (even an empty list), so leave them alone.
            seed = self._artist_as_tag and not entry.name and not entry.tags
            batch.append(song_from_file(entry.path, entry.name, entry.tags, entry.weight, artist_as_tag=seed))
            if len(batch) >= BATCH:
                self._signals.batch.emit(batch)
                batch = []
        if batch:
            self._signals.batch.emit(batch)
        self._signals.done.emit()


class Scanner(QObject):
    """Turns paths/folders/playlist entries into Songs in the background, emitting them in order."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._active = set()

    def scan(self, items, on_batch, on_done=None, artist_as_tag=False):
        """items: file/folder paths or PlaylistEntry objects. Callbacks run on the GUI thread."""
        signals = _Signals(self)  # owned here, so signals are delivered via the GUI thread's queue
        self._active.add(signals)
        signals.batch.connect(on_batch)

        def finished():
            self._active.discard(signals)
            signals.deleteLater()
            if on_done:
                on_done()
        signals.done.connect(finished)
        self._pool.start(_ScanTask(list(items), signals, artist_as_tag))

    @property
    def busy(self) -> bool:
        return bool(self._active)

    def wait(self, msecs=-1):
        return self._pool.waitForDone(msecs)
