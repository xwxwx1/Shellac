"""Application entry point."""
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from . import config
from .resources import asset
from .system.single_instance import InstanceServer, send_to_running
from .ui.main_window import MainWindow, apply_theme


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if sys.platform == 'win32':
        from ctypes import windll
        # Gives Shellac its own taskbar entry and icon instead of python.exe's.
        windll.shell32.SetCurrentProcessExplicitAppUserModelID('shellac')

    app = QApplication(argv)
    app.setApplicationName('Shellac')
    app.setWindowIcon(QIcon(asset('Shellac.ico')))

    paths = argv[1:]
    if send_to_running(paths):
        return 0  # an existing window takes the files and comes to the front
    server = InstanceServer(parent=app)
    server.listen()

    settings = config.load_config()
    apply_theme(app, settings.get('theme'))
    window = MainWindow(settings)
    server.messageReceived.connect(window.on_other_instance)

    if config.flag(settings, 'restoresession'):
        window.restore_session(on_done=lambda: window.open_paths(paths))
    else:
        window.open_paths(paths)
    window.show()
    return app.exec()
