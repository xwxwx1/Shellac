"""Audio from bilibili through its JSON APIs.

yt-dlp reads bilibili's video pages, but bilibili often answers unfamiliar clients with a captcha
page instead, so that route fails. The signed ("wbi") JSON APIs keep working, and are what this
module uses. Without an account it gets the standard audio streams (up to 192 kbps); with cookies
from a logged-in browser it can also get Hi-Res lossless and members-only videos.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/130.0.0.0 Safari/537.36')
API = 'https://api.bilibili.com'
CHUNK = 256 * 1024

# Audio stream ids bilibili uses, best first. Dolby is surround sound and comes last on purpose.
AUDIO_QUALITY = {30251: 'Hi-Res lossless', 30280: '192 kbps', 30232: '132 kbps', 30216: '64 kbps',
                 30250: 'Dolby Atmos'}
PREFERENCE = [30251, 30280, 30232, 30216, 30250]

# Fixed permutation used by bilibili's request signing ("wbi").
_MIXIN = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14,
          39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6,
          63, 57, 62, 11, 36, 20, 34, 44, 52]

_ID = re.compile(r'\b(BV[0-9A-Za-z]{10})\b|\bav(\d+)\b', re.IGNORECASE)


class BilibiliError(Exception):
    """Something the user should be told, in plain words."""


class Cancelled(Exception):
    pass


def matches(url: str) -> bool:
    """Whether a URL (or a bare BV/av id) is a bilibili video."""
    url = url.strip()
    host = urllib.parse.urlparse(url if '//' in url else '//' + url).netloc.lower()
    return host.endswith('bilibili.com') or host in ('b23.tv', 'bili2233.cn') or bool(_ID.fullmatch(url))


@dataclass
class AudioStream:
    id: int
    bandwidth: int
    urls: list[str]

    @property
    def label(self) -> str:
        return AUDIO_QUALITY.get(self.id, f'{self.bandwidth // 1000} kbps')


@dataclass
class VideoInfo:
    title: str
    uploader: str
    duration: float
    bvid: str
    cid: int
    page: int
    pages: int
    streams: list[AudioStream] = field(default_factory=list)
    logged_in: bool = False
    username: str = ''
    vip: bool = False

    @property
    def best(self) -> AudioStream | None:
        ranked = sorted(self.streams, key=lambda s: (PREFERENCE.index(s.id) if s.id in PREFERENCE else 99,
                                                     -s.bandwidth))
        return ranked[0] if ranked else None

    def describe(self) -> str:
        account = (f'logged in as {self.username}' + (' (VIP)' if self.vip else '')) if self.logged_in \
            else 'not logged in'
        best = self.best.label if self.best else 'no audio'
        part = f', part {self.page} of {self.pages}' if self.pages > 1 else ''
        return f'bilibili: {self.uploader}{part} · best audio {best} · {account}'


class Client:
    def __init__(self, cookie_header: str = '', timeout: float = 30):
        self._cookies = _parse_cookie_header(cookie_header)
        self._timeout = timeout
        self._wbi_key = None
        self._nav = None

    # --- HTTP --------------------------------------------------------------------------------

    def _headers(self, extra=None):
        headers = {'User-Agent': USER_AGENT, 'Referer': 'https://www.bilibili.com/',
                   'Origin': 'https://www.bilibili.com', 'Accept-Encoding': 'gzip'}
        if self._cookies:
            headers['Cookie'] = '; '.join(f'{k}={v}' for k, v in self._cookies.items())
        headers.update(extra or {})
        return headers

    def _open(self, url, headers=None):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=self._headers(headers)),
                                          timeout=self._timeout)
        except urllib.error.HTTPError as e:
            if e.code == 412:
                raise BilibiliError('bilibili is temporarily blocking requests from this connection (HTTP 412). '
                                    'Wait a few minutes, or use cookies from a browser where you use bilibili.'
                                    ) from None
            raise BilibiliError(f'bilibili answered HTTP {e.code} for {urllib.parse.urlparse(url).path}') from None
        except urllib.error.URLError as e:
            raise BilibiliError(f'Could not reach bilibili: {e.reason}') from None

    def _json(self, path, params=None, signed=False):
        if signed:
            query = self._sign(params or {})
        else:
            query = urllib.parse.urlencode(params or {})
        response = self._open(f'{API}{path}?{query}' if query else f'{API}{path}')
        raw = response.read()
        if response.headers.get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        data = json.loads(raw)
        if data.get('code') != 0:
            raise BilibiliError(_api_message(data))
        return data.get('data')

    def _ensure_visitor_cookies(self):
        # Anonymous visitor ids every browser gets on its first visit; without them bilibili's
        # anti-bot checks reject most requests.
        if 'buvid3' not in self._cookies:
            spi = self._json('/x/frontend/finger/spi')
            self._cookies.update(buvid3=spi['b_3'], buvid4=urllib.parse.quote(spi['b_4']),
                                 b_nut=str(int(time.time())))

    def nav(self) -> dict:
        if self._nav is None:
            response = self._open(f'{API}/x/web-interface/nav')
            raw = response.read()
            if response.headers.get('Content-Encoding') == 'gzip':
                raw = gzip.decompress(raw)
            # Logged out, this answers code -101 but still includes the signing keys.
            self._nav = json.loads(raw).get('data') or {}
        return self._nav

    def _sign(self, params) -> str:
        if self._wbi_key is None:
            images = self.nav().get('wbi_img') or {}
            try:
                raw_key = ''.join(u.rsplit('/', 1)[1].split('.')[0] for u in (images['img_url'], images['sub_url']))
            except (KeyError, IndexError):
                raise BilibiliError('bilibili did not provide its request-signing keys') from None
            self._wbi_key = ''.join(raw_key[i] for i in _MIXIN)[:32]
        params = dict(params, wts=int(time.time()))
        query = urllib.parse.urlencode(sorted(
            (k, ''.join(c for c in str(v) if c not in "!'()*")) for k, v in params.items()))
        return f'{query}&w_rid={hashlib.md5((query + self._wbi_key).encode()).hexdigest()}'

    # --- videos ------------------------------------------------------------------------------

    def resolve(self, url: str) -> tuple[dict, int]:
        """({'bvid': ...} or {'aid': ...}, page number) for a video URL, short link or bare id."""
        url = url.strip()
        host = urllib.parse.urlparse(url if '//' in url else '//' + url).netloc.lower()
        if host in ('b23.tv', 'bili2233.cn'):
            url = self._open(url if '//' in url else 'https://' + url).geturl()  # follow the short link
        match = _ID.search(url)
        if not match:
            raise BilibiliError('That bilibili link does not point to a video (expected a BV… or av… id).')
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        try:
            page = max(1, int(query.get('p', ['1'])[0]))
        except ValueError:
            page = 1
        return ({'bvid': match.group(1)} if match.group(1) else {'aid': match.group(2)}), page

    def info(self, url: str) -> VideoInfo:
        ident, page = self.resolve(url)
        self._ensure_visitor_cookies()
        view = self._json('/x/web-interface/wbi/view', ident, signed=True)
        pages = view.get('pages') or []
        if not pages:
            raise BilibiliError('This bilibili video has no playable parts.')
        part = pages[min(page, len(pages)) - 1]
        title = view['title'] if len(pages) == 1 else f"{view['title']} - {part.get('part') or page}"
        nav = self.nav()
        info = VideoInfo(title=title, uploader=(view.get('owner') or {}).get('name', ''),
                         duration=float(part.get('duration') or view.get('duration') or 0),
                         bvid=view['bvid'], cid=part['cid'], page=min(page, len(pages)), pages=len(pages),
                         logged_in=bool(nav.get('isLogin')), username=nav.get('uname', ''),
                         vip=bool(nav.get('vipStatus')))
        info.streams = self._streams(info)
        return info

    def _streams(self, info: VideoInfo) -> list[AudioStream]:
        play = self._json('/x/player/wbi/playurl',
                          {'bvid': info.bvid, 'cid': info.cid, 'fnval': 4048, 'fnver': 0, 'fourk': 1},
                          signed=True)
        dash = (play or {}).get('dash') or {}
        raw = list(dash.get('audio') or [])
        flac = (dash.get('flac') or {}).get('audio')  # a single stream, when there is one
        if flac:
            raw.append(flac)
        raw += (dash.get('dolby') or {}).get('audio') or []
        streams = []
        for item in raw:
            urls = [u for u in [item.get('baseUrl') or item.get('base_url')]
                    + list(item.get('backupUrl') or item.get('backup_url') or []) if u]
            if urls:
                streams.append(AudioStream(int(item.get('id', 0)), int(item.get('bandwidth', 0)), urls))
        if not streams:
            raise BilibiliError('bilibili offered no separate audio stream for this video '
                                '(it may be a paid or members-only video: try cookies from a logged-in browser).')
        return streams

    def download(self, stream: AudioStream, path: str, progress=lambda done, total: None,
                 cancelled=lambda: False) -> str:
        """Save one audio stream to `path`, trying each mirror in turn."""
        errors = []
        for url in stream.urls:
            try:
                # The CDN refuses requests without a Range header (HTTP 567).
                response = self._open(url, {'Range': 'bytes=0-'})
            except BilibiliError as e:
                errors.append(str(e))
                continue
            total = _total_size(response)
            done = 0
            with open(path, 'wb') as f:
                while True:
                    if cancelled():
                        raise Cancelled()
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    progress(done, total)
            if total and done < total:
                errors.append(f'connection closed after {done} of {total} bytes')
                continue
            return path
        raise BilibiliError('Could not download the audio from any of bilibili\'s servers: ' + '; '.join(errors))


def _total_size(response) -> int:
    content_range = response.headers.get('Content-Range') or ''
    if '/' in content_range and content_range.rsplit('/', 1)[1].isdigit():
        return int(content_range.rsplit('/', 1)[1])
    length = response.headers.get('Content-Length')
    return int(length) if length and length.isdigit() else 0


def _parse_cookie_header(header: str) -> dict:
    cookies = {}
    for part in header.split(';'):
        if '=' in part:
            name, value = part.split('=', 1)
            if name.strip():
                cookies[name.strip()] = value.strip()
    return cookies


def _api_message(data) -> str:
    code = data.get('code')
    message = data.get('message') or 'unknown error'
    known = {-404: 'This video does not exist or has been removed.',
             -403: 'Access denied: this video may need a logged-in (or VIP) account. Try cookies.',
             62002: 'This video is not visible.',
             62012: 'This video is only visible to its uploader.',
             -10403: 'This video is not available in your region.'}
    return known.get(code, f'bilibili error {code}: {message}')


def download_audio(url, work_dir, cookie_header='', progress=lambda message, fraction: None,
                   cancelled=lambda: False):
    """Download the best audio stream of a bilibili video into work_dir. Returns (path, VideoInfo)."""
    client = Client(cookie_header)
    progress('Looking up the video on bilibili…', -1)
    info = client.info(url)
    stream = info.best
    name = info.title

    def report(done, total):
        if total:
            progress(f'Downloading {name} ({stream.label}): {100 * done / total:.0f}%', done / total)
        else:
            progress(f'Downloading {name} ({stream.label}): {done // 1024} KiB', -1)

    path = client.download(stream, os.path.join(work_dir, 'source.m4s'), report, cancelled)
    return path, info
