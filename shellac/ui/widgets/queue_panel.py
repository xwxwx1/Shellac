from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class QueuePanel(QWidget):
    """Shows and edits the up-next queue. Songs here play before the loop mode picks anything."""

    changed = pyqtSignal()
    playRequested = pyqtSignal(object)  # Song to play right away (taken out of the queue)

    def __init__(self, queue, parent=None):
        super().__init__(parent)
        self._queue = queue
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(self._play_item)
        self.empty_label = QLabel('Nothing queued.\nRight-click songs › Play Next or Add to Up Next.')
        self.empty_label.setWordWrap(True)

        up = QPushButton('Up')
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton('Down')
        down.clicked.connect(lambda: self._move(1))
        remove = QPushButton('Remove')
        remove.clicked.connect(self._remove_selected)
        clear = QPushButton('Clear')
        clear.clicked.connect(self.clear)
        QShortcut(QKeySequence('Delete'), self.list, self._remove_selected)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        for b in (up, down, remove, clear):
            row.addWidget(b)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        selected = {i.row() for i in self.list.selectedIndexes()}
        self.list.clear()
        for i, song in enumerate(self._queue, 1):
            self.list.addItem(f'{i}. {song.name}')
        for row in selected:
            if row < self.list.count():
                self.list.item(row).setSelected(True)
        self.empty_label.setVisible(len(self._queue) == 0)

    def _selected_rows(self):
        return sorted({i.row() for i in self.list.selectedIndexes()})

    def _move(self, delta):
        rows = self._selected_rows()
        if len(rows) != 1:
            return
        target = self._queue.move(rows[0], delta)
        self.refresh()
        self.list.clearSelection()
        self.list.item(target).setSelected(True)
        self.list.setCurrentRow(target)
        self.changed.emit()

    def _remove_selected(self):
        rows = self._selected_rows()
        if rows:
            self._queue.remove_at(rows)
            self.list.clearSelection()
            self.refresh()
            self.changed.emit()

    def clear(self):
        self._queue.clear()
        self.refresh()
        self.changed.emit()

    def _play_item(self, item):
        row = self.list.row(item)
        song = self._queue[row]
        self._queue.remove_at([row])
        self.refresh()
        self.changed.emit()
        self.playRequested.emit(song)
