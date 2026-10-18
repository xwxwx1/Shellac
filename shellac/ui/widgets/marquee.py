from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QLabel, QSizePolicy

GAP = 40      # pixels between the end of the text and its repeat
PAUSE = 60    # ticks to rest at the start of each loop
STEP_MS = 30


class MarqueeLabel(QLabel):
    """A single-line label that scrolls its text when it doesn't fit."""

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._offset = 0
        self._pause = PAUSE
        self._timer = QTimer(self)
        self._timer.setInterval(STEP_MS)
        self._timer.timeout.connect(self._tick)

    def _text_width(self):
        return self.fontMetrics().horizontalAdvance(self.text())

    def _overflows(self):
        return self._text_width() > self.contentsRect().width()

    def _restart(self):
        self._offset = 0
        self._pause = PAUSE
        if self._overflows() and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def setText(self, text):
        super().setText(text)
        self._restart()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._restart()

    def showEvent(self, event):
        super().showEvent(event)
        self._restart()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self):
        if self._pause:
            self._pause -= 1
            return
        self._offset += 1
        if self._offset >= self._text_width() + GAP:
            self._offset = 0
            self._pause = PAUSE
        self.update()

    def paintEvent(self, event):
        if not self._timer.isActive():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        rect = self.contentsRect()
        baseline = rect.top() + (rect.height() + self.fontMetrics().ascent() - self.fontMetrics().descent()) // 2
        x = rect.left() - self._offset
        painter.drawText(x, baseline, self.text())
        painter.drawText(x + self._text_width() + GAP, baseline, self.text())
