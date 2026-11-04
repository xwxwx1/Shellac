"""Qt models over core.Playlist: the table model and the filtering/sorting proxy in front of it."""
from __future__ import annotations

import json

from PyQt6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, QSortFilterProxyModel, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from ..core.filter import Filter
from ..core.playlist import Playlist
from ..core.song import parse_tags
from ..core.timefmt import format_time

SongRole = Qt.ItemDataRole.UserRole + 1
SortRole = Qt.ItemDataRole.UserRole + 2

COLUMNS = ('Name', 'Length', 'Tags', 'Artist', 'Album', 'Weight')
NAME, LENGTH, TAGS, ARTIST, ALBUM, WEIGHT = range(len(COLUMNS))
EDITABLE = (NAME, TAGS, WEIGHT)

SONGS_MIME = 'application/x-shellac-songs'


def sort_key(song, column):
    if column == LENGTH:
        return song.duration if song.duration is not None else -1.0
    if column == WEIGHT:
        return song.weight
    text = {NAME: song.name, TAGS: ', '.join(song.tags), ARTIST: song.artist, ALBUM: song.album or ''}[column]
    return text.casefold()


class PlaylistModel(QAbstractTableModel):
    songEdited = pyqtSignal(object)  # Song changed by in-place editing

    def __init__(self, parent=None):
        super().__init__(parent)
        self.playlist = Playlist()
        self._playing = None
        self._fonts = {}
        self._missing_color = QColor(150, 150, 150)
        self._sort_keys = (None, None)  # (column, key per row), rebuilt after any change

    # --- read --------------------------------------------------------------------------------

    # index/rowCount run tens of thousands of times per sort, so they skip the usual layers: the
    # base index() would call back into Python twice more (rowCount and columnCount) for each one.
    def index(self, row, column, parent=None):
        in_range = 0 <= row < len(self.playlist._songs) and 0 <= column < len(COLUMNS)
        if in_range and (parent is None or not parent.isValid()):
            return self.createIndex(row, column)
        return QModelIndex()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.playlist._songs)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return COLUMNS[section]
            return str(section + 1)
        if role == Qt.ItemDataRole.ToolTipRole and orientation == Qt.Orientation.Horizontal and section in EDITABLE:
            return 'Press F2 or click a selected cell to edit'
        return None

    def _font(self, bold, italic):
        key = (bold, italic)
        if key not in self._fonts:
            font = QFont()
            font.setBold(bold)
            font.setItalic(italic)
            self._fonts[key] = font
        return self._fonts[key]

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
            if col == ALBUM:
                return song.album or ''
            if col == WEIGHT:
                return song.weight
        elif role == Qt.ItemDataRole.EditRole:
            return {NAME: song.name, TAGS: ', '.join(song.tags), WEIGHT: song.weight}.get(col)
        elif role == SortRole:
            return sort_key(song, col)
        elif role == SongRole:
            return song
        elif role == Qt.ItemDataRole.ToolTipRole:
            return f'{song.path}\n(file not found — right-click › Locate File…)' if song.missing else song.path
        elif role == Qt.ItemDataRole.FontRole and (song is self._playing or song.missing):
            return self._font(song is self._playing, song.missing)
        elif role == Qt.ItemDataRole.ForegroundRole and song.missing:
            return self._missing_color
        elif role == Qt.ItemDataRole.TextAlignmentRole and col in (LENGTH, WEIGHT):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled  # drops land between rows, never on them
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
        if index.column() in EDITABLE:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        song = self.playlist[index.row()]
        col = index.column()
        self._keys_changed()
        if col == NAME:
            name = str(value).strip()
            if not name:
                return False
            self.playlist.update(song, name=name)
        elif col == TAGS:
            self.playlist.update(song, tags=parse_tags(str(value)))
        elif col == WEIGHT:
            try:
                self.playlist.update(song, weight=max(0, int(value)))
            except (TypeError, ValueError):
                return False
        else:
            return False
        self._row_changed(song)
        self.songEdited.emit(song)
        return True

    def song_at(self, row: int):
        return self.playlist[row]

    def sort_keys(self, column) -> list:
        """Sort key of every row for `column`, computed once and reused until the playlist changes."""
        cached_column, keys = self._sort_keys
        if cached_column != column or keys is None:
            keys = [sort_key(song, column) for song in self.playlist]
            self._sort_keys = (column, keys)
        return keys

    def _keys_changed(self):
        # Called before the playlist changes, so the proxy never compares with stale keys while it
        # reacts to the change signals.
        self._sort_keys = (None, None)

    def row_of(self, song) -> int:
        return self.playlist.index(song)

    # --- drag and drop -----------------------------------------------------------------------

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def mimeTypes(self):
        return [SONGS_MIME, 'text/uri-list']

    def mimeData(self, indexes):
        rows = sorted({i.row() for i in indexes})
        data = QMimeData()
        # Only a private type: offering file URLs would let Explorer *move* the files on a drop.
        data.setData(SONGS_MIME, json.dumps([self.playlist[r].path for r in rows]).encode())
        return data

    def canDropMimeData(self, data, action, row, column, parent):
        return data.hasFormat(SONGS_MIME) or data.hasUrls()

    def dropMimeData(self, data, action, row, column, parent):
        return False  # PlaylistView handles drops itself

    # --- write -------------------------------------------------------------------------------

    def add_songs(self, songs, row: int | None = None) -> list:
        songs = self.playlist.new_songs(songs)
        if not songs:
            return []
        row = len(self.playlist) if row is None else max(0, min(row, len(self.playlist)))
        self._keys_changed()
        self.beginInsertRows(QModelIndex(), row, row + len(songs) - 1)
        added = self.playlist.add(songs, row)
        self.endInsertRows()
        return added

    def remove_songs(self, songs) -> list:
        rows = sorted((self.playlist.index(s) for s in songs if s in self.playlist), reverse=True)
        removed = []
        self._keys_changed()
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
        self._keys_changed()
        self.beginResetModel()
        self.playlist.clear()
        self._playing = None
        self.endResetModel()

    def update_song(self, song, name=None, tags=None, weight=None):
        self._keys_changed()
        self.playlist.update(song, name, tags, weight)
        self._row_changed(song)

    def relocate(self, song, path):
        self.playlist.relocate(song, path)  # may raise ValueError
        self._row_changed(song)

    def refresh_missing(self) -> int:
        """Re-check which files exist; returns how many are missing."""
        changed = False
        for song in self.playlist:
            before = song.missing
            changed |= song.check_missing() != before
        if changed and len(self.playlist):
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.playlist) - 1, len(COLUMNS) - 1))
        return sum(s.missing for s in self.playlist)

    def song_changed(self, song):
        if song in self.playlist:
            self._row_changed(song)

    def reorder(self, new_order):
        """Rearrange a subset of songs (see Playlist.reorder), keeping selections attached to their songs."""
        self._keys_changed()
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
    """Shows the songs passing the filter, search text and tag selection; optionally sorted by a column."""

    def __init__(self, source: PlaylistModel, parent=None):
        super().__init__(parent)
        self.setSourceModel(source)
        self._source = source
        self.setSortRole(SortRole)
        self._filter = Filter()
        self._search = ''
        self._tags = ()

    @property
    def filter(self) -> Filter:
        return self._filter

    @property
    def search(self) -> str:
        return self._search

    @property
    def required_tags(self) -> tuple:
        return self._tags

    @property
    def is_sorted(self) -> bool:
        return self.sortColumn() >= 0

    @property
    def is_filtered(self) -> bool:
        return not self._filter.is_empty or bool(self._search) or bool(self._tags)

    def set_filter(self, f: Filter):
        self._filter = f
        self.invalidateFilter()

    def set_search(self, text: str):
        text = text.strip().casefold()
        if text != self._search:
            self._search = text
            self.invalidateFilter()

    def set_required_tags(self, tags):
        tags = tuple(tags)
        if tags != self._tags:
            self._tags = tags
            self.invalidateFilter()

    def _matches_search(self, song) -> bool:
        haystack = '\n'.join([song.name, *song.tags, song.album or '']).casefold()
        return all(word in haystack for word in self._search.split())

    def filterAcceptsRow(self, source_row, source_parent):
        song = self.sourceModel().song_at(source_row)
        return (self._filter.check(song)
                and all(tag in song.tags for tag in self._tags)
                and (not self._search or self._matches_search(song)))

    def lessThan(self, left, right):
        # Qt calls this ~20k times for 2000 rows: look keys up in the model's cached table instead
        # of going through data() (which made a header click take a quarter of a second or more).
        column, keys = self._source._sort_keys
        if keys is None or column != left.column():
            keys = self._source.sort_keys(left.column())
        return keys[left.row()] < keys[right.row()]

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
