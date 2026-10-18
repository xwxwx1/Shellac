import os

# Qt widgets in tests render offscreen, so no window pops up and CI needs no display.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from shellac.core.song import Song


@pytest.fixture
def make_song(tmp_path):
    def make(name, tags=(), weight=1, duration=60.0):
        return Song(str(tmp_path / f'{name}.mp3'), name, list(tags), weight, duration)
    return make
