"""Downloading audio and converting/trimming it with ffmpeg, off the GUI thread.

bilibili links go through shellac.download.bilibili; everything else through yt-dlp.
"""
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
from . import bilibili
from .cookies import CookieError, CookieSource, cookie_header
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
    name: str = ''  # blank: use the video's title
    start: float | None = None
    end: float | None = None
    tags: list[str] = field(default_factory=list)
    weight: int = 1
    format: str = 'mp3'
    ytdlp_args: str = ''
    ffmpeg_args: str = ''
    keep_source: bool = False
    cookies: CookieSource = field(default_factory=CookieSource)
    uploader_as_artist: bool = True  # with no tags given, tag the song with the uploader's name

    @property
    def label(self) -> str:
        return self.name.strip() or self.url.strip()

    def validate(self):
        """Raise ValueError describing the first problem, if any."""
        if not self.url.strip():
            raise ValueError('Please enter a URL.')
        if self.name.strip() and not safe_filename(self.name):
            raise ValueError('The name has no characters usable in a file name.')
        if self.format not in FORMATS:
            raise ValueError(f'Unknown format: {self.format}')
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError('The end time must be after the start time.')
        self.cookies.validate()
        for label, args in (('yt-dlp', self.ytdlp_args), ('ffmpeg', self.ffmpeg_args)):
            try:
                shlex.split(args)
            except ValueError as e:
                raise ValueError(f'Could not parse the extra {label} options: {e}') from None
        if self.ytdlp_args.strip():
            ytdlp_options([], self.ytdlp_args, '.')  # raises ValueError for unknown options


def ytdlp_options(urls, extra_args: str, out_dir: str, cookies: CookieSource | None = None) -> dict:
    """yt-dlp options for downloading the best audio into out_dir, with the user's extra CLI options applied."""
    import yt_dlp

    argv = ['--format', 'bestaudio/best', '--output', os.path.join(out_dir, 'source.%(ext)s'),
            '--no-playlist', '--no-part', '--ffmpeg-location', ffmpeg_exe(),
            *shlex.split(extra_args), *urls]
    try:
        options = yt_dlp.parse_options(argv).ydl_opts
    except (optparse.OptParseError, SystemExit):  # unknown or malformed options
        raise ValueError(f'yt-dlp did not accept the options: {extra_args}') from None
    if cookies is not None:
        options.update(cookies.ytdlp_options())
    return options


@dataclass
class MediaInfo:
    """What a URL points to, looked up before downloading."""
    title: str
    uploader: str = ''
    duration: float | None = None
    details: str = ''


def _bilibili_cookies(source: CookieSource) -> str:
    if not source.enabled:
        return ''
    try:
        return cookie_header(source.load(), 'bilibili.com')
    except CookieError as e:
        raise DownloadFailedError(str(e)) from None


def fetch_info(url: str, cookies: CookieSource | None = None, ytdlp_args: str = '') -> MediaInfo:
    """Look up a URL's title, uploader and length without downloading. Blocking."""
    cookies = cookies or CookieSource()
    if bilibili.matches(url):
        try:
            info = bilibili.Client(_bilibili_cookies(cookies)).info(url)
        except bilibili.BilibiliError as e:
            raise DownloadFailedError(str(e)) from None
        return MediaInfo(info.title, info.uploader, info.duration, info.describe())

    import yt_dlp
    from yt_dlp.utils import DownloadError

    options = ytdlp_options([], ytdlp_args, tempfile.gettempdir(), cookies)
    options.update(quiet=True, no_warnings=True, noprogress=True, logger=_SilentLogger(), skip_download=True)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(url, download=False)
    except DownloadError as e:
        raise DownloadFailedError(_explain_ytdlp_error(str(e), cookies)) from None
    except Exception as e:  # noqa: BLE001 - e.g. cookie extraction failing inside yt-dlp
        raise DownloadFailedError(_explain_ytdlp_error(f'{type(e).__name__}: {e}', cookies)) from None
    abr = max((f.get('abr') or 0 for f in data.get('formats') or []), default=0)
    details = f"{data.get('extractor_key', 'yt-dlp')}: {data.get('uploader') or 'unknown uploader'}"
    if abr:
        details += f' · best audio ~{abr:.0f} kbps'
    return MediaInfo(data.get('title') or url, data.get('uploader') or '', data.get('duration'), details)


def _explain_ytdlp_error(message: str, cookies: CookieSource) -> str:
    message = message.removeprefix('ERROR: ')
    if cookies.kind == 'browser' and 'cookie' in message.lower():
        from .cookies import browser_hint
        return browser_hint(cookies.browser, message)
    return message


def _download_with_ytdlp(request, tmp, progress, cancelled):
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled, DownloadError

    label = request.label

    def hook(status):
        if cancelled():
            raise DownloadCancelled()
        if status.get('status') == 'downloading':
            total = status.get('total_bytes') or status.get('total_bytes_estimate')
            done = status.get('downloaded_bytes', 0)
            if total:
                progress(f'Downloading {label}: {100 * done / total:.0f}%', done / total)
            else:
                progress(f'Downloading {label}…', -1)

    options = ytdlp_options([], request.ytdlp_args, tmp, request.cookies)
    options.update(quiet=True, no_warnings=True, noprogress=True, progress_hooks=[hook],
                   logger=_SilentLogger())  # errors still surface as DownloadError
    progress(f'Downloading {label}…', -1)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(request.url, download=True)
    except DownloadCancelled:
        raise DownloadCancelledError() from None
    except DownloadError as e:
        raise DownloadFailedError(_explain_ytdlp_error(str(e), request.cookies)) from None
    except Exception as e:  # noqa: BLE001 - e.g. cookie extraction failing inside yt-dlp
        raise DownloadFailedError(_explain_ytdlp_error(f'{type(e).__name__}: {e}', request.cookies)) from None

    sources = [p for p in glob.glob(os.path.join(tmp, 'source.*')) if not p.endswith('.part')]
    if not sources:
        raise DownloadFailedError('yt-dlp finished but produced no file.')
    data = data or {}
    return sources[0], data.get('title') or '', data.get('uploader') or ''


def _download_from_bilibili(request, tmp, progress, cancelled):
    try:
        path, info = bilibili.download_audio(request.url, tmp, _bilibili_cookies(request.cookies),
                                             progress, cancelled)
    except bilibili.Cancelled:
        raise DownloadCancelledError() from None
    except bilibili.BilibiliError as e:
        raise DownloadFailedError(str(e)) from None
    return path, info.title, info.uploader


def run_download(request: DownloadRequest, song_dir: str, work_dir: str,
                 progress=lambda message, fraction: None, cancelled=lambda: False):
    """Download, convert and return the finished Song. Blocking; meant for a worker thread.

    progress(message, fraction) gets a fraction in 0..1, or -1 when the size is unknown.
    """
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(song_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='shellac-', dir=work_dir)
    try:
        fetch = _download_from_bilibili if bilibili.matches(request.url) else _download_with_ytdlp
        source, title, uploader = fetch(request, tmp, progress, cancelled)

        display_name = request.name.strip() or title.strip() or 'Download'
        name = safe_filename(display_name) or 'Download'
        tags = list(request.tags)
        if not tags and request.uploader_as_artist and uploader:
            tags = [uploader]

        if cancelled():
            raise DownloadCancelledError()
        progress(f'Converting {display_name}…', -1)
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
            kept_ext = os.path.splitext(source)[1][1:]
            shutil.move(source, unique_path(work_dir, name, 'm4a' if kept_ext == 'm4s' else kept_ext))
        return song_from_file(target, display_name, tags, request.weight)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class DownloadJob(QThread):
    progress = pyqtSignal(str, float)  # message, fraction (0..1, or -1 if unknown)
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

    @property
    def cancelling(self) -> bool:
        return self._cancel

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


class InfoJob(QThread):
    """Looks up a URL in the background (title, uploader, length, available quality)."""

    found = pyqtSignal(object)  # MediaInfo
    failed = pyqtSignal(str)

    def __init__(self, url: str, cookies: CookieSource, ytdlp_args: str = '', parent=None):
        super().__init__(parent)
        self.url = url
        self._cookies = cookies
        self._ytdlp_args = ytdlp_args

    def run(self):
        try:
            info = fetch_info(self.url, self._cookies, self._ytdlp_args)
        except DownloadFailedError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f'{type(e).__name__}: {e}')
        else:
            self.found.emit(info)
