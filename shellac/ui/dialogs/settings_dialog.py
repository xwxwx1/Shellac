from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import config as cfg
from ...system.mediakeys import GlobalMediaKeys


def _theme_label(name: str) -> str:
    return name.removesuffix('.xml').replace('_', ' ').title()


class SettingsDialog(QDialog):
    """Edits the user config. `values()` returns the changed settings as config key -> string."""

    def __init__(self, parent, config: dict, themes):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.setMinimumWidth(560)
        self._config = config

        self.song_dir = self._dir_row(config['songdir'])
        self.download_dir = self._dir_row(config['downloaddir'])

        self.folders = QListWidget()
        self.folders.addItems(cfg.sidebar_folders(config))
        self.folders.setMaximumHeight(110)
        add_folder = QPushButton('Add…')
        add_folder.clicked.connect(self._add_folder)
        remove_folder = QPushButton('Remove')
        remove_folder.clicked.connect(lambda: [self.folders.takeItem(self.folders.row(i))
                                               for i in self.folders.selectedItems()])
        folder_buttons = QVBoxLayout()
        folder_buttons.addWidget(add_folder)
        folder_buttons.addWidget(remove_folder)
        folder_buttons.addStretch()
        folders = QHBoxLayout()
        folders.addWidget(self.folders, 1)
        folders.addLayout(folder_buttons)

        self.theme = QComboBox()
        for theme in themes:
            self.theme.addItem(_theme_label(theme), theme)
        self.theme.setCurrentIndex(max(0, self.theme.findData(config.get('theme'))))

        self.restore_session = QCheckBox('Reopen the last playlist and song on startup')
        self.restore_session.setChecked(cfg.flag(config, 'restoresession'))
        self.artist_tags = QCheckBox("Use the file's artist as the first tag for songs added without tags")
        self.artist_tags.setChecked(cfg.flag(config, 'artisttags'))
        self.no_repeat = QCheckBox('Shuffle in cycles: each song plays as many times as its weight')
        self.no_repeat.setChecked(cfg.flag(config, 'norepeatshuffle'))
        self.tray = QCheckBox('Show an icon in the system tray')
        self.tray.setChecked(cfg.flag(config, 'trayicon'))
        self.media_keys = QCheckBox('Respond to media keys while Shellac is in the background')
        self.media_keys.setChecked(cfg.flag(config, 'mediakeys'))
        self.media_keys.setEnabled(GlobalMediaKeys.supported)
        if not GlobalMediaKeys.supported:
            self.media_keys.setToolTip('Only available on Windows; media keys work while Shellac is focused.')

        form = QFormLayout()
        form.addRow('Song folder:', self.song_dir.parent_widget)
        form.addRow('Download folder:', self.download_dir.parent_widget)
        form.addRow('File dialog\nshortcuts:', folders)
        form.addRow('Theme:', self.theme)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        for box in (self.restore_session, self.artist_tags, self.no_repeat, self.tray, self.media_keys):
            layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _dir_row(self, value):
        edit = QLineEdit(value)
        edit.setCursorPosition(0)
        browse = QPushButton('Browse…')
        browse.clicked.connect(lambda: self._browse(edit))
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, 1)
        h.addWidget(browse)
        edit.parent_widget = row
        return edit

    def _browse(self, edit):
        path = QFileDialog.getExistingDirectory(self, 'Choose Folder', edit.text())
        if path:
            edit.setText(path)

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Add Shortcut Folder')
        if path:
            self.folders.addItem(path)

    def values(self) -> dict:
        def on_off(box):
            return str(box.isChecked())
        return {
            'songdir': self.song_dir.text().strip(),
            'downloaddir': self.download_dir.text().strip(),
            'folders': ';'.join(self.folders.item(i).text() for i in range(self.folders.count())),
            'theme': self.theme.currentData(),
            'restoresession': on_off(self.restore_session),
            'artisttags': on_off(self.artist_tags),
            'norepeatshuffle': on_off(self.no_repeat),
            'trayicon': on_off(self.tray),
            'mediakeys': on_off(self.media_keys),
        }
