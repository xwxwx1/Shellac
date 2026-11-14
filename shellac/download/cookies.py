"""Where download cookies come from: nowhere, a browser's cookie store, or an exported cookies.txt.

Only the *source* is remembered in the settings (a browser name or a file path); cookie values are
read fresh for each download and never written anywhere by Shellac.
"""
from __future__ import annotations

import http.cookiejar
import sys
from dataclasses import dataclass

# Browsers yt-dlp can read cookies from, in the order offered to the user.
BROWSERS = ('firefox', 'chrome', 'edge', 'brave', 'opera', 'vivaldi', 'chromium', 'whale')
if sys.platform == 'darwin':
    BROWSERS += ('safari',)

CHROMIUM_FAMILY = {'chrome', 'edge', 'brave', 'opera', 'vivaldi', 'chromium', 'whale'}


class CookieError(Exception):
    """Cookies could not be loaded; the message is meant for the user."""


@dataclass
class CookieSource:
    kind: str = 'none'  # 'none' | 'browser' | 'file'
    browser: str = 'firefox'
    file: str = ''

    @property
    def enabled(self) -> bool:
        return self.kind in ('browser', 'file')

    def describe(self) -> str:
        if self.kind == 'browser':
            return f'cookies from {self.browser.title()}'
        if self.kind == 'file':
            return f'cookies from {self.file}'
        return 'no cookies'

    def validate(self):
        if self.kind == 'browser' and self.browser not in BROWSERS:
            raise ValueError(f'Unsupported browser: {self.browser}')
        if self.kind == 'file' and not self.file.strip():
            raise ValueError('Choose a cookies.txt file, or switch cookies off.')

    def ytdlp_options(self) -> dict:
        if self.kind == 'browser':
            return {'cookiesfrombrowser': (self.browser, None, None, None)}
        if self.kind == 'file':
            return {'cookiefile': self.file}
        return {}

    def load(self) -> http.cookiejar.CookieJar:
        """The cookies themselves. Raises CookieError with an explanation the user can act on."""
        if self.kind == 'file':
            jar = http.cookiejar.MozillaCookieJar(self.file)
            try:
                jar.load(ignore_discard=True, ignore_expires=True)
            except FileNotFoundError:
                raise CookieError(f'Cookie file not found: {self.file}') from None
            except (OSError, http.cookiejar.LoadError) as e:
                raise CookieError(f'Could not read {self.file} as a cookies.txt (Netscape format) file: {e}') from None
            return jar
        if self.kind == 'browser':
            return _from_browser(self.browser)
        return http.cookiejar.CookieJar()


class _QuietLogger:
    """yt-dlp's cookie reader logs to the console, which a windowed app doesn't have."""

    def __init__(self):
        self.messages = []

    def debug(self, message, *args, **kwargs):
        pass

    def info(self, message, *args, **kwargs):
        pass

    def warning(self, message, *args, **kwargs):
        self.messages.append(str(message))

    def error(self, message, *args, **kwargs):
        self.messages.append(str(message))

    def progress_bar(self):
        return None


def _from_browser(browser: str):
    from yt_dlp.cookies import extract_cookies_from_browser

    logger = _QuietLogger()
    try:
        jar = extract_cookies_from_browser(browser, logger=logger)
    except Exception as e:  # noqa: BLE001 - yt-dlp raises many kinds of errors here
        raise CookieError(browser_hint(browser, f'{e} {" ".join(logger.messages)}'.strip())) from None
    if len(jar) == 0 and logger.messages:
        raise CookieError(browser_hint(browser, ' '.join(logger.messages)))
    return jar


def browser_hint(browser: str, detail: str) -> str:
    """Explain the usual reasons reading a browser's cookies fails."""
    hint = f'Could not read cookies from {browser.title()}: {detail}'
    lowered = detail.lower()
    if browser in CHROMIUM_FAMILY and sys.platform == 'win32':
        if 'copy' in lowered or 'lock' in lowered or 'permission' in lowered:
            hint += f'\n\nClose {browser.title()} completely and try again: it locks its cookie database while running.'
        else:
            hint += (f'\n\nRecent versions of {browser.title()} on Windows encrypt cookies so that other programs '
                     'cannot read them. Use Firefox, or export a cookies.txt file with a browser extension '
                     'and choose "cookies.txt file" instead.')
    return hint


def cookie_header(jar, domain: str) -> str:
    """A Cookie header with the jar's cookies for `domain` and its subdomains."""
    domain = domain.lstrip('.').lower()
    pairs = {}
    for cookie in jar:
        cookie_domain = cookie.domain.lstrip('.').lower()
        if cookie_domain == domain or cookie_domain.endswith('.' + domain):
            pairs[cookie.name] = cookie.value
    return '; '.join(f'{k}={v}' for k, v in pairs.items())
