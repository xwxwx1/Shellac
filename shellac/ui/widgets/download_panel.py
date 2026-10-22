"""The Downloads panel: a form for new downloads, cookie choice, and the list of running/finished jobs."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...config import DownloadSettings
from ...core.song import parse_tags
from ...core.timefmt import format_time, parse_time
from ...download.cookies import BROWSERS, CookieSource
from ...download.ffmpeg import FORMATS
from ...download.worker import DownloadJob, DownloadRequest, InfoJob

FILE_CHOICE = 'file'


class JobRow(QWidget):
    """One download in the list: name, status, progress, and a cancel/retry/dismiss button."""

    def __init__(self, request: DownloadRequest, parent=None):
        super().__init__(parent)
        self.request = request
        self.job = None
        self.name = QLabel(request.label)
        self.name.setWordWrap(True)
        self.status = QLabel('Waiting…')
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.button = QToolButton()
        self.button.setText('Cancel')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        top = QHBoxLayout()
        top.addWidget(self.name, 1)
        top.addWidget(self.button)
        layout.addLayout(top)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)

    def set_progress(self, message, fraction):
        self.status.setText(message)
        if fraction < 0:
            self.bar.setRange(0, 0)  # busy indicator
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(round(fraction * 1000))

    def finish(self, message, ok, can_retry=False):
        self.job = None
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if ok else 0)
        self.bar.setVisible(not ok)
        self.status.setText(message)
        self.status.setToolTip(message)
        self.button.setText('Retry' if can_retry else 'Dismiss')

    @property
    def running(self) -> bool:
        return self.job is not None


class DownloadPanel(QWidget):
    songDownloaded = pyqtSignal(object)  # Song
    settingsChanged = pyqtSignal(object)  # DownloadSettings to remember
    busyChanged = pyqtSignal(bool)
    statusMessage = pyqtSignal(str)

    def __init__(self, settings: DownloadSettings, folders, parent=None):
        """folders(): returns (song folder, download folder) at the time a download starts."""
        super().__init__(parent)
        self._folders = folders
        self._info_job = None
        self.rows: list[JobRow] = []

        self.url = QLineEdit()
        self.url.setPlaceholderText('Paste a link (bilibili, YouTube, …)')
        self.url.setClearButtonEnabled(True)
        self.url.returnPressed.connect(self.look_up)
        self.url.textChanged.connect(self._url_changed)
        self.look_up_button = QPushButton('Look up')
        self.look_up_button.setToolTip('Check the link (and your cookies) without downloading')
        self.look_up_button.clicked.connect(self.look_up)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.name = QLineEdit()
        self.name.setPlaceholderText('the video title')
        self.start_time = QLineEdit()
        self.start_time.setPlaceholderText('start, e.g. 1:05')
        self.end_time = QLineEdit()
        self.end_time.setPlaceholderText('end')
        self.tags = QLineEdit(settings.tags)
        self.tags.setPlaceholderText('the uploader (as artist)')
        self.weight = QSpinBox()
        self.weight.setRange(0, 999)
        self.weight.setValue(settings.weight)
        self.format = QComboBox()
        self.format.addItems(FORMATS)
        self.format.setCurrentText(settings.format if settings.format in FORMATS else 'mp3')

        self.cookie_choice = QComboBox()
        self.cookie_choice.addItem('No cookies', 'none')
        for browser in BROWSERS:
            self.cookie_choice.addItem(f'From {browser.title()}', browser)
        self.cookie_choice.addItem('From a cookies.txt file', FILE_CHOICE)
        self.cookie_choice.setToolTip(
            'Cookies let downloads use your logged-in account, e.g. bilibili Hi-Res audio or members-only '
            'videos.\nShellac reads them when downloading and never stores them.')
        self.cookie_file = QLineEdit(settings.cookie_file)
        self.cookie_file.setPlaceholderText('cookies.txt (Netscape format)')
        browse = QPushButton('Browse…')
        browse.clicked.connect(self._browse_cookie_file)
        self.cookie_file_row = QWidget()
        file_row = QHBoxLayout(self.cookie_file_row)
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.addWidget(self.cookie_file, 1)
        file_row.addWidget(browse)
        choice = {'browser': settings.cookie_browser, 'file': FILE_CHOICE}.get(settings.cookie_source, 'none')
        self.cookie_choice.setCurrentIndex(max(0, self.cookie_choice.findData(choice)))
        self.cookie_choice.currentIndexChanged.connect(self._cookie_choice_changed)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText('Advanced options')
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.ytdlp_args = QLineEdit(settings.ytdlp_args)
        self.ytdlp_args.setPlaceholderText('extra yt-dlp options (not used for bilibili)')
        self.ffmpeg_args = QLineEdit(settings.ffmpeg_args)
        self.ffmpeg_args.setPlaceholderText('extra ffmpeg options, e.g. -af loudnorm')
        self.keep_source = QCheckBox('Keep the original download')
        self.keep_source.setChecked(settings.keep_source)
        self.advanced = QWidget()
        advanced = QFormLayout(self.advanced)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.addRow('yt-dlp:', self.ytdlp_args)
        advanced.addRow('ffmpeg:', self.ffmpeg_args)
        advanced.addRow(self.keep_source)
        self.advanced.setVisible(False)

        self.download_button = QPushButton('Download')
        self.download_button.clicked.connect(self.download)

        self.jobs = QVBoxLayout()
        self.jobs.addStretch(1)
        jobs_widget = QWidget()
        jobs_widget.setLayout(self.jobs)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(jobs_widget)
        self.clear_button = QPushButton('Clear Finished')
        self.clear_button.clicked.connect(self.clear_finished)

        url_row = QHBoxLayout()
        url_row.addWidget(self.url, 1)
        url_row.addWidget(self.look_up_button)
        times = QHBoxLayout()
        times.addWidget(self.start_time)
        times.addWidget(self.end_time)
        weight_format = QHBoxLayout()
        weight_format.addWidget(self.weight)
        weight_format.addWidget(QLabel('Format:'))
        weight_format.addWidget(self.format, 1)

        form = QFormLayout()
        form.addRow(url_row)
        form.addRow(self.info)
        form.addRow('Name:', self.name)
        form.addRow('Trim:', times)
        form.addRow('Tags:', self.tags)
        form.addRow('Weight:', weight_format)
        form.addRow('Cookies:', self.cookie_choice)
        form.addRow('', self.cookie_file_row)
        form.addRow(self.advanced_toggle)
        form.addRow(self.advanced)
        form.addRow(self.download_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(form)
        layout.addWidget(scroll, 1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.clear_button)
        layout.addLayout(bottom)
        self._cookie_choice_changed()

    # --- form --------------------------------------------------------------------------------

    def cookies(self) -> CookieSource:
        choice = self.cookie_choice.currentData()
        if choice == 'none':
            return CookieSource()
        if choice == FILE_CHOICE:
            return CookieSource('file', file=self.cookie_file.text().strip())
        return CookieSource('browser', browser=choice)

    def settings(self) -> DownloadSettings:
        cookies = self.cookies()
        previous_browser = self.cookie_choice.currentData() if cookies.kind == 'browser' else 'firefox'
        return DownloadSettings(
            tags=self.tags.text(), format=self.format.currentText(), ytdlp_args=self.ytdlp_args.text(),
            ffmpeg_args=self.ffmpeg_args.text(), weight=self.weight.value(),
            keep_source=self.keep_source.isChecked(), cookie_source=cookies.kind,
            cookie_browser=previous_browser, cookie_file=self.cookie_file.text().strip())

    def _cookie_choice_changed(self, *_):
        self.cookie_file_row.setVisible(self.cookie_choice.currentData() == FILE_CHOICE)

    def _browse_cookie_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose cookies.txt', self.cookie_file.text(),
                                              'Cookie files (*.txt);;All files (*)')
        if path:
            self.cookie_file.setText(path)

    def _toggle_advanced(self, shown):
        self.advanced.setVisible(shown)
        self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)

    def _url_changed(self):
        self.info.setText('')
        self.name.setPlaceholderText('the video title')
        self.tags.setPlaceholderText('the uploader (as artist)')

    def focus_url(self):
        self.url.setFocus()
        self.url.selectAll()

    def build_request(self) -> DownloadRequest:
        """The request described by the form. Raises ValueError with a message for the user."""
        request = DownloadRequest(
            url=self.url.text().strip(), name=self.name.text().strip(),
            start=parse_time(self.start_time.text()), end=parse_time(self.end_time.text()),
            tags=parse_tags(self.tags.text()), weight=self.weight.value(), format=self.format.currentText(),
            ytdlp_args=self.ytdlp_args.text(), ffmpeg_args=self.ffmpeg_args.text(),
            keep_source=self.keep_source.isChecked(), cookies=self.cookies())
        request.validate()
        return request

    # --- look up -----------------------------------------------------------------------------

    def look_up(self):
        url = self.url.text().strip()
        if not url or self._info_job is not None:
            return
        cookies = self.cookies()
        try:
            cookies.validate()
        except ValueError as e:
            self.info.setText(str(e))
            return
        self.info.setText(f'Looking up… ({cookies.describe()})')
        self.look_up_button.setEnabled(False)
        job = InfoJob(url, cookies, self.ytdlp_args.text(), self)
        job.found.connect(self._on_info)
        job.failed.connect(self._on_info_failed)
        job.finished.connect(self._on_info_finished)
        self._info_job = job
        job.start()

    def _on_info(self, info):
        if self.sender().url != self.url.text().strip():
            return  # the URL changed while looking it up
        length = f' · {format_time(info.duration)}' if info.duration else ''
        self.info.setText(f'<b>{_escape(info.title)}</b>{length}<br>{_escape(info.details)}')
        self.name.setPlaceholderText(info.title)
        if info.uploader:
            self.tags.setPlaceholderText(info.uploader)

    def _on_info_failed(self, message):
        if self.sender().url == self.url.text().strip():
            self.info.setText(f'<span style="color:#e57373">{_escape(message)}</span>')

    def _on_info_finished(self):
        self.sender().deleteLater()
        self._info_job = None
        self.look_up_button.setEnabled(True)

    # --- jobs --------------------------------------------------------------------------------

    def download(self):
        try:
            request = self.build_request()
        except ValueError as e:
            QMessageBox.warning(self, 'Download', str(e))
            return
        self.settingsChanged.emit(self.settings())
        self.start(request)
        # Ready for the next link; trims and the name belong to this one.
        for field in (self.url, self.name, self.start_time, self.end_time):
            field.clear()

    def start(self, request: DownloadRequest) -> JobRow:
        row = JobRow(request)
        row.button.clicked.connect(lambda: self._row_button(row))
        self.jobs.insertWidget(0, row)
        self.rows.insert(0, row)
        self._run(row)
        return row

    def _run(self, row: JobRow):
        song_dir, work_dir = self._folders()
        job = DownloadJob(row.request, song_dir, work_dir, self)
        # Bound methods of row/panel objects, so Qt queues these onto the GUI thread.
        job.progress.connect(row.set_progress)
        job.succeeded.connect(self._on_succeeded)
        job.failed.connect(self._on_failed)
        job.aborted.connect(self._on_aborted)
        job.finished.connect(self._on_finished)
        job.row = row
        row.job = job
        row.button.setText('Cancel')
        row.bar.setVisible(True)
        row.set_progress('Starting…', -1)
        job.start()
        self.busyChanged.emit(True)

    def _row_button(self, row: JobRow):
        if row.running:
            row.job.cancel()
            row.status.setText('Cancelling…')
        elif row.button.text() == 'Retry':
            self._run(row)
        else:
            self._remove(row)

    def _on_succeeded(self, song):
        row = self.sender().row
        row.name.setText(song.name)
        row.finish('Added to the playlist', ok=True)
        self.songDownloaded.emit(song)
        self.statusMessage.emit(f'Downloaded {song.name}')

    def _on_failed(self, message):
        row = self.sender().row
        row.finish(f'Failed: {message}', ok=False, can_retry=True)
        self.statusMessage.emit(f'Download failed: {row.request.label}')

    def _on_aborted(self):
        self.sender().row.finish('Cancelled', ok=False, can_retry=True)

    def _on_finished(self):
        job = self.sender()
        job.deleteLater()
        self.busyChanged.emit(self.busy)

    def _remove(self, row: JobRow):
        self.rows.remove(row)
        self.jobs.removeWidget(row)
        row.deleteLater()

    def clear_finished(self):
        for row in [r for r in self.rows if not r.running]:
            self._remove(row)

    @property
    def running_jobs(self) -> list[DownloadJob]:
        return [r.job for r in self.rows if r.running]

    @property
    def busy(self) -> bool:
        return any(r.running for r in self.rows)

    def cancel_all(self):
        for job in self.running_jobs:
            job.cancel()

    def shutdown(self, wait_ms=5000):
        for job in self.running_jobs:
            job.cancel()
            job.wait(wait_ms)
        if self._info_job is not None:
            self._info_job.wait(wait_ms)


def _escape(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
