"""Back/forward navigation over played songs, like a browser history."""
from __future__ import annotations


class History:
    def __init__(self):
        self._items = []
        self._cursor = -1

    def __len__(self):
        return len(self._items)

    @property
    def current(self):
        return self._items[self._cursor] if self._cursor >= 0 else None

    def push(self, song):
        """Record a newly chosen song, discarding anything ahead of the cursor."""
        del self._items[self._cursor + 1:]
        if self.current is not song:
            self._items.append(song)
        self._cursor = len(self._items) - 1

    def back(self):
        if self._cursor <= 0:
            return None
        self._cursor -= 1
        return self._items[self._cursor]

    def forward(self):
        if self._cursor >= len(self._items) - 1:
            return None
        self._cursor += 1
        return self._items[self._cursor]

    def remove(self, songs):
        """Forget songs (e.g. deleted from the playlist), keeping the cursor on the same entry if possible."""
        doomed = {id(s) for s in songs}
        kept = []
        cursor = -1
        for i, song in enumerate(self._items):
            if id(song) in doomed:
                continue
            # Collapse repeats that removal would make adjacent.
            if kept and kept[-1] is song:
                if i <= self._cursor:
                    cursor = len(kept) - 1
                continue
            kept.append(song)
            if i <= self._cursor:
                cursor = len(kept) - 1
        self._items = kept
        self._cursor = cursor

    def clear(self):
        self._items.clear()
        self._cursor = -1
