"""An ordered collection of unique songs."""
from __future__ import annotations

from collections.abc import Iterable

from .song import Song, path_key


class Playlist:
    def __init__(self, songs: Iterable[Song] = ()):
        self._songs: list[Song] = []
        self._by_key: dict[str, Song] = {}
        self._positions: dict[int, int] | None = None
        self.add(songs)

    def __len__(self):
        return len(self._songs)

    def __iter__(self):
        return iter(self._songs)

    def __getitem__(self, row: int) -> Song:
        return self._songs[row]

    def __contains__(self, song) -> bool:
        return isinstance(song, Song) and self._by_key.get(song.key) is song

    def get(self, path_or_key: str) -> Song | None:
        return self._by_key.get(path_key(path_or_key))

    def index(self, song: Song) -> int:
        """Row of a song in O(1) amortised; raises ValueError if absent."""
        if self._positions is None:
            self._positions = {id(s): i for i, s in enumerate(self._songs)}
        try:
            return self._positions[id(song)]
        except KeyError:
            raise ValueError(f'{song!r} is not in the playlist') from None

    def _changed(self):
        self._positions = None

    def new_songs(self, songs: Iterable[Song]) -> list[Song]:
        """The songs that add() would accept: not already present (by file), first occurrence only."""
        seen = set()
        result = []
        for song in songs:
            if song.key not in self._by_key and song.key not in seen:
                seen.add(song.key)
                result.append(song)
        return result

    def add(self, songs: Iterable[Song], position: int | None = None) -> list[Song]:
        """Insert songs at position (default: end), skipping files already present. Returns those added."""
        added = self.new_songs(songs)
        if position is None or position > len(self._songs):
            position = len(self._songs)
        self._songs[position:position] = added
        for song in added:
            self._by_key[song.key] = song
        self._changed()
        return added

    def remove(self, songs: Iterable[Song]) -> list[Song]:
        doomed = {id(s) for s in songs if s in self}
        removed = [s for s in self._songs if id(s) in doomed]
        self._songs = [s for s in self._songs if id(s) not in doomed]
        for song in removed:
            del self._by_key[song.key]
        self._changed()
        return removed

    def clear(self):
        self._songs.clear()
        self._by_key.clear()
        self._changed()

    def reorder(self, new_order: list[Song]):
        """Rearrange a subset of songs into new_order, leaving every other song where it is.

        The subset's current rows are refilled in the new order, so reordering the songs visible
        through a filter never disturbs the hidden ones.
        """
        slots = sorted(self.index(s) for s in new_order)
        if len(set(map(id, new_order))) != len(new_order):
            raise ValueError('new_order contains duplicates')
        for row, song in zip(slots, new_order):
            self._songs[row] = song
        self._changed()

    def relocate(self, song: Song, new_path: str):
        """Point a song at a different file (e.g. one that was moved). Raises ValueError if that file is
        already another song in the playlist."""
        new_key = path_key(new_path)
        other = self._by_key.get(new_key)
        if other is not None and other is not song:
            raise ValueError(f'{new_path} is already in the playlist as "{other.name}"')
        del self._by_key[song.key]
        song.path = new_path
        song.__post_init__()
        self._by_key[song.key] = song
        song.check_missing()

    def update(self, song: Song, name: str | None = None, tags: list[str] | None = None,
               weight: int | None = None):
        if name is not None:
            song.name = name
        if tags is not None:
            song.tags = list(tags)
        if weight is not None:
            song.weight = weight

    def all_tags(self) -> list[str]:
        tags = {}
        for song in self._songs:
            tags.update(dict.fromkeys(song.tags))
        return list(tags)
