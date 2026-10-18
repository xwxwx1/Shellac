from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
)

from ...config import DownloadSettings
from ...core.song import parse_tags
from ...core.timefmt import parse_time
from ...download.ffmpeg import FORMATS
from ...download.worker import DownloadRequest


class DownloadDialog(QDialog):
    """Collects a DownloadRequest; remembered settings pre-fill everything except the URL, name and times."""

    def __init__(self, parent, settings: DownloadSettings):
        super().__init__(parent)
        self.setWindowTitle('Download from the Internet')
        self.setMinimumWidth(560)
        self.request = None

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText('https://…  (any site yt-dlp supports)')
        self.name_edit = QLineEdit()
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText('beginning   (e.g. 1:05)')
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText('end of the file   (e.g. 4:30)')
        self.tags_edit = QLineEdit(settings.tags)
        self.tags_edit.setPlaceholderText('Artist, tag, tag…')
        self.weight_edit = QSpinBox()
        self.weight_edit.setRange(0, 999)
        self.weight_edit.setValue(settings.weight)
        self.format_box = QComboBox()
        self.format_box.addItems(FORMATS)
        self.format_box.setCurrentText(settings.format if settings.format in FORMATS else 'mp3')
        self.ytdlp_edit = QLineEdit(settings.ytdlp_args)
        self.ytdlp_edit.setPlaceholderText('e.g. --cookies-from-browser firefox')
        self.ffmpeg_edit = QLineEdit(settings.ffmpeg_args)
        self.ffmpeg_edit.setPlaceholderText('e.g. -af loudnorm')
        self.keep_box = QCheckBox('Keep the original downloaded file')
        self.keep_box.setChecked(settings.keep_source)
        self.remember_box = QCheckBox('Remember these settings')
        self.remember_box.setChecked(True)

        form = QFormLayout(self)
        form.addRow('URL:', self.url_edit)
        form.addRow('Name:', self.name_edit)
        form.addRow('Start:', self.start_edit)
        form.addRow('End:', self.end_edit)
        form.addRow('Tags:', self.tags_edit)
        form.addRow('Weight:', self.weight_edit)
        form.addRow('Format:', self.format_box)
        form.addRow('yt-dlp options:', self.ytdlp_edit)
        form.addRow('ffmpeg options:', self.ffmpeg_edit)
        form.addRow('', self.keep_box)
        form.addRow('', self.remember_box)
        note = QLabel('Times can be seconds, m:ss or h:mm:ss. Leave them blank to keep the whole track.')
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Download')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def settings(self) -> DownloadSettings:
        return DownloadSettings(
            tags=self.tags_edit.text(),
            format=self.format_box.currentText(),
            ytdlp_args=self.ytdlp_edit.text(),
            ffmpeg_args=self.ffmpeg_edit.text(),
            weight=self.weight_edit.value(),
            keep_source=self.keep_box.isChecked(),
        )

    @property
    def remember(self) -> bool:
        return self.remember_box.isChecked()

    def accept(self):
        try:
            start = parse_time(self.start_edit.text())
            end = parse_time(self.end_edit.text())
            request = DownloadRequest(
                url=self.url_edit.text().strip(),
                name=self.name_edit.text().strip(),
                start=start,
                end=end,
                tags=parse_tags(self.tags_edit.text()),
                weight=self.weight_edit.value(),
                format=self.format_box.currentText(),
                ytdlp_args=self.ytdlp_edit.text(),
                ffmpeg_args=self.ffmpeg_edit.text(),
                keep_source=self.keep_box.isChecked(),
            )
            request.validate()
        except ValueError as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return
        self.request = request
        super().accept()
