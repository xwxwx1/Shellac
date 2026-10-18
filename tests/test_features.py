"""Tests for the stage 6 features: queue, sorting/search/tags, editing, missing files, sessions, system."""
import os
import subprocess
import sys
import uuid

import pytest
from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QMessageBox

from shellac import config
from shellac.core.filter import Filter, TagTerm
from shellac.core.ordering import LoopMode
from shellac.download.ffmpeg import ffmpeg_exe
from shellac.system.mediakeys import WM_HOTKEY, GlobalMediaKeys
from shellac.system.single_instance import InstanceServer, send_to_running
from shellac.ui.dialogs.about_dialog import AboutDialog
from shellac.ui.dialogs.filter_dialog import FilterDialog
from shellac.ui.dialogs.settings_dialog import SettingsDialog
from shellac.ui.main_window import MainWindow
from shellac.ui.playlist_model import LENGTH, NAME, TAGS, WEIGHT


def make_tone(path, seconds, artist=None, album=None):
    cmd = [ffmpeg_exe(), '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', f'sine=duration={seconds}']
    if artist:
        cmd += ['-metadata', f'artist={artist}']
    if album:
        cmd += ['-metadata', f'album={album}']
    subprocess.run([*cmd, str(path)], check=True)
    return str(path)


@pytest.fixture
def music(tmp_path):
    folder = tmp_path / 'music'
    folder.mkdir()
    specs = [('alpha', 3, 'Ann', 'First'), ('bravo', 1, 'Bob', None), ('charlie', 2, 'Ann', 'Second')]
    return folder, [make_tone(folder / f'{n}.mp3', d, a, al) for n, d, a, al in specs]


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_DIR', tmp_path / 'cfg')
    monkeypatch.setattr(config, 'CONFIG_PATH', tmp_path / 'cfg' / 'config.txt')
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'data')
    return tmp_path


def new_window(qtbot):
    w = MainWindow(config.load_config())
    qtbot.addWidget(w)
    w.player.set_volume(0)
    return w


@pytest.fixture
def window(qtbot, isolated, music):
    w = new_window(qtbot)
    w.add_paths([str(music[0])])
    qtbot.waitUntil(lambda: len(w.model.playlist) == 3 and not w.scanner.busy, timeout=10000)
    return w


def names(songs):
    return [s.name for s in songs]


# --- metadata --------------------------------------------------------------------------------

def test_added_files_take_artist_tag_and_album(qtbot, window):
    a, b, c = window.model.playlist
    assert [s.tags for s in (a, b, c)] == [['Ann'], ['Bob'], ['Ann']]
    assert (a.album, b.album) == ('First', None)
    qtbot.waitUntil(lambda: window.tag_browser.list.count() == 2)  # the browser refreshes on a short delay
    assert window.tag_browser.list.item(0).text() == 'Ann  (2)'


# --- in-place editing ------------------------------------------------------------------------

def test_inline_editing(qtbot, window):
    proxy = window.proxy
    with qtbot.waitSignal(window.model.songEdited):
        assert proxy.setData(proxy.index(0, WEIGHT), 7)
    assert proxy.setData(proxy.index(0, TAGS), 'X, y ,X')
    assert proxy.setData(proxy.index(0, NAME), '  New name ')
    assert not proxy.setData(proxy.index(0, NAME), '   ')
    assert not proxy.setData(proxy.index(0, LENGTH), '1:00')
    song = window.model.playlist[0]
    assert (song.name, song.tags, song.weight) == ('New name', ['X', 'y'], 7)
    assert proxy.setData(proxy.index(0, WEIGHT), -3) and song.weight == 0


# --- sorting, search and tags ----------------------------------------------------------------

def test_sorting_and_clearing_sort(qtbot, window):
    header = window.table.horizontalHeader()
    header.setSortIndicator(LENGTH, Qt.SortOrder.DescendingOrder)
    assert names(window.proxy.visible_songs()) == ['alpha', 'charlie', 'bravo']
    window.select_songs([window.model.playlist[1]])
    window.move_selection(-1)  # refused while sorted
    assert names(window.model.playlist) == ['alpha', 'bravo', 'charlie']
    window.clear_sort()
    assert names(window.proxy.visible_songs()) == ['alpha', 'bravo', 'charlie']


def test_search_and_tag_browser(qtbot, window):
    window.search.setText('CHAR')
    assert names(window.proxy.visible_songs()) == ['charlie']
    window.search.setText('first')  # albums are searched too
    assert names(window.proxy.visible_songs()) == ['alpha']
    window.search.clear()

    window.tag_browser.set_checked(['Ann'])
    assert names(window.proxy.visible_songs()) == ['alpha', 'charlie']
    assert 'Tags: Ann' in window.filter_label.text() and '2 of 3' in window.filter_label.text()
    window.clear_filter()
    assert window.proxy.rowCount() == 3 and window.filter_label.text() == ''


def test_filter_dialog_text_query(qtbot):
    dialog = FilterDialog(None, Filter(), ['rock', 'live'])
    qtbot.addWidget(dialog)
    dialog.query_edit.setText('rock AND NOT live OR "big band"')
    dialog.query_edit.textEdited.emit(dialog.query_edit.text())
    assert dialog.filter.rules == ((TagTerm('rock'), TagTerm('live', False)), (TagTerm('big band'),))
    assert dialog.tree.topLevelItemCount() == 2
    dialog.query_edit.textEdited.emit('rock AND')
    assert dialog.query_error.text()


# --- drag and drop ---------------------------------------------------------------------------

def test_drag_reorder_through_filter(qtbot, window):
    c = window.model.playlist[2]
    window._on_songs_dragged([c.path], 0)
    assert names(window.model.playlist) == ['charlie', 'alpha', 'bravo']
    window.tag_browser.set_checked(['Ann'])  # visible: charlie, alpha
    window._on_songs_dragged([c.path], 2)  # to the end of the visible rows
    assert names(window.model.playlist) == ['alpha', 'charlie', 'bravo']  # bravo stays put
    assert window.selected_songs() == [c]


def test_files_dropped_between_rows(qtbot, window, tmp_path):
    extra = make_tone(tmp_path / 'delta.mp3', 1)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(extra)])
    rect = window.table.visualRect(window.proxy.index(1, 0))
    event = QDropEvent(QPointF(rect.center().x(), rect.top() + 2), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    window.show()
    with qtbot.waitSignal(window.table.filesDropped) as blocker:
        window.table.dropEvent(event)
    assert [os.path.normpath(p) for p in blocker.args[0]] == [os.path.normpath(extra)]
    qtbot.waitUntil(lambda: len(window.model.playlist) == 4 and not window.scanner.busy, timeout=10000)
    assert names(window.model.playlist)[blocker.args[1]] == 'delta'


# --- up next and shuffle ---------------------------------------------------------------------

def test_up_next_takes_priority(qtbot, window):
    a, b, c = window.model.playlist
    window.loop_mode = LoopMode.LIST
    window.play_song(a)
    window.select_songs([c])
    window.queue_selected_next()
    window.select_songs([b])
    window.queue_selected()
    assert window.queue_panel.list.count() == 2 and window.queue_dock.windowTitle() == 'Up Next (2)'
    window.next()
    assert window.current is c
    window._on_track_ended()  # auto-advance also drains the queue first
    assert window.current is b
    window.next()
    assert window.current is c  # back to the loop mode: list order after b


def test_queue_forgets_removed_songs_and_plays_on_double_click(qtbot, window):
    a, b, c = window.model.playlist
    window.queue.append([a, b, c])
    window._on_queue_changed()
    window.select_songs([b])
    window.remove_selected()
    assert list(window.queue) == [a, c]
    window.queue_panel.list.itemDoubleClicked.emit(window.queue_panel.list.item(1))
    assert window.current is c and list(window.queue) == [a]


def test_shuffle_without_repeats(qtbot, window):
    window.loop_mode = LoopMode.SHUFFLE
    window.no_repeat_action.trigger()
    assert config.flag(config.load_config(), 'norepeatshuffle')
    window.play_song(window.model.playlist[0])
    played = {window.current.name}
    for _ in range(2):
        window.next()
        played.add(window.current.name)
    assert played == {'alpha', 'bravo', 'charlie'}


# --- missing files ---------------------------------------------------------------------------

def test_missing_files_are_skipped_located_and_removed(qtbot, window, monkeypatch, tmp_path):
    a, b, c = window.model.playlist
    moved = tmp_path / 'moved.mp3'
    os.replace(b.path, moved)
    window.loop_mode = LoopMode.LIST
    window.play_song(a)
    window.next()
    assert window.current is c and b.missing  # skipped, and now shown as missing
    assert window.model.index(1, NAME).data(Qt.ItemDataRole.FontRole).italic()

    class FakeDialog:
        def __init__(self, *args):
            pass
        exec = staticmethod(lambda: True)
        selectedFiles = staticmethod(lambda: [str(moved)])
    monkeypatch.setattr(window, '_file_dialog', lambda *a: FakeDialog())
    window.select_songs([b])
    window.locate_selected()
    assert not b.missing and window.model.playlist.get(str(moved)) is b

    os.remove(str(moved))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.remove_missing()
    assert names(window.model.playlist) == ['alpha', 'charlie']


# --- session ---------------------------------------------------------------------------------

def test_session_roundtrip(qtbot, isolated, music):
    first = new_window(qtbot)
    first.add_paths([str(music[0])])
    qtbot.waitUntil(lambda: len(first.model.playlist) == 3 and not first.scanner.busy, timeout=10000)
    a, b, c = first.model.playlist
    first.model.update_song(b, tags=['Bob', 'keep'], weight=5)
    first.play_song(c)
    first.volume.setValue(42)
    first.queue.append([a])
    first.set_filter(Filter(rules=[[TagTerm('Bob', False)]]))
    first.search.setText('a')
    first.table.horizontalHeader().setSortIndicator(NAME, Qt.SortOrder.DescendingOrder)
    first.close()
    assert config.session_path().exists()

    second = new_window(qtbot)
    done = []
    second.restore_session(on_done=lambda: done.append(True))
    qtbot.waitUntil(lambda: bool(done), timeout=10000)
    restored = second.model.playlist
    assert names(restored) == ['alpha', 'bravo', 'charlie']
    assert (restored[1].tags, restored[1].weight) == (['Bob', 'keep'], 5)
    assert second.current is restored[2] and second.player.has_media and not second.player.is_playing
    assert second.volume.value() == 42 and list(second.queue) == [restored[0]]
    assert second.proxy.filter.rules == ((TagTerm('Bob', False),),)
    assert second.search.text() == 'a' and second.proxy.sortColumn() == NAME
    assert names(second.proxy.visible_songs()) == ['charlie', 'alpha']
    second.close()


def test_session_disabled(qtbot, isolated, music):
    config.load_config()
    config.edit_config('restoresession', 'False')
    w = new_window(qtbot)
    w.close()
    assert not config.session_path().exists()


# --- dialogs ---------------------------------------------------------------------------------

def test_settings_dialog_applies(qtbot, window, monkeypatch, tmp_path):
    import shellac.ui.main_window as mw
    applied = []
    monkeypatch.setattr(mw, 'apply_theme', lambda app, theme: applied.append(theme))
    dialog = SettingsDialog(window, window.config, ['dark_teal.xml', 'light_blue.xml'])
    qtbot.addWidget(dialog)
    dialog.theme.setCurrentIndex(1)
    dialog.song_dir.setText(str(tmp_path / 'elsewhere'))
    dialog.no_repeat.setChecked(True)
    dialog.folders.addItem('C:/shortcut')
    values = dialog.values()
    assert values['theme'] == 'light_blue.xml' and values['norepeatshuffle'] == 'True'

    monkeypatch.setattr(mw, 'SettingsDialog', lambda *a: type('D', (), {'exec': lambda s: True,
                                                                        'values': lambda s: values})())
    window.settings_dialog()
    assert applied == ['light_blue.xml']
    assert window.song_dir.rstrip('/').endswith('elsewhere') and os.path.isdir(window.song_dir)
    assert window.no_repeat_action.isChecked()
    assert config.sidebar_folders(window.config) == ['C:/shortcut']


def test_about_dialog_shows_version(qtbot):
    from shellac import __version__
    dialog = AboutDialog()
    qtbot.addWidget(dialog)
    assert __version__ in dialog.findChildren(type(dialog.layout().itemAt(1).widget()))[1].text()


# --- system integration ----------------------------------------------------------------------

def test_single_instance_hands_over_paths(qtbot):
    name = f'shellac-test-{uuid.uuid4().hex[:8]}'
    assert not send_to_running(['x'], name=name, timeout_ms=200)  # nobody listening yet
    server = InstanceServer(name)
    assert server.listen()
    # A second launch is a separate process, which lets this one's event loop answer it.
    script = ('import sys; from PyQt6.QtCore import QCoreApplication; app = QCoreApplication([]); '
              'from shellac.system.single_instance import send_to_running; '
              f'sys.exit(0 if send_to_running(["C:/a.mp3", "D:/歌"], name={name!r}) else 3)')
    with qtbot.waitSignal(server.messageReceived, timeout=15000) as blocker:
        process = subprocess.Popen([sys.executable, '-c', script])
    assert process.wait(15) == 0
    assert blocker.args == [['C:/a.mp3', 'D:/歌']]
    server.close()


@pytest.mark.skipif(not GlobalMediaKeys.supported, reason='global media keys are Windows-only')
def test_global_media_keys(qtbot):
    import ctypes
    keys = GlobalMediaKeys()
    keys.enable()
    try:
        if not keys.registered:
            pytest.skip('another program owns every media key')
        hotkey_id = min(keys.registered)
        signal = {0x5E01: keys.playPause, 0x5E02: keys.next, 0x5E03: keys.previous, 0x5E04: keys.stop}[hotkey_id]
        with qtbot.waitSignal(signal, timeout=3000):
            thread = ctypes.windll.kernel32.GetCurrentThreadId()
            ctypes.windll.user32.PostThreadMessageW(thread, WM_HOTKEY, hotkey_id, 0)
    finally:
        keys.disable()
    assert not keys.enabled and not keys.registered
