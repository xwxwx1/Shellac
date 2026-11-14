"""Cookies, the bilibili client (offline, against faked responses) and the Downloads panel.

Set SHELLAC_NETWORK_TESTS=1 to also run the live bilibili test at the bottom.
"""
import io
import os
import subprocess

import pytest
from PyQt6.QtCore import QUrl

from shellac import config
from shellac.download import bilibili, cookies, worker
from shellac.download.cookies import CookieError, CookieSource, cookie_header
from shellac.download.ffmpeg import ffmpeg_exe
from shellac.download.worker import DownloadRequest, MediaInfo
from shellac.ui.widgets.download_panel import DownloadPanel

COOKIES_TXT = """# Netscape HTTP Cookie File
.bilibili.com\tTRUE\t/\tTRUE\t2147483647\tSESSDATA\tsecret%2Cvalue
.bilibili.com\tTRUE\t/\tFALSE\t2147483647\tbuvid3\tabc
www.bilibili.com\tFALSE\t/\tFALSE\t2147483647\tbili_jct\tcsrf
.example.com\tTRUE\t/\tFALSE\t2147483647\tother\tx
"""


# --- cookies ---------------------------------------------------------------------------------

def test_cookie_file_and_header(tmp_path):
    path = tmp_path / 'cookies.txt'
    path.write_text(COOKIES_TXT, encoding='utf-8')
    source = CookieSource('file', file=str(path))
    source.validate()
    header = cookie_header(source.load(), 'bilibili.com')
    assert header.split('; ') == ['SESSDATA=secret%2Cvalue', 'buvid3=abc', 'bili_jct=csrf']
    assert source.ytdlp_options() == {'cookiefile': str(path)}
    assert CookieSource().ytdlp_options() == {} and not CookieSource().enabled


def test_cookie_errors(tmp_path, monkeypatch):
    with pytest.raises(CookieError, match='not found'):
        CookieSource('file', file=str(tmp_path / 'nope.txt')).load()
    bad = tmp_path / 'bad.txt'
    bad.write_text('not a cookie file', encoding='utf-8')
    with pytest.raises(CookieError, match='Netscape'):
        CookieSource('file', file=str(bad)).load()
    with pytest.raises(ValueError):
        CookieSource('file', file=' ').validate()
    with pytest.raises(ValueError):
        CookieSource('browser', browser='netscape').validate()

    import yt_dlp.cookies

    def fail(browser, logger=None):
        raise PermissionError('Could not copy Chrome cookie database')
    monkeypatch.setattr(yt_dlp.cookies, 'extract_cookies_from_browser', fail)
    monkeypatch.setattr(cookies.sys, 'platform', 'win32')
    with pytest.raises(CookieError, match='Close Chrome completely'):
        CookieSource('browser', browser='chrome').load()
    assert CookieSource('browser', browser='edge').ytdlp_options() == {'cookiesfrombrowser': ('edge', None, None, None)}
    assert 'encrypt' in cookies.browser_hint('chrome', 'Failed to decrypt with DPAPI')


def test_download_settings_remember_cookie_source_only():
    settings = config.DownloadSettings(cookie_source='file', cookie_file='C:/c.txt')
    parsed = config.DownloadSettings.parse(settings.dump())
    assert parsed == settings and parsed.cookies() == CookieSource('file', 'firefox', 'C:/c.txt')
    assert 'SESSDATA' not in settings.dump()


# --- bilibili (offline) ----------------------------------------------------------------------

@pytest.mark.parametrize('url, expected', [
    ('https://www.bilibili.com/video/BV1AHnB6NEhM/?spm_id_from=333', True),
    ('https://m.bilibili.com/video/av170001', True),
    ('BV1AHnB6NEhM', True),
    ('https://b23.tv/abcdEF', True),
    ('https://www.youtube.com/watch?v=x', False),
    ('https://notbilibili.com.evil.org/video/BV1AHnB6NEhM', False),
])
def test_matches(url, expected):
    assert bilibili.matches(url) is expected


def test_resolve():
    client = bilibili.Client()
    assert client.resolve('https://www.bilibili.com/video/BV1fNnv6EEon?p=3') == ({'bvid': 'BV1fNnv6EEon'}, 3)
    assert client.resolve('https://www.bilibili.com/video/av170001/') == ({'aid': '170001'}, 1)
    with pytest.raises(bilibili.BilibiliError, match='does not point to a video'):
        client.resolve('https://space.bilibili.com/123')


class FakeResponse(io.BytesIO):
    def __init__(self, body=b'', headers=None, url=''):
        super().__init__(body)
        self.headers = headers or {}
        self._url = url

    def geturl(self):
        return self._url


def fake_client(monkeypatch, playurl_dash, logged_in=False, view=None):
    client = bilibili.Client('SESSDATA=s')
    view = view or {'bvid': 'BV1fNnv6EEon', 'title': 'Show', 'owner': {'name': 'Uploader'}, 'duration': 300,
                    'pages': [{'cid': 11, 'part': 'Intro', 'duration': 100},
                              {'cid': 22, 'part': 'Main', 'duration': 200}]}
    calls = []

    def fake_json(path, params=None, signed=False):
        calls.append((path, params, signed))
        if path == '/x/frontend/finger/spi':
            return {'b_3': 'B3', 'b_4': 'B4'}
        if path == '/x/web-interface/wbi/view':
            return view
        if path == '/x/player/wbi/playurl':
            return {'dash': playurl_dash}
        raise AssertionError(path)
    monkeypatch.setattr(client, '_json', fake_json)
    monkeypatch.setattr(client, 'nav', lambda: {'isLogin': logged_in, 'uname': 'me', 'vipStatus': 1})
    return client, calls


def test_info_picks_part_and_best_audio(monkeypatch):
    dash = {'audio': [{'id': 30216, 'bandwidth': 64000, 'baseUrl': 'http://a/64'},
                      {'id': 30280, 'bandwidth': 192000, 'baseUrl': 'http://a/192', 'backupUrl': ['http://b/192']}],
            'flac': {'audio': {'id': 30251, 'bandwidth': 900000, 'base_url': 'http://a/flac'}},
            'dolby': {'audio': [{'id': 30250, 'bandwidth': 448000, 'baseUrl': 'http://a/dolby'}]}}
    client, calls = fake_client(monkeypatch, dash, logged_in=True)
    info = client.info('https://www.bilibili.com/video/BV1fNnv6EEon?p=2')
    assert (info.title, info.uploader, info.duration, info.cid, info.page) == ('Show - Main', 'Uploader', 200, 22, 2)
    assert info.best.id == 30251 and info.best.label == 'Hi-Res lossless'
    assert 'logged in as me (VIP)' in info.describe() and 'part 2 of 2' in info.describe()
    assert all(signed for path, _, signed in calls if path != '/x/frontend/finger/spi')
    assert client._cookies['SESSDATA'] == 's' and client._cookies['buvid3'] == 'B3'  # visitor ids added

    del dash['flac']
    assert client.info('BV1fNnv6EEon').best.urls == ['http://a/192', 'http://b/192']


def test_info_without_audio_explains(monkeypatch):
    client, _ = fake_client(monkeypatch, {'audio': None, 'video': [{}]})
    with pytest.raises(bilibili.BilibiliError, match='members-only'):
        client.info('BV1fNnv6EEon')


def test_download_sends_range_and_falls_back(monkeypatch, tmp_path):
    client = bilibili.Client()
    seen = []

    def fake_open(url, headers=None):
        seen.append((url, headers))
        if url == 'http://dead':
            raise bilibili.BilibiliError('HTTP 403')
        if url == 'http://short':
            return FakeResponse(b'abc', {'Content-Range': 'bytes 0-9/10'})
        return FakeResponse(b'0123456789', {'Content-Range': 'bytes 0-9/10'})
    monkeypatch.setattr(client, '_open', fake_open)
    stream = bilibili.AudioStream(30280, 192000, ['http://dead', 'http://short', 'http://good'])
    progress = []
    path = client.download(stream, str(tmp_path / 'a.m4s'), lambda d, t: progress.append((d, t)))
    assert (tmp_path / 'a.m4s').read_bytes() == b'0123456789' and path.endswith('a.m4s')
    assert all(h == {'Range': 'bytes=0-'} for _, h in seen)
    assert progress[-1] == (10, 10)
    with pytest.raises(bilibili.Cancelled):
        client.download(bilibili.AudioStream(1, 1, ['http://good']), str(tmp_path / 'b'), cancelled=lambda: True)


def test_api_error_messages():
    assert 'removed' in bilibili._api_message({'code': -404, 'message': 'x'})
    assert 'bilibili error 123: boom' == bilibili._api_message({'code': 123, 'message': 'boom'})


def test_worker_routes_bilibili_and_tags_uploader(monkeypatch, tmp_path):
    source = tmp_path / 'src.wav'
    subprocess.run([ffmpeg_exe(), '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=duration=2', str(source)],
                   check=True)
    used = {}

    def fake_download_audio(url, work_dir, cookie_header='', progress=None, cancelled=None):
        used.update(url=url, cookies=cookie_header)
        target = os.path.join(work_dir, 'source.m4s')
        with open(source, 'rb') as src, open(target, 'wb') as dst:
            dst.write(src.read())
        info = bilibili.VideoInfo('标题: Title?', 'UP主', 2, 'BV1', 1, 1, 1)
        return target, info
    monkeypatch.setattr(bilibili, 'download_audio', fake_download_audio)
    cookie_file = tmp_path / 'c.txt'
    cookie_file.write_text(COOKIES_TXT, encoding='utf-8')

    request = DownloadRequest('https://www.bilibili.com/video/BV1AHnB6NEhM', format='mp3',
                              cookies=CookieSource('file', file=str(cookie_file)))
    request.validate()
    song = worker.run_download(request, str(tmp_path / 'songs'), str(tmp_path / 'work'))
    assert (song.name, song.tags) == ('标题: Title?', ['UP主'])
    assert song.path.endswith('/songs/标题 Title.mp3')
    assert 'SESSDATA=secret%2Cvalue' in used['cookies'] and 'other=' not in used['cookies']


# --- the Downloads panel ---------------------------------------------------------------------

@pytest.fixture
def panel(qtbot, tmp_path):
    p = DownloadPanel(config.DownloadSettings(tags='', format='ogg', cookie_source='browser',
                                              cookie_browser='firefox'),
                      lambda: (str(tmp_path / 'songs'), str(tmp_path / 'work')))
    qtbot.addWidget(p)
    return p


def test_panel_form_and_settings(qtbot, panel, tmp_path):
    assert panel.cookies() == CookieSource('browser', browser='firefox')
    assert not panel.cookie_file_row.isVisibleTo(panel)
    panel.cookie_choice.setCurrentIndex(panel.cookie_choice.findData('file'))
    assert panel.cookie_file_row.isVisibleTo(panel)
    panel.cookie_file.setText(str(tmp_path / 'c.txt'))
    panel.url.setText('https://example.com/v')
    panel.start_time.setText('0:05')
    panel.tags.setText('A, b')
    request = panel.build_request()
    assert (request.start, request.tags, request.format, request.name) == (5, ['A', 'b'], 'ogg', '')
    assert request.cookies == CookieSource('file', file=str(tmp_path / 'c.txt'))
    settings = panel.settings()
    assert (settings.cookie_source, settings.cookie_file, settings.format) == ('file', str(tmp_path / 'c.txt'), 'ogg')
    panel.end_time.setText('0:01')
    with pytest.raises(ValueError, match='end time'):
        panel.build_request()


def test_panel_look_up_fills_placeholders(qtbot, panel, monkeypatch):
    monkeypatch.setattr(worker, 'fetch_info', lambda url, c, a: MediaInfo('Song <Title>', 'Uploader', 125, 'details'))
    panel.url.setText('https://example.com/v')
    panel.look_up()
    qtbot.waitUntil(lambda: panel.look_up_button.isEnabled(), timeout=5000)
    assert panel.name.placeholderText() == 'Song <Title>' and panel.tags.placeholderText() == 'Uploader'
    assert '&lt;Title&gt;' in panel.info.text() and '02:05' in panel.info.text()

    monkeypatch.setattr(worker, 'fetch_info', lambda *a: (_ for _ in ()).throw(worker.DownloadFailedError('nope')))
    panel.look_up()
    qtbot.waitUntil(lambda: panel.look_up_button.isEnabled(), timeout=5000)
    assert 'nope' in panel.info.text()


def test_panel_jobs_retry_and_clear(qtbot, panel, tmp_path):
    clip = tmp_path / 'clip.wav'
    subprocess.run([ffmpeg_exe(), '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=duration=1', str(clip)],
                   check=True)
    missing = DownloadRequest(QUrl.fromLocalFile(str(tmp_path / 'later.wav')).toString(), name='Later',
                              ytdlp_args='--enable-file-urls', format='ogg')
    row = panel.start(missing)
    qtbot.waitUntil(lambda: not row.running, timeout=30000)
    assert row.button.text() == 'Retry' and row.status.text().startswith('Failed')

    os.replace(clip, tmp_path / 'later.wav')  # now the file exists: retrying works
    with qtbot.waitSignal(panel.songDownloaded, timeout=30000) as blocker:
        row.button.click()
    assert blocker.args[0].name == 'Later' and not panel.busy
    qtbot.waitUntil(lambda: row.button.text() == 'Dismiss', timeout=5000)
    panel.clear_finished()
    assert panel.rows == []


# --- live (opt-in) ---------------------------------------------------------------------------

@pytest.mark.skipif(os.environ.get('SHELLAC_NETWORK_TESTS') != '1', reason='set SHELLAC_NETWORK_TESTS=1')
def test_live_bilibili_download(tmp_path):
    url = os.environ.get('SHELLAC_BILIBILI_URL', 'https://www.bilibili.com/video/BV1AHnB6NEhM')
    info = worker.fetch_info(url)
    assert info.title and 'bilibili' in info.details
    song = worker.run_download(DownloadRequest(url, start=10, end=20, format='mp3'),
                               str(tmp_path / 'songs'), str(tmp_path / 'work'))
    assert song.duration == pytest.approx(10, abs=0.5) and song.name == info.title and song.tags
