"""Global media keys (Play/Pause, Next, Previous, Stop) on Windows, even when Shellac isn't focused.

Elsewhere this is a no-op; the window's own shortcuts still handle media keys while it has focus.
If another program (e.g. a different player) already owns a key, registering it fails and that key
is simply left alone.
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, pyqtSignal

WM_HOTKEY = 0x0312
_KEYS = {  # hotkey id -> (virtual key, signal name)
    0x5E01: (0xB3, 'playPause'),  # VK_MEDIA_PLAY_PAUSE
    0x5E02: (0xB0, 'next'),       # VK_MEDIA_NEXT_TRACK
    0x5E03: (0xB1, 'previous'),   # VK_MEDIA_PREV_TRACK
    0x5E04: (0xB2, 'stop'),       # VK_MEDIA_STOP
}


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def nativeEventFilter(self, event_type, message):
        if event_type in (b'windows_dispatcher_MSG', b'windows_generic_MSG'):
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam in self._owner.registered:
                getattr(self._owner, _KEYS[msg.wParam][1]).emit()
                return True, 0
        return False, 0


class GlobalMediaKeys(QObject):
    playPause = pyqtSignal()
    next = pyqtSignal()
    previous = pyqtSignal()
    stop = pyqtSignal()

    supported = sys.platform == 'win32'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.registered = set()
        self._filter = None

    def enable(self) -> list[str]:
        """Register the keys; returns the names of keys that another program already owns."""
        if not self.supported or self._filter is not None:
            return []
        import ctypes
        user32 = ctypes.windll.user32
        taken = []
        for hotkey_id, (vk, name) in _KEYS.items():
            # hwnd=NULL: WM_HOTKEY is posted to this (the GUI) thread's message queue.
            if user32.RegisterHotKey(None, hotkey_id, 0, vk):
                self.registered.add(hotkey_id)
            else:
                taken.append(name)
        self._filter = _Filter(self)
        QCoreApplication.instance().installNativeEventFilter(self._filter)
        return taken

    def disable(self):
        if self._filter is None:
            return
        import ctypes
        for hotkey_id in self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
        self.registered.clear()
        QCoreApplication.instance().removeNativeEventFilter(self._filter)
        self._filter = None

    @property
    def enabled(self) -> bool:
        return self._filter is not None
