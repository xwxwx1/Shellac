import platform
import sys

from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ... import __version__, config
from ...resources import asset


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('About Shellac')

        banner = QLabel()
        pixmap = QPixmap(asset('shellac_banner.jpg'))
        if not pixmap.isNull():
            banner.setPixmap(pixmap.scaledToWidth(480, Qt.TransformationMode.SmoothTransformation))
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text = QLabel(
            f'<h2>Shellac {__version__}</h2>'
            '<p>A music player built around tags and weighted shuffle.</p>'
            f'<p>Python {platform.python_version()} · Qt {QT_VERSION_STR} · PyQt {PYQT_VERSION_STR}'
            f' · {platform.system()} {platform.release()}</p>'
            f'<p>Settings: <code>{config.CONFIG_PATH}</code></p>'
        )
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(banner)
        layout.addWidget(text)
        layout.addWidget(buttons)
        if getattr(sys, 'frozen', False):
            self.setWindowTitle('About Shellac (standalone build)')
