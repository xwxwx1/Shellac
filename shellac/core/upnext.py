"""The up-next queue: songs to play before the loop mode picks anything."""
from __future__ import annotations


class UpNext:
    def __init__(self):
        self._items = []

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, i):
        return self._items[i]

    def play_next(self, songs):
        """Put songs at the front, in the given order."""
        self._items[0:0] = list(songs)

    def append(self, songs):
        self._items.extend(songs)

    def pop(self, is_available=lambda song: True):
        """Remove and return the first song that is still available, or None."""
        while self._items:
            song = self._items.pop(0)
            if is_available(song):
                return song
        return None

    def remove(self, songs):
        doomed = {id(s) for s in songs}
        self._items = [s for s in self._items if id(s) not in doomed]

    def remove_at(self, indices):
        doomed = set(indices)
        self._items = [s for i, s in enumerate(self._items) if i not in doomed]

    def move(self, index, delta):
        target = index + delta
        if 0 <= index < len(self._items) and 0 <= target < len(self._items):
            self._items[index], self._items[target] = self._items[target], self._items[index]
            return target
        return index

    def clear(self):
        self._items.clear()
