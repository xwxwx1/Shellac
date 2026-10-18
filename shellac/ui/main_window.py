"""The Shellac main window: playlist table, transport controls and menus."""
from __future__ import annotations

import os

from PyQt6.QtCore import QItemSelection, QItemSelectionModel, QSize, QStandardPaths, Qt, QUrl
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSlider,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import config as cfg
from ..core import playlist_io
from ..core.filter import Filter
from ..core.history import History
from ..core.ordering import LoopMode, moved_to_edge, pick_next, shifted
from ..core.song import AUDIO_EXTENSIONS, is_audio_file, song_from_file
from ..core.timefmt import format_time
from ..download.worker import DownloadJob
from ..playback.player import MAX_VOLUME, AudioPlayer
from ..resources import asset
from .dialogs.download_dialog import DownloadDialog
from .dialogs.filter_dialog import FilterDialog
from .dialogs.song_dialog import SongDialog
from .playlist_model import ARTIST, LENGTH, NAME, TAGS, WEIGHT, FilterProxy, PlaylistModel
from .scanner import Scanner
from .widgets.marquee import MarqueeLabel

PLAYLIST_FILTER = 'Shellac Playlist (*.slp)'
AUDIO_FILTER = f"Audio files ({' '.join(f'*.{e}' for e in AUDIO_EXTENSIONS)})"


class PlaylistView(QTableView):
    def keyboardSearch(self, search):
        # Letter keys are shortcuts (e.g. L for loop), not type-to-search.
        pass


class MainWindow(QMainWindow):
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.song_dir = config['songdir']
        self.download_dir = config['downloaddir']
        self.save_path = config.get('savedir', '')
        self.loop_mode = LoopMode(cfg.loop_mode(config))

        self.model = PlaylistModel(self)
        self.proxy = FilterProxy(self.model, self)
        self.player = AudioPlayer(self)
        self.history = History()
        self.scanner = Scanner(self)
        self.current = None  # the song loaded in the player
        self.downloads = []  # running DownloadJobs

        self._icons = {}
        self._dragging_slider = False
        self._syncing_slider = False
        self._shown_second = -1

        self.setWindowTitle('Shellac')
        self.setWindowIcon(self._icon('Shellac.ico'))
        self.setAcceptDrops(True)
        self.resize(1280, 760)
        self._build_ui()
        self._build_actions()
        self._connect_player()
        for signal in (self.proxy.rowsInserted, self.proxy.rowsRemoved, self.proxy.modelReset,
                       self.proxy.layoutChanged):
            signal.connect(self._refresh_filter_label)
        self._refresh_loop_button()
        self._refresh_volume_icon()
        self._refresh_filter_label()

    # =========================================================================================
    # construction
    # =========================================================================================

    def _icon(self, name):
        if name not in self._icons:
            self._icons[name] = QIcon(asset(name))
        return self._icons[name]

    def _tool_button(self, icon, tip, slot):
        button = QToolButton()
        button.setIcon(self._icon(icon))
        button.setIconSize(QSize(24, 24))
        button.setAutoRaise(True)
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    def _build_ui(self):
        self.table = PlaylistView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(26)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(NAME, QHeaderView.ResizeMode.Stretch)
        for column, width in ((LENGTH, 95), (TAGS, 280), (ARTIST, 180), (WEIGHT, 95)):
            self.table.setColumnWidth(column, width)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)

        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 0)
        self.progress.sliderPressed.connect(self._on_slider_pressed)
        self.progress.sliderReleased.connect(self._on_slider_released)
        self.progress.valueChanged.connect(self._on_slider_value)

        self.prev_button = self._tool_button('last.png', 'Previous song  ([)', self.previous)
        self.play_button = self._tool_button('play.png', 'Play / pause  (Space)', self.toggle_play)
        self.next_button = self._tool_button('next.png', 'Next song  (])', self.next)
        self.loop_button = self._tool_button('loop_list.png', '', self.cycle_loop_mode)
        self.mute_button = self._tool_button('volume_2.png', 'Mute  (Alt+M)', self.toggle_mute)
        self.up_button = self._tool_button('up.png', 'Move selection up  (Shift+Up; hold Alt for top)',
                                           lambda: self.move_selection(-1))
        self.down_button = self._tool_button('down.png', 'Move selection down  (Shift+Down; hold Alt for bottom)',
                                             lambda: self.move_selection(+1))

        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, MAX_VOLUME)
        self.volume.setValue(self.player.volume)
        self.volume.setFixedWidth(130)
        self.volume.valueChanged.connect(self.set_volume)
        self.volume_label = QLabel(str(self.player.volume))
        self.volume_label.setMinimumWidth(32)
        self.time_label = QLabel('--:-- / --:--')
        self.time_label.setMinimumWidth(130)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.now_playing = MarqueeLabel('Now Playing: ')

        controls = QHBoxLayout()
        for widget in (self.prev_button, self.play_button, self.next_button, self.loop_button):
            controls.addWidget(widget)
        controls.addSpacing(16)
        controls.addWidget(self.mute_button)
        controls.addWidget(self.volume)
        controls.addWidget(self.volume_label)
        controls.addWidget(self.time_label)
        controls.addWidget(self.now_playing, 1)
        controls.addWidget(self.up_button)
        controls.addWidget(self.down_button)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.progress)
        layout.addLayout(controls)
        self.setCentralWidget(central)

        self.download_label = QLabel()
        self.filter_label = QLabel()
        self.statusBar().addPermanentWidget(self.download_label)
        self.statusBar().addPermanentWidget(self.filter_label)

    def _action(self, menu, text, shortcuts, slot, tip=''):
        action = QAction(text, self)
        if shortcuts:
            action.setShortcuts([QKeySequence(s) for s in shortcuts])
        action.setStatusTip(tip)
        action.triggered.connect(slot)
        if menu is not None:
            menu.addAction(action)
        else:
            self.addAction(action)
        return action

    def _build_actions(self):
        bar = self.menuBar()

        play = bar.addMenu('Play')
        self._action(play, 'Play / Pause', ['Space'], self.toggle_play)
        self._action(play, 'Next Song', ['Alt+N', ']'], self.next, 'Next song, by loop mode and playlist')
        self._action(play, 'Previous Song', ['Alt+B', '['], self.previous, 'Previous song in history')
        self._action(play, 'Change Loop Mode', ['Alt+L', 'L'], self.cycle_loop_mode)
        self._action(play, 'Mute / Unmute', ['Alt+M'], self.toggle_mute)
        play.addSeparator()
        self._action(play, 'Select…', ['Alt+P'], self.select_by_name, 'Select songs by name or row number')
        self._action(play, 'Deselect', ['Esc'], self.table.clearSelection)

        file = bar.addMenu('File')
        self._action(file, 'Add Songs…', ['Alt+A'], self.add_songs_dialog, 'Add audio files to the playlist')
        self._action(file, 'Add Folder…', ['Alt+Shift+O'], self.add_folder_dialog,
                     'Add every audio file in a folder')
        file.addSeparator()
        self._action(file, 'Load Playlist…', ['Alt+O'], self.load_playlist_dialog)
        self._action(file, 'Save Playlist…', ['Alt+S'], self.save_playlist_dialog)
        file.addSeparator()
        self.remove_action = self._action(file, 'Remove Selected', ['Delete'], self.remove_selected)
        self._action(file, 'Clear Playlist', ['Alt+Shift+Delete'], self.clear_playlist)
        file.addSeparator()
        self._action(file, 'Download from Internet…', ['Alt+Ctrl+D'], self.download_dialog,
                     'Download audio from a URL with yt-dlp')
        self.cancel_downloads_action = self._action(file, 'Cancel Downloads', [], self.cancel_downloads)
        self.cancel_downloads_action.setEnabled(False)
        file.addSeparator()
        self._action(file, 'Exit', ['Ctrl+Q'], self.close)

        edit = bar.addMenu('Edit')
        self.edit_action = self._action(edit, 'Edit Selected…', ['Alt+E'], self.edit_selected)
        self._action(edit, 'Move Up', ['Shift+Up'], lambda: self.move_selection(-1))
        self._action(edit, 'Move Down', ['Shift+Down'], lambda: self.move_selection(+1))
        self._action(edit, 'Move to Top', ['Alt+Shift+Up'], lambda: self.move_selection(-1, edge=True))
        self._action(edit, 'Move to Bottom', ['Alt+Shift+Down'], lambda: self.move_selection(+1, edge=True))
        edit.addSeparator()
        self._action(edit, 'Add/Edit Filter…', ['Ctrl+F'], self.edit_filter)
        self._action(edit, 'Clear Filter', ['Ctrl+Alt+R'], self.clear_filter)

        play_selected = QAction('Play', self)
        play_selected.triggered.connect(lambda: self._play_first_selected())
        self.table.addActions([play_selected, self.edit_action, self.remove_action])

    def _connect_player(self):
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playingChanged.connect(
            lambda playing: self.play_button.setIcon(self._icon('pause.png' if playing else 'play.png')))
        self.player.ended.connect(self._on_track_ended)
        self.player.errorOccurred.connect(lambda message: self.statusBar().showMessage(message, 10000))

    # =========================================================================================
    # playback
    # =========================================================================================

    def play_song(self, song, record=True):
        if song is None:
            self.stop_playback()
            return
        self.current = song
        if record:
            self.history.push(song)
        self.model.set_playing(song)
        self.player.play_file(song.path)
        self._show_now_playing()

    def stop_playback(self):
        self.player.stop()
        self.current = None
        self.model.set_playing(None)
        self._shown_second = -1
        self._sync_slider(0, 0)
        self.time_label.setText('--:-- / --:--')
        self._show_now_playing()

    def _show_now_playing(self):
        name = self.current.name if self.current else ''
        self.now_playing.setText(f'Now Playing: {name}')
        self.setWindowTitle(f'{name} — Shellac' if name else 'Shellac')

    def toggle_play(self):
        if self.player.has_media:
            self.player.toggle()
        else:
            self._play_first_selected()

    def _play_first_selected(self):
        songs = self.selected_songs() or self.proxy.visible_songs()
        if songs:
            self.play_song(songs[0])

    def next(self):
        song = self.history.forward()
        if song is not None and song in self.model.playlist:
            self.play_song(song, record=False)
            return
        self.play_song(pick_next(self.loop_mode, self.proxy.visible_songs(), self.current, manual=True))

    def previous(self):
        song = self.history.back()
        if song is not None:
            self.play_song(song, record=False)
        elif self.current is not None:
            self.player.seek(0)

    def _on_track_ended(self):
        song = pick_next(self.loop_mode, self.proxy.visible_songs(), self.current, manual=False)
        if song is None:
            self.stop_playback()
        else:
            self.play_song(song, record=song is not self.current)

    def cycle_loop_mode(self):
        self.loop_mode = self.loop_mode.cycled()
        cfg.edit_config('loopmode', int(self.loop_mode))
        self._refresh_loop_button()
        self.statusBar().showMessage(f'Loop mode: {self.loop_mode.label}', 3000)

    def _refresh_loop_button(self):
        self.loop_button.setIcon(self._icon(f'loop_{self.loop_mode.icon_name}.png'))
        self.loop_button.setToolTip(f'Loop mode: {self.loop_mode.label}  (L)')

    # --- volume ------------------------------------------------------------------------------

    def set_volume(self, value):
        self.player.set_volume(value)
        self.volume_label.setText(str(value))
        self._refresh_volume_icon()

    def toggle_mute(self):
        self.player.set_muted(not self.player.muted)
        self._refresh_volume_icon()

    def _refresh_volume_icon(self):
        volume = self.player.volume
        if volume == 0:
            name = 'volume_0'
        else:
            level = 1 if volume <= 50 else 2 if volume <= 100 else 3
            name = f'volume_{level}' + ('_mute' if self.player.muted else '')
        self.mute_button.setIcon(self._icon(f'{name}.png'))

    # --- progress ----------------------------------------------------------------------------

    def _sync_slider(self, value, maximum=None):
        self._syncing_slider = True
        if maximum is not None:
            self.progress.setMaximum(maximum)
        self.progress.setValue(value)
        self._syncing_slider = False

    def _update_time_label(self, position):
        self.time_label.setText(f'{format_time(position)} / {format_time(self.player.duration)}')

    def _on_duration(self, seconds):
        self._sync_slider(self.progress.value(), max(0, round(seconds)))
        self._update_time_label(self.player.position)

    def _on_position(self, seconds):
        # Qt reports position many times a second; only repaint when the shown second changes.
        second = round(seconds)
        if self._dragging_slider or second == self._shown_second:
            return
        self._shown_second = second
        self._sync_slider(second)
        self._update_time_label(seconds)

    def _on_slider_pressed(self):
        self._dragging_slider = True

    def _on_slider_released(self):
        self._dragging_slider = False
        self.player.seek(self.progress.sliderPosition())

    def _on_slider_value(self, value):
        if self._dragging_slider:
            self._update_time_label(value)
        elif not self._syncing_slider:
            self.player.seek(value)  # clicked on the groove or used the keyboard

    # =========================================================================================
    # selection
    # =========================================================================================

    def selected_songs(self):
        rows = sorted(index.row() for index in self.table.selectionModel().selectedRows())
        return [self.proxy.song_at(row) for row in rows]

    def select_songs(self, songs):
        selection = QItemSelection()
        for song in songs:
            row = self.proxy.row_of(song)
            if row >= 0:
                selection.select(self.proxy.index(row, 0), self.proxy.index(row, self.proxy.columnCount() - 1))
        flags = QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows
        self.table.selectionModel().select(selection, flags)
        if songs and self.proxy.row_of(songs[0]) >= 0:
            self.table.scrollTo(self.proxy.index(self.proxy.row_of(songs[0]), 0))

    def select_by_name(self):
        text, ok = QInputDialog.getText(self, 'Select Songs',
                                        'Names or row numbers, separated by ";":')
        if not ok or not text.strip():
            return
        playlist = self.model.playlist
        chosen = []
        # Numbers are the row numbers shown in the table, i.e. positions in the whole playlist.
        for part in (p.strip() for p in text.split(';')):
            if part.isdigit() and 1 <= int(part) <= len(playlist):
                chosen.append(playlist[int(part) - 1])
            else:
                chosen.extend(s for s in playlist if s.name == part)
        chosen = [s for s in chosen if self.proxy.row_of(s) >= 0]
        if chosen:
            self.select_songs(chosen)
        else:
            self.statusBar().showMessage('No matching songs', 4000)

    def _on_double_click(self, index):
        song = self.proxy.song_at(index.row())
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            self.edit_song(song)
        else:
            self.play_song(song)

    def move_selection(self, delta, edge=False):
        songs = self.selected_songs()
        if not songs:
            return
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
            edge = True
        visible = self.proxy.visible_songs()
        order = moved_to_edge(visible, songs, top=delta < 0) if edge else shifted(visible, songs, delta)
        if all(a is b for a, b in zip(order, visible)):
            return
        self.model.reorder(order)
        self.table.scrollTo(self.proxy.index(self.proxy.row_of(songs[0 if delta < 0 else -1]), 0))

    # =========================================================================================
    # editing the playlist
    # =========================================================================================

    def _file_dialog(self, mode, title, name_filter='', directory=''):
        dialog = QFileDialog(self, title, directory or self.song_dir, name_filter)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog)  # the native one ignores the sidebar
        dialog.setFileMode(mode)
        dialog.setViewMode(QFileDialog.ViewMode.List)
        locations = [QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation),
                     QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation),
                     self.song_dir, *cfg.sidebar_folders(self.config)]
        dialog.setSidebarUrls([QUrl('file:')] + [QUrl.fromLocalFile(os.path.expanduser(p))
                                                 for p in locations if p])
        return dialog

    def add_songs_dialog(self):
        dialog = self._file_dialog(QFileDialog.FileMode.ExistingFiles, 'Add Songs', AUDIO_FILTER)
        if not dialog.exec():
            return
        files = dialog.selectedFiles()
        if len(files) == 1:
            self.add_song_with_details(files[0])
        else:
            self.add_paths(files)

    def add_song_with_details(self, path):
        if self.model.playlist.get(path):
            self.statusBar().showMessage('That file is already in the playlist', 4000)
            return
        song = song_from_file(path)
        dialog = SongDialog(self, 'Add Song', song.name, song.tags, song.weight, song.path)
        if dialog.exec():
            self.model.playlist.update(song, dialog.name, dialog.tags, dialog.weight)
            self.model.add_songs([song])

    def add_folder_dialog(self):
        dialog = self._file_dialog(QFileDialog.FileMode.Directory, 'Add Folder')
        dialog.setOption(QFileDialog.Option.ShowDirsOnly)
        if dialog.exec():
            self.add_paths(dialog.selectedFiles())

    def add_paths(self, items, done_message='Added {added} songs'):
        """Add files, folders or playlist entries in the background."""
        counts = {'added': 0, 'skipped': 0}

        def on_batch(songs):
            added = len(self.model.add_songs(songs))
            counts['added'] += added
            counts['skipped'] += len(songs) - added
            self.statusBar().showMessage(f"Adding songs… {counts['added']}")

        def on_done():
            message = done_message.format(**counts)
            if counts['skipped']:
                message += f" ({counts['skipped']} already in the playlist)"
            self.statusBar().showMessage(message, 6000)

        self.scanner.scan(items, on_batch, on_done)

    def open_paths(self, paths):
        """Open dropped or command-line paths: playlists are loaded, audio files and folders added."""
        media = []
        for path in paths:
            if path.lower().endswith('.slp'):
                self.load_playlist(path)
            elif os.path.isdir(path) or is_audio_file(path):
                media.append(path)
        if media:
            self.add_paths(media)

    def load_playlist_dialog(self):
        dialog = self._file_dialog(QFileDialog.FileMode.ExistingFile, 'Load Playlist', PLAYLIST_FILTER,
                                   self.save_path)
        if dialog.exec():
            self.load_playlist(dialog.selectedFiles()[0])

    def load_playlist(self, path):
        try:
            entries = playlist_io.load(path)
        except (OSError, playlist_io.PlaylistFormatError) as e:
            QMessageBox.warning(self, 'Load Playlist', f'Could not load {path}:\n{e}')
            return
        self._remember_save_path(path)
        self.add_paths(entries, f'Loaded {os.path.basename(path)}: {{added}} songs')

    def save_playlist_dialog(self):
        dialog = self._file_dialog(QFileDialog.FileMode.AnyFile, 'Save Playlist', PLAYLIST_FILTER, self.save_path)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDefaultSuffix('slp')
        if not dialog.exec():
            return
        path = dialog.selectedFiles()[0]
        try:
            playlist_io.save(path, self.model.playlist)
        except OSError as e:
            QMessageBox.warning(self, 'Save Playlist', f'Could not save {path}:\n{e}')
            return
        self._remember_save_path(path)
        self.statusBar().showMessage(f'Saved {len(self.model.playlist)} songs to {path}', 6000)

    def _remember_save_path(self, path):
        self.save_path = path
        cfg.edit_config('savedir', path)

    def remove_selected(self):
        songs = self.selected_songs()
        if not songs:
            return
        if self.current in songs:
            self.stop_playback()
        self.model.remove_songs(songs)
        self.history.remove(songs)

    def clear_playlist(self):
        if not len(self.model.playlist):
            return
        answer = QMessageBox.question(self, 'Clear Playlist',
                                      f'Remove all {len(self.model.playlist)} songs from the playlist?')
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.stop_playback()
        self.model.clear()
        self.history.clear()

    def edit_selected(self):
        songs = self.selected_songs()
        if songs:
            self.edit_song(songs[0])

    def edit_song(self, song):
        dialog = SongDialog(self, 'Edit Song', song.name, song.tags, song.weight, song.path)
        if dialog.exec():
            self.model.update_song(song, dialog.name, dialog.tags, dialog.weight)
            if song is self.current:
                self._show_now_playing()

    # --- filter ------------------------------------------------------------------------------

    def edit_filter(self):
        dialog = FilterDialog(self, self.proxy.filter, self.model.playlist.all_tags())
        if dialog.exec():
            self.set_filter(dialog.filter)

    def clear_filter(self):
        self.set_filter(Filter())

    def set_filter(self, new_filter):
        self.proxy.set_filter(new_filter)
        self._refresh_filter_label()

    def _refresh_filter_label(self):
        f = self.proxy.filter
        if f.is_empty:
            self.filter_label.setText('')
        else:
            self.filter_label.setText(f'Filter: {f.describe()}  —  '
                                      f'{self.proxy.rowCount()} of {len(self.model.playlist)} songs')

    # =========================================================================================
    # downloads
    # =========================================================================================

    def download_dialog(self):
        dialog = DownloadDialog(self, cfg.DownloadSettings.parse(self.config.get('downloadconfig')))
        if not dialog.exec():
            return
        if dialog.remember:
            self.config['downloadconfig'] = dialog.settings().dump()
            cfg.edit_config('downloadconfig', self.config['downloadconfig'])
        self.start_download(dialog.request)

    def start_download(self, request):
        job = DownloadJob(request, self.song_dir, self.download_dir, self)
        job.progress.connect(self.download_label.setText)
        job.succeeded.connect(self._on_download_succeeded)
        # Bound methods (not lambdas) so Qt queues these onto the GUI thread; sender() is the job.
        job.failed.connect(self._on_download_failed)
        job.aborted.connect(self._on_download_aborted)
        job.finished.connect(self._on_download_finished)
        self.downloads.append(job)
        self.cancel_downloads_action.setEnabled(True)
        job.start()

    def _on_download_succeeded(self, song):
        self.model.add_songs([song])
        self.statusBar().showMessage(f'Downloaded {song.name}', 6000)

    def _on_download_failed(self, message):
        name = self.sender().request.name
        QMessageBox.warning(self, 'Download Failed', f'Could not download {name}:\n\n{message}')

    def _on_download_aborted(self):
        self.statusBar().showMessage(f'Cancelled download of {self.sender().request.name}', 6000)

    def _on_download_finished(self):
        job = self.sender()
        self.downloads.remove(job)
        job.deleteLater()
        self.cancel_downloads_action.setEnabled(bool(self.downloads))
        if not self.downloads:
            self.download_label.setText('')

    def cancel_downloads(self):
        for job in self.downloads:
            job.cancel()

    # =========================================================================================
    # window events
    # =========================================================================================

    def dragEnterEvent(self, event):
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.open_paths(paths)

    def closeEvent(self, event):
        self.player.stop()
        for job in list(self.downloads):
            job.cancel()
            job.wait(5000)
        self.scanner.wait(3000)
        super().closeEvent(event)
