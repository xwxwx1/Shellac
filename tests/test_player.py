import subprocess

import pytest
from PyQt6.QtMultimedia import QMediaDevices

from shellac.download.ffmpeg import ffmpeg_exe
from shellac.playback.player import AudioPlayer


@pytest.fixture
def tone(tmp_path):
    path = tmp_path / 'tone.wav'
    subprocess.run([ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'sine=frequency=440:duration=0.6', str(path)], check=True)
    return str(path)


def test_volume_and_mute(qtbot):
    player = AudioPlayer()
    player.set_volume(500)
    assert player.volume == 150
    player.set_muted(True)
    assert player._output.volume() == 0
    player.set_muted(False)
    assert player._output.volume() == pytest.approx(1.0)


def test_plays_to_end_and_reports_errors(qtbot, tone, tmp_path):
    if not QMediaDevices.audioOutputs():
        pytest.skip('no audio output device')
    player = AudioPlayer()
    player.set_volume(0)
    with qtbot.waitSignal(player.ended, timeout=10000):
        player.play_file(tone)
    assert player.duration == pytest.approx(0.6, abs=0.1)

    with qtbot.waitSignal(player.errorOccurred, timeout=10000):
        player.play_file(str(tmp_path / 'missing.mp3'))


def test_stop_clears_media(qtbot, tone):
    player = AudioPlayer()
    player.play_file(tone)
    assert player.has_media
    player.stop()
    assert not player.has_media and not player.is_playing
