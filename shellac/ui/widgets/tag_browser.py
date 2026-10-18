from collections import Counter

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

TagRole = Qt.ItemDataRole.UserRole + 1


class TagBrowser(QWidget):
    """Every tag in the playlist with its song count. Checked tags narrow the playlist (all must match)."""

    tagsChanged = pyqtSignal(list)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self._model = model
        self._checked = []

        self.find = QLineEdit()
        self.find.setPlaceholderText('Find tag…')
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self._apply_find)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.itemDoubleClicked.connect(self._only)
        self.list.setToolTip('Tick tags to show only songs that have all of them.\nDouble-click: just this tag.')
        self.summary = QLabel()
        clear = QPushButton('Clear')
        clear.clicked.connect(lambda: self.set_checked([]))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.find)
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(self.summary, 1)
        row.addWidget(clear)
        layout.addLayout(row)

        # Rebuilding on every inserted batch would be wasteful; coalesce changes.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh)
        for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset, model.dataChanged):
            signal.connect(self._timer.start)
        self.refresh()

    @property
    def checked(self) -> list:
        return list(self._checked)

    def set_checked(self, tags):
        self._checked = [t for t in tags]
        self.refresh()
        self.tagsChanged.emit(self.checked)

    def refresh(self):
        counts = Counter(tag for song in self._model.playlist for tag in song.tags)
        shown = {self.list.item(i).data(TagRole): self.list.item(i).checkState() == Qt.CheckState.Checked
                 for i in range(self.list.count())}
        if counts == getattr(self, '_counts', None) and shown == {t: t in self._checked for t in counts}:
            return  # nothing changed (e.g. only the playing song did); keep the scroll position
        self._counts = counts
        self.list.blockSignals(True)
        self.list.clear()
        for tag in sorted(counts, key=str.casefold):
            item = QListWidgetItem(f'{tag}  ({counts[tag]})')
            item.setData(TagRole, tag)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if tag in self._checked else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._apply_find()
        self.summary.setText(f'{len(counts)} tags')
        # A ticked tag that no longer exists would hide everything; drop it.
        still_there = [t for t in self._checked if t in counts]
        if still_there != self._checked:
            self._checked = still_there
            self.tagsChanged.emit(self.checked)

    def _apply_find(self):
        needle = self.find.text().strip().casefold()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(bool(needle) and needle not in item.data(TagRole).casefold())

    def _on_item_changed(self, item):
        tag = item.data(TagRole)
        if item.checkState() == Qt.CheckState.Checked and tag not in self._checked:
            self._checked.append(tag)
        elif item.checkState() != Qt.CheckState.Checked and tag in self._checked:
            self._checked.remove(tag)
        self.tagsChanged.emit(self.checked)

    def _only(self, item):
        self.set_checked([item.data(TagRole)])
