"""Downloading audio with yt-dlp and converting/trimming it with ffmpeg, off the GUI thread."""
from __future__ import annotations

import glob
import optparse
import os
import re
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass, field

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.song import song_from_file
from .ffmpeg import FORMATS, conversion_command, ffmpeg_exe, popen

_INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class _SilentLogger:
    def debug(self, msg):
        pass

    warning = info = error = debug


class DownloadCancelledError(Exception):
    pass


class DownloadFailedError(Exception):
    pass


def safe_filename(name: str) -> str:
    """A name usable as a file name on every platform (Windows is the strictest)."""
    return _INVALID_NAME_CHARS.sub('', name).strip().rstrip('.')


def unique_path(directory: str, stem: str, ext: str) -> str:
    path = os.path.join(directory, f'{stem}.{ext}')
    n = 2
    while os.path.exists(path):
        path = os.path.join(directory, f'{stem} ({n}).{ext}')
        n += 1
    return path


@dataclass
class DownloadRequest:
    url: str
    name: str
    start: float | None = None
    end: float | None = None
    tags: list[str] = field(default_factory=list)
    weight: int = 1
    format: str = 'mp3'
    ytdlp_args: str = ''
    ffmpeg_args: str = ''
    keep_source: bool = False

    def validate(self):
        """Raise ValueError describing the first problem, if any."""
        if not self.url.strip():
            raise ValueError('Please enter a URL.')
        if not safe_filename(self.name):
            raise ValueError('Please enter a name for the song.')
        if self.format not in FORMATS:
            raise ValueError(f'Unknown format: {self.format}')
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError('The end time must be after the start time.')
        for label, args in (('yt-dlp', self.ytdlp_args), ('ffmpeg', self.ffmpeg_args)):
            try:
                shlex.split(args)
            except ValueError as e:
                raise ValueError(f'Could not parse the extra {label} options: {e}') from None
        if self.ytdlp_args.strip():
            ytdlp_options([], self.ytdlp_args, '.')  # raises ValueError for unknown options


def ytdlp_options(urls, extra_args: str, out_dir: str) -> dict:
    """yt-dlp options for downloading the best audio into out_dir, with the user's extra CLI options applied."""
    import yt_dlp

    argv = ['--format', 'bestaudio/best', '--output', os.path.join(out_dir, 'source.%(ext)s'),
            '--no-playlist', '--no-part', '--ffmpeg-location', ffmpeg_exe(),
            *shlex.split(extra_args), *urls]
    try:
        return yt_dlp.parse_options(argv).ydl_opts
    except (optparse.OptParseError, SystemExit):  # unknown or malformed options
        raise ValueError(f'yt-dlp did not accept the options: {extra_args}') from None


def run_download(request: DownloadRequest, song_dir: str, work_dir: str,
                 progress=lambda message: None, cancelled=lambda: False):
    """Download, convert and return the finished Song. Blocking; meant for a worker thread."""
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled, DownloadError

    name = safe_filename(request.name)
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(song_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='shellac-', dir=work_dir)
    try:
        def hook(status):
            if cancelled():
                raise DownloadCancelled()
            if status.get('status') == 'downloading':
                total = status.get('total_bytes') or status.get('total_bytes_estimate')
                if total:
                    progress(f'Downloading {name}: {100 * status.get("downloaded_bytes", 0) / total:.0f}%')
                else:
                    progress(f'Downloading {name}…')

        options = ytdlp_options([], request.ytdlp_args, tmp)
        options.update(quiet=True, no_warnings=True, noprogress=True, progress_hooks=[hook],
                       logger=_SilentLogger())  # errors still surface as DownloadError
        progress(f'Downloading {name}…')
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([request.url])
        except DownloadCancelled:
            raise DownloadCancelledError() from None
        except DownloadError as e:
            raise DownloadFailedError(str(e).removeprefix('ERROR: ')) from None

        sources = [p for p in glob.glob(os.path.join(tmp, 'source.*')) if not p.endswith('.part')]
        if not sources:
            raise DownloadFailedError('yt-dlp finished but produced no file.')
        source = sources[0]

        if cancelled():
            raise DownloadCancelledError()
        progress(f'Converting {name}…')
        ext = FORMATS[request.format][0]
        target = unique_path(song_dir, name, ext)
        partial = os.path.join(tmp, f'converted.{ext}')
        process = popen(conversion_command(source, partial, request.format, request.start, request.end,
                                           shlex.split(request.ffmpeg_args)))
        while process.poll() is None:
            if cancelled():
                process.kill()
                process.wait()
                raise DownloadCancelledError()
            time.sleep(0.1)
        if process.returncode != 0:
            error = process.stderr.read().decode(errors='replace').strip()
            raise DownloadFailedError(f'ffmpeg failed: {error or process.returncode}')
        process.stderr.close()
        shutil.move(partial, target)

        if request.keep_source:
            shutil.move(source, unique_path(work_dir, name, os.path.splitext(source)[1][1:]))
        return song_from_file(target, request.name.strip(), request.tags, request.weight)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class DownloadJob(QThread):
    progress = pyqtSignal(str)
    succeeded = pyqtSignal(object)  # Song
    failed = pyqtSignal(str)
    aborted = pyqtSignal()

    def __init__(self, request: DownloadRequest, song_dir: str, work_dir: str, parent=None):
        super().__init__(parent)
        self.request = request
        self._song_dir = song_dir
        self._work_dir = work_dir
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            song = run_download(self.request, self._song_dir, self._work_dir,
                                self.progress.emit, lambda: self._cancel)
        except DownloadCancelledError:
            self.aborted.emit()
        except DownloadFailedError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001 - report anything unexpected instead of dying silently
            self.failed.emit(f'{type(e).__name__}: {e}')
        else:
            self.succeeded.emit(song)
