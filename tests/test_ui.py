import subprocess

import pytest
from PyQt6.QtCore import QItemSelectionModel as Sel
from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtMultimedia import QMediaDevices

from shellac import config
from shellac.core.filter import Filter, TagTerm
from shellac.core.ordering import LoopMode
from shellac.download.ffmpeg import ffmpeg_exe
from shellac.ui.main_window import MainWindow
from shellac.ui.playlist_model import NAME, FilterProxy, PlaylistModel

# --- models ----------------------------------------------------------------------------------

@pytest.fixture
def model(qtbot, make_song):
    m = PlaylistModel()
    m.add_songs([make_song(n, [t]) for n, t in zip('abcde', ['x', 'y', 'x', 'y', 'x'])])
    return m


def names(model_or_proxy):
    return [model_or_proxy.index(r, NAME).data().lstrip('▶ ') for r in range(model_or_proxy.rowCount())]


def test_model_add_remove_signals(qtbot, model, make_song):
    with qtbot.waitSignal(model.rowsInserted):
        assert len(model.add_songs([make_song('f'), make_song('a')])) == 1  # 'a' is a duplicate file
    songs = [model.song_at(1), model.song_at(2), model.song_at(4)]
    model.remove_songs(songs)
    assert names(model) == ['a', 'd', 'f']


def test_proxy_filters_and_maps_rows(qtbot, model):
    proxy = FilterProxy(model)
    proxy.set_filter(Filter(rules=[[TagTerm('x')]]))
    assert names(proxy) == ['a', 'c', 'e']
    assert proxy.row_of(model.song_at(2)) == 1
    assert proxy.row_of(model.song_at(1)) == -1


def test_reorder_through_filter_keeps_hidden_rows_and_selection(qtbot, model):
    proxy = FilterProxy(model)
    proxy.set_filter(Filter(rules=[[TagTerm('x')]]))
    selection = Sel(proxy)
    selection.select(proxy.index(2, 0), Sel.SelectionFlag.Select | Sel.SelectionFlag.Rows)
    a, c, e = proxy.visible_songs()
    model.reorder([e, a, c])
    assert names(model) == ['e', 'b', 'a', 'd', 'c']  # b and d did not move
    assert [proxy.song_at(i.row()) for i in selection.selectedRows()] == [e]


def test_playing_row_is_marked(qtbot, model):
    song = model.song_at(1)
    model.set_playing(song)
    assert model.index(1, NAME).data().startswith('▶')
    assert model.index(1, NAME).data(Qt.ItemDataRole.FontRole).bold()


# --- main window -----------------------------------------------------------------------------

@pytest.fixture
def tones(tmp_path):
    folder = tmp_path / 'music'
    (folder / 'sub').mkdir(parents=True)
    paths = []
    for i, name in enumerate(['one', 'two', 'sub/three']):
        path = folder / f'{name}.wav'
        subprocess.run([ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                        '-i', f'sine=frequency={300 + 100 * i}:duration=0.5', str(path)], check=True)
        paths.append(str(path))
    return folder, paths


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_DIR', tmp_path / 'cfg')
    monkeypatch.setattr(config, 'CONFIG_PATH', tmp_path / 'cfg' / 'config.txt')
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.chdir(tmp_path)
    w = MainWindow(config.load_config())
    qtbot.addWidget(w)
    w.player.set_volume(0)
    yield w
    w.close()


def add_and_wait(qtbot, window, paths, count):
    window.add_paths(paths)
    qtbot.waitUntil(lambda: len(window.model.playlist) == count and not window.scanner.busy, timeout=10000)


def test_folder_scan_adds_sorted_with_durations(qtbot, window, tones):
    folder, _ = tones
    add_and_wait(qtbot, window, [str(folder)], 3)
    assert [s.name for s in window.model.playlist] == ['one', 'two', 'three']
    assert all(s.duration == pytest.approx(0.5, abs=0.1) for s in window.model.playlist)
    add_and_wait(qtbot, window, [str(folder)], 3)  # adding again changes nothing


def test_drop_files_and_playlist(qtbot, window, tones, tmp_path):
    _, paths = tones
    from shellac.core import playlist_io
    from shellac.core.song import Song
    playlist = tmp_path / 'saved.slp'
    playlist_io.save(str(playlist), [Song(paths[2], 'Three!', ['T'], 5)])

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(paths[0]), QUrl.fromLocalFile(str(playlist))])
    event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    window.dropEvent(event)
    qtbot.waitUntil(lambda: len(window.model.playlist) == 2 and not window.scanner.busy, timeout=10000)
    loaded = window.model.playlist.get(paths[2])
    assert (loaded.name, loaded.tags, loaded.weight) == ('Three!', ['T'], 5)


def test_move_selection_and_filter(qtbot, window, tones):
    folder, _ = tones
    add_and_wait(qtbot, window, [str(folder)], 3)
    one, two, three = window.model.playlist
    window.select_songs([three])
    window.move_selection(-1)
    assert list(window.model.playlist) == [one, three, two]
    window.move_selection(-1, edge=True)
    assert list(window.model.playlist) == [three, one, two]
    assert window.selected_songs() == [three]

    window.model.update_song(one, tags=['keep'])
    window.set_filter(Filter(rules=[[TagTerm('keep', required=False)]]))
    assert window.proxy.visible_songs() == [three, two]
    assert '2 of 3' in window.filter_label.text()


def test_remove_and_clear(qtbot, window, tones, monkeypatch):
    folder, _ = tones
    add_and_wait(qtbot, window, [str(folder)], 3)
    one, two, three = window.model.playlist
    window.play_song(two)
    window.select_songs([two, three])
    window.remove_selected()
    assert list(window.model.playlist) == [one]
    assert window.current is None and not window.player.has_media

    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.clear_playlist()
    assert len(window.model.playlist) == 0


def test_next_previous_and_history(qtbot, window, tones):
    folder, _ = tones
    add_and_wait(qtbot, window, [str(folder)], 3)
    one, two, three = window.model.playlist
    window.loop_mode = LoopMode.LIST
    window.play_song(one)
    window.next()
    window.next()
    assert window.current is three
    window.previous()
    window.previous()
    assert window.current is one
    window.next()  # forward through history first
    assert window.current is two
    assert window.windowTitle() == 'two — Shellac'


def test_track_end_follows_loop_mode(qtbot, window, tones):
    if not QMediaDevices.audioOutputs():
        pytest.skip('no audio output device')
    folder, _ = tones
    add_and_wait(qtbot, window, [str(folder)], 3)
    one, two, _ = window.model.playlist

    window.loop_mode = LoopMode.LIST
    window.play_song(one)
    qtbot.waitUntil(lambda: window.current is two, timeout=10000)

    window.loop_mode = LoopMode.STOP
    qtbot.waitUntil(lambda: window.current is None, timeout=10000)
    assert window.now_playing.text() == 'Now Playing: '


def test_select_by_number_and_name(qtbot, window, tones, monkeypatch):
    folder, _ = tones
    add_and_wait(qtbot, window, [str(folder)], 3)
    one, _, three = window.model.playlist
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('1; three', True))
    window.select_by_name()
    assert window.selected_songs() == [one, three]


def test_position_updates_time_label_and_slider(qtbot, window, tones):
    if not QMediaDevices.audioOutputs():
        pytest.skip('no audio output device')
    _, paths = tones
    long_tone = paths[0].replace('one.wav', 'long.wav')
    subprocess.run([ffmpeg_exe(), '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=duration=4', long_tone],
                   check=True)
    add_and_wait(qtbot, window, [long_tone], 1)
    window.play_song(window.model.playlist[0])
    qtbot.waitUntil(lambda: window.time_label.text().startswith('00:02'), timeout=6000)
    assert window.progress.maximum() == 4 and window.progress.value() == 2
    window.progress.setValue(3)  # clicking the groove seeks
    qtbot.waitUntil(lambda: window.player.position >= 3, timeout=3000)
