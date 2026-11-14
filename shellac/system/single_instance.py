"""Keep one Shellac window: a second launch hands its files to the running one and exits."""
from __future__ import annotations

import getpass
import json
import re

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name available (rare); share one name
        user = 'user'
    return 'shellac-' + re.sub(r'[^A-Za-z0-9_-]', '_', user)


def send_to_running(paths, name: str | None = None, timeout_ms: int = 500) -> bool:
    """Pass paths to an already running Shellac. Returns False if none is running."""
    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(json.dumps({'paths': list(paths)}).encode('utf-8') + b'\n')
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    # Wait for the reply before hanging up: on Windows, unread data is lost when the client disconnects.
    # A running instance answered the connection either way, so this launch should still exit.
    socket.waitForReadyRead(max(timeout_ms, 3000))
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(timeout_ms)
    return True


class InstanceServer(QObject):
    """Listens for later launches. messageReceived carries the paths they were given (maybe none)."""

    messageReceived = pyqtSignal(list)

    def __init__(self, name: str | None = None, parent=None):
        super().__init__(parent)
        self._name = name or server_name()
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)

    def listen(self) -> bool:
        # Only called when no live instance answered, so a leftover socket is stale (e.g. after a crash).
        QLocalServer.removeServer(self._name)
        return self._server.listen(self._name)

    def close(self):
        self._server.close()

    def _on_connection(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            buffer = bytearray()
            socket.readyRead.connect(lambda s=socket, b=buffer: self._read(s, b))
            socket.disconnected.connect(socket.deleteLater)

    def _read(self, socket, buffer):
        buffer.extend(bytes(socket.readAll()))
        if not buffer.endswith(b'\n'):
            return  # message not complete yet
        socket.write(b'ok\n')
        socket.flush()
        try:
            paths = json.loads(buffer.decode('utf-8')).get('paths', [])
        except (ValueError, AttributeError):
            paths = []
        buffer.clear()
        self.messageReceived.emit([p for p in paths if isinstance(p, str)])
