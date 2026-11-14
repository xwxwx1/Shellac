import json

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QTableView

from ..playlist_model import SONGS_MIME


class PlaylistView(QTableView):
    """The playlist table. Rows can be dragged to reorder them, and files dropped between rows."""

    songsMoved = pyqtSignal(list, int)     # song paths, visible row to insert before (rowCount = end)
    filesDropped = pyqtSignal(list, int)   # file paths, visible row to insert before

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.setDropIndicatorShown(True)

    def keyboardSearch(self, search):
        # Letter keys are shortcuts (e.g. L for loop), not type-to-search.
        pass

    def _drop_row(self, event) -> int:
        index = self.indexAt(event.position().toPoint())
        if not index.isValid():
            return self.model().rowCount()
        below = self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem
        return index.row() + (1 if below else 0)

    def dropEvent(self, event):
        mime = event.mimeData()
        row = self._drop_row(event)
        if mime.hasFormat(SONGS_MIME) and event.source() is self:
            self.songsMoved.emit(json.loads(bytes(mime.data(SONGS_MIME)).decode('utf-8')), row)
        elif mime.hasUrls():
            paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
            if paths:
                self.filesDropped.emit(paths, row)
        # The base class only tidies up here (auto-scroll, drop indicator): the model's dropMimeData
        # declines, so it changes nothing itself.
        super().dropEvent(event)
        # Report a copy so the drag source never tries to delete the dragged rows itself.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
