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


@pytest.fixture(autouse=True)
def quiet_config(monkeypatch):
    """Keep test windows from grabbing global media keys or adding tray icons."""
    from shellac import config
    original = config.load_config

    def load():
        cfg = original()
        cfg.update(mediakeys='False', trayicon='False')
        return cfg
    monkeypatch.setattr(config, 'load_config', load)
