from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QSpinBox

from ...core.song import parse_tags


class SongDialog(QDialog):
    """Edit a song's name, tags and weight (used for both adding and editing)."""

    def __init__(self, parent, title, name='', tags=(), weight=1, path=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        self.name_edit = QLineEdit(name)
        self.tags_edit = QLineEdit(', '.join(tags))
        self.tags_edit.setPlaceholderText('Artist, tag, tag…')
        self.weight_edit = QSpinBox()
        self.weight_edit.setRange(0, 999)
        self.weight_edit.setValue(weight)
        self.weight_edit.setToolTip('Relative chance of being picked in shuffle mode (0 = never)')

        form = QFormLayout(self)
        if path:
            location = QLabel(path)
            location.setWordWrap(True)
            form.addRow('File:', location)
        form.addRow('Name:', self.name_edit)
        form.addRow('Tags:', self.tags_edit)
        form.addRow('', QLabel('Separate tags with commas. The first tag is the artist.'))
        form.addRow('Weight:', self.weight_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.name_edit.setSelection(len(name), -len(name))  # select all, but show the start

    def accept(self):
        if not self.name.strip():
            QMessageBox.warning(self, self.windowTitle(), 'Please enter a name.')
            return
        super().accept()

    @property
    def name(self) -> str:
        return self.name_edit.text().strip()

    @property
    def tags(self) -> list[str]:
        return parse_tags(self.tags_edit.text())

    @property
    def weight(self) -> int:
        return self.weight_edit.value()
