"""Application entry point."""
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from . import config
from .resources import asset
from .ui.main_window import MainWindow


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if sys.platform == 'win32':
        from ctypes import windll
        # Gives Shellac its own taskbar entry and icon instead of python.exe's.
        windll.shell32.SetCurrentProcessExplicitAppUserModelID('shellac')

    import qt_material  # imported after PyQt6 so it picks the right Qt binding

    app = QApplication(argv)
    app.setApplicationName('Shellac')
    app.setWindowIcon(QIcon(asset('Shellac.ico')))
    qt_material.apply_stylesheet(app, theme='dark_teal.xml')

    window = MainWindow(config.load_config())
    window.show()
    window.open_paths(argv[1:])
    return app.exec()
