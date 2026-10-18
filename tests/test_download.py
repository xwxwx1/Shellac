import os
import subprocess

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QMessageBox

from shellac import config
from shellac.core.song import read_metadata
from shellac.download.ffmpeg import FORMATS, conversion_command, ffmpeg_exe
from shellac.download.worker import (
    DownloadCancelledError,
    DownloadFailedError,
    DownloadRequest,
    run_download,
    safe_filename,
    unique_path,
)
from shellac.ui.main_window import MainWindow


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / 'clip.wav'
    subprocess.run([ffmpeg_exe(), '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=duration=6', str(path)],
                   check=True)
    return path


def file_request(clip, **kwargs):
    # yt-dlp refuses file:// URLs unless asked, which conveniently exercises the extra-options path.
    defaults = {'url': QUrl.fromLocalFile(str(clip)).toString(), 'name': 'Song', 'ytdlp_args': '--enable-file-urls'}
    return DownloadRequest(**{**defaults, **kwargs})


def test_safe_filename_and_unique_path(tmp_path):
    assert safe_filename(' a/b\\c:d*e?f"g<h>i|j. ') == 'abcdefghij'
    assert safe_filename('???') == ''
    (tmp_path / 'x.mp3').touch()
    (tmp_path / 'x (2).mp3').touch()
    assert unique_path(str(tmp_path), 'x', 'mp3').endswith('x (3).mp3')
    assert unique_path(str(tmp_path), 'y', 'mp3').endswith('y.mp3')


@pytest.mark.parametrize('kwargs, message', [
    ({'url': ''}, 'URL'),
    ({'name': '//'}, 'name'),
    ({'start': 5, 'end': 5}, 'end time'),
    ({'ytdlp_args': '--no-such-option'}, 'yt-dlp'),
    ({'ffmpeg_args': '"unbalanced'}, 'ffmpeg'),
    ({'format': 'mp4'}, 'format'),
])
def test_validation(kwargs, message):
    request = DownloadRequest(**{'url': 'https://example.com', 'name': 'x', **kwargs})
    with pytest.raises(ValueError, match=message):
        request.validate()


@pytest.mark.parametrize('fmt', sorted(FORMATS))
def test_every_format_encodes(fmt, clip, tmp_path):
    ext = FORMATS[fmt][0]
    target = tmp_path / f'out.{ext}'
    subprocess.run(conversion_command(str(clip), str(target), fmt, start=1, end=2), check=True)
    _, duration = read_metadata(str(target))
    assert duration == pytest.approx(1, abs=0.15)


def test_download_trims_converts_and_cleans_up(clip, tmp_path):
    messages = []
    request = file_request(clip, name='A: song?', start=1, end=3.5, tags=['T'], weight=4,
                           format='ogg', keep_source=True)
    request.validate()
    song = run_download(request, str(tmp_path / 'songs'), str(tmp_path / 'work'), messages.append)
    assert song.path.endswith('/songs/A song.ogg')
    assert (song.name, song.tags, song.weight) == ('A: song?', ['T'], 4)
    assert song.duration == pytest.approx(2.5, abs=0.15)
    assert os.listdir(tmp_path / 'work') == ['A song.wav']  # kept source; temp folder removed
    assert any('Converting' in m for m in messages)

    again = run_download(file_request(clip, name='A song', format='ogg'), str(tmp_path / 'songs'),
                         str(tmp_path / 'work'))
    assert again.path.endswith('/songs/A song (2).ogg')


def test_failures_and_cancellation(clip, tmp_path):
    missing = file_request(clip.with_name('nope.wav'))
    with pytest.raises(DownloadFailedError):
        run_download(missing, str(tmp_path / 'songs'), str(tmp_path / 'work'))
    with pytest.raises(DownloadCancelledError):
        run_download(file_request(clip), str(tmp_path / 'songs'), str(tmp_path / 'work'), cancelled=lambda: True)
    assert os.listdir(tmp_path / 'work') == []
    assert not os.listdir(tmp_path / 'songs')


def test_window_download_adds_song(qtbot, clip, tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_DIR', tmp_path / 'cfg')
    monkeypatch.setattr(config, 'CONFIG_PATH', tmp_path / 'cfg' / 'config.txt')
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'data')
    window = MainWindow(config.load_config())
    qtbot.addWidget(window)

    window.start_download(file_request(clip, name='Downloaded', tags=['Net']))
    qtbot.waitUntil(lambda: len(window.model.playlist) == 1 and not window.downloads, timeout=30000)
    song = window.model.playlist[0]
    assert song.name == 'Downloaded' and song.path.startswith(window.song_dir)
    assert not window.cancel_downloads_action.isEnabled()

    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: warnings.append(a[2]))
    window.start_download(file_request(clip.with_name('missing.wav'), name='Broken'))
    qtbot.waitUntil(lambda: bool(warnings) and not window.downloads, timeout=30000)
    assert 'Broken' in warnings[0]
    window.close()
