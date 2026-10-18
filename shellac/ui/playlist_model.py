"""Qt models over core.Playlist: the table model and the filtering proxy in front of it."""
from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QFont

from ..core.filter import Filter
from ..core.playlist import Playlist
from ..core.timefmt import format_time

SongRole = Qt.ItemDataRole.UserRole + 1

COLUMNS = ('Name', 'Length', 'Tags', 'Artist', 'Weight')
NAME, LENGTH, TAGS, ARTIST, WEIGHT = range(len(COLUMNS))


class PlaylistModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.playlist = Playlist()
        self._playing = None
        self._bold = QFont()
        self._bold.setBold(True)

    # --- read --------------------------------------------------------------------------------

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.playlist)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return COLUMNS[section]
            return str(section + 1)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        song = self.playlist[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == NAME:
                return f'▶  {song.name}' if song is self._playing else song.name
            if col == LENGTH:
                return format_time(song.duration)
            if col == TAGS:
                return ', '.join(song.tags)
            if col == ARTIST:
                return song.artist
            if col == WEIGHT:
                return song.weight
        elif role == SongRole:
            return song
        elif role == Qt.ItemDataRole.ToolTipRole:
            return song.path if song.exists else f'{song.path}\n(file not found)'
        elif role == Qt.ItemDataRole.FontRole and song is self._playing:
            return self._bold
        elif role == Qt.ItemDataRole.TextAlignmentRole and col in (LENGTH, WEIGHT):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def song_at(self, row: int):
        return self.playlist[row]

    def row_of(self, song) -> int:
        return self.playlist.index(song)

    # --- write -------------------------------------------------------------------------------

    def add_songs(self, songs, row: int | None = None) -> list:
        songs = self.playlist.new_songs(songs)
        if not songs:
            return []
        row = len(self.playlist) if row is None else max(0, min(row, len(self.playlist)))
        self.beginInsertRows(QModelIndex(), row, row + len(songs) - 1)
        added = self.playlist.add(songs, row)
        self.endInsertRows()
        return added

    def remove_songs(self, songs) -> list:
        rows = sorted((self.playlist.index(s) for s in songs if s in self.playlist), reverse=True)
        removed = []
        # Remove contiguous runs from the bottom up so earlier rows stay valid.
        while rows:
            last = first = rows.pop(0)
            while rows and rows[0] == first - 1:
                first = rows.pop(0)
            run = [self.playlist[r] for r in range(first, last + 1)]
            self.beginRemoveRows(QModelIndex(), first, last)
            removed[:0] = self.playlist.remove(run)
            self.endRemoveRows()
        if self._playing in removed:
            self._playing = None
        return removed

    def clear(self):
        self.beginResetModel()
        self.playlist.clear()
        self._playing = None
        self.endResetModel()

    def update_song(self, song, name=None, tags=None, weight=None):
        self.playlist.update(song, name, tags, weight)
        self._row_changed(song)

    def reorder(self, new_order):
        """Rearrange a subset of songs (see Playlist.reorder), keeping selections attached to their songs."""
        self.layoutAboutToBeChanged.emit()
        old = self.persistentIndexList()
        anchors = [(self.playlist[i.row()], i.column()) for i in old]
        self.playlist.reorder(new_order)
        self.changePersistentIndexList(old, [self.index(self.playlist.index(s), c) for s, c in anchors])
        self.layoutChanged.emit()

    def set_playing(self, song):
        previous, self._playing = self._playing, song
        for s in (previous, song):
            if s is not None and s in self.playlist:
                self._row_changed(s)

    def _row_changed(self, song):
        row = self.playlist.index(song)
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))


class FilterProxy(QSortFilterProxyModel):
    """Shows the songs passing a core Filter, in playlist order."""

    def __init__(self, source: PlaylistModel, parent=None):
        super().__init__(parent)
        self.setSourceModel(source)
        self._filter = Filter()

    @property
    def filter(self) -> Filter:
        return self._filter

    def set_filter(self, f: Filter):
        self._filter = f
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        return self._filter.check(self.sourceModel().song_at(source_row))

    def song_at(self, row: int):
        return self.index(row, 0).data(SongRole)

    def visible_songs(self) -> list:
        return [self.song_at(r) for r in range(self.rowCount())]

    def row_of(self, song) -> int:
        """Visible row of a song, or -1 if it is filtered out or absent."""
        source = self.sourceModel()
        if song not in source.playlist:
            return -1
        return self.mapFromSource(source.index(source.row_of(song), 0)).row()
