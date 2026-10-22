"""The Shellac main window: playlist table, transport controls, side panels and menus."""
from __future__ import annotations

import os

from PyQt6.QtCore import (
    QByteArray,
    QItemSelection,
    QItemSelectionModel,
    QSize,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
)
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSlider,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import config as cfg
from ..core import playlist_io
from ..core.filter import Filter
from ..core.history import History
from ..core.ordering import LoopMode, ShuffleCycle, moved_to_edge, pick_next, shifted
from ..core.session import Session
from ..core.song import AUDIO_EXTENSIONS, is_audio_file, read_cover, song_from_file
from ..core.timefmt import format_time
from ..core.upnext import UpNext
from ..playback.player import MAX_VOLUME, AudioPlayer
from ..resources import asset
from ..system.mediakeys import GlobalMediaKeys
from .dialogs.about_dialog import AboutDialog
from .dialogs.filter_dialog import FilterDialog
from .dialogs.settings_dialog import SettingsDialog
from .dialogs.song_dialog import SongDialog
from .playlist_model import ALBUM, ARTIST, LENGTH, NAME, TAGS, WEIGHT, FilterProxy, PlaylistModel
from .scanner import Scanner
from .widgets.download_panel import DownloadPanel
from .widgets.marquee import MarqueeLabel
from .widgets.playlist_view import PlaylistView
from .widgets.queue_panel import QueuePanel
from .widgets.tag_browser import TagBrowser

PLAYLIST_FILTER = 'Shellac Playlist (*.slp)'
AUDIO_FILTER = f"Audio files ({' '.join(f'*.{e}' for e in AUDIO_EXTENSIONS)})"
COVER_SIZE = 44


def _keys(*names):
    return [QKeySequence(n) if isinstance(n, str) else QKeySequence(n.value) for n in names]


class MainWindow(QMainWindow):
    def __init__(self, config: dict, session_path=None):
        super().__init__()
        self.config = config
        self.song_dir = config['songdir']
        self.download_dir = config['downloaddir']
        self.save_path = config.get('savedir', '')
        self.loop_mode = LoopMode(cfg.loop_mode(config))
        self.session_path = session_path or cfg.session_path()

        self.model = PlaylistModel(self)
        self.proxy = FilterProxy(self.model, self)
        self.player = AudioPlayer(self)
        self.history = History()
        self.queue = UpNext()
        self.shuffle_cycle = ShuffleCycle()
        self.scanner = Scanner(self)
        self.media_keys = GlobalMediaKeys(self)
        self.tray = None
        self.current = None  # the song loaded in the player

        self._icons = {}
        self._dragging_slider = False
        self._syncing_slider = False
        self._shown_second = -1
        self._restoring = False

        self.setWindowTitle('Shellac')
        self.setWindowIcon(self._icon('Shellac.ico'))
        self.setAcceptDrops(True)
        self.resize(1380, 800)
        self._build_ui()
        self._build_docks()
        self._build_actions()
        self._connect_player()
        self._refresh_loop_button()
        self._refresh_volume_icon()
        self._refresh_filter_label()
        self._apply_system_settings()

        # Save the session shortly after anything worth remembering changes.
        self._session_timer = QTimer(self)
        self._session_timer.setSingleShot(True)
        self._session_timer.setInterval(2000)
        self._session_timer.timeout.connect(self.save_session)
        for signal in (self.model.rowsInserted, self.model.rowsRemoved, self.model.modelReset,
                       self.model.layoutChanged, self.model.dataChanged):
            signal.connect(self._schedule_session_save)
        for signal in (self.proxy.rowsInserted, self.proxy.rowsRemoved, self.proxy.modelReset,
                       self.proxy.layoutChanged):
            signal.connect(self._refresh_filter_label)

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
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search names, tags and albums  (Ctrl+K)')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)

        self.table = PlaylistView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.SelectedClicked)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(26)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(NAME, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(60)
        for column, width in ((LENGTH, 100), (TAGS, 190), (ARTIST, 140), (ALBUM, 160), (WEIGHT, 100)):
            self.table.setColumnWidth(column, width)
        # Click a header to sort; a third click returns to playlist order.
        header.setSortIndicatorClearable(True)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        header.sortIndicatorChanged.connect(lambda *_: self._schedule_session_save())
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.songsMoved.connect(self._on_songs_dragged)
        self.table.filesDropped.connect(self._on_files_dropped)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.model.songEdited.connect(self._on_song_edited)

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
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.cover = QLabel()
        self.cover.setFixedSize(COVER_SIZE, COVER_SIZE)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.now_playing = MarqueeLabel('Now Playing: ')
        self._show_cover(None)

        info = QHBoxLayout()
        info.addWidget(self.cover)
        info.addWidget(self.now_playing, 1)
        info.addWidget(self.time_label)

        controls = QHBoxLayout()
        for widget in (self.prev_button, self.play_button, self.next_button, self.loop_button):
            controls.addWidget(widget)
        controls.addSpacing(16)
        controls.addWidget(self.mute_button)
        controls.addWidget(self.volume)
        controls.addWidget(self.volume_label)
        controls.addStretch(1)
        controls.addWidget(self.up_button)
        controls.addWidget(self.down_button)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.search)
        layout.addWidget(self.table, 1)
        layout.addLayout(info)
        layout.addWidget(self.progress)
        layout.addLayout(controls)
        self.setCentralWidget(central)

        self.download_label = QLabel()
        self.filter_label = QLabel()
        self.statusBar().addPermanentWidget(self.download_label)
        self.statusBar().addPermanentWidget(self.filter_label)

    def _build_docks(self):
        self.tag_browser = TagBrowser(self.model)
        self.tag_browser.tagsChanged.connect(self._on_tags_changed)
        self.tags_dock = QDockWidget('Tags', self)
        self.tags_dock.setObjectName('tags_dock')
        self.tags_dock.setWidget(self.tag_browser)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.tags_dock)

        self.queue_panel = QueuePanel(self.queue)
        self.queue_panel.changed.connect(self._on_queue_changed)
        self.queue_panel.playRequested.connect(self.play_song)
        self.queue_dock = QDockWidget('Up Next', self)
        self.queue_dock.setObjectName('queue_dock')
        self.queue_dock.setWidget(self.queue_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.queue_dock)

        self.download_panel = DownloadPanel(cfg.DownloadSettings.parse(self.config.get('downloadconfig')),
                                            lambda: (self.song_dir, self.download_dir))
        self.download_panel.songDownloaded.connect(self._on_song_downloaded)
        self.download_panel.settingsChanged.connect(self._remember_download_settings)
        self.download_panel.busyChanged.connect(self._on_downloads_busy)
        self.download_panel.statusMessage.connect(lambda message: self.statusBar().showMessage(message, 6000))
        self.downloads_dock = QDockWidget('Downloads', self)
        self.downloads_dock.setObjectName('downloads_dock')
        self.downloads_dock.setWidget(self.download_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.downloads_dock)
        self.tabifyDockWidget(self.queue_dock, self.downloads_dock)
        self.queue_dock.raise_()
        self.resizeDocks([self.tags_dock, self.queue_dock], [170, 210], Qt.Orientation.Horizontal)

    def _action(self, menu, text, shortcuts, slot, tip=''):
        action = QAction(text, self)
        if shortcuts:
            action.setShortcuts(_keys(*shortcuts))
        action.setStatusTip(tip)
        action.triggered.connect(slot)
        if menu is not None:
            menu.addAction(action)
        else:
            self.addAction(action)
        return action

    def _build_actions(self):
        bar = self.menuBar()
        media = Qt.Key

        play = bar.addMenu('Play')
        self._action(play, 'Play / Pause', ['Space', media.Key_MediaTogglePlayPause, media.Key_MediaPlay],
                     self.toggle_play)
        self._action(play, 'Next Song', ['Alt+N', ']', media.Key_MediaNext], self.next,
                     'Next song: history, then Up Next, then the loop mode')
        self._action(play, 'Previous Song', ['Alt+B', '[', media.Key_MediaPrevious], self.previous,
                     'Previous song in history')
        self._action(play, 'Stop', [media.Key_MediaStop], self.stop_playback)
        self._action(play, 'Change Loop Mode', ['Alt+L', 'L'], self.cycle_loop_mode)
        self.no_repeat_action = self._action(play, 'Shuffle Without Repeats', [], self._toggle_no_repeat,
                                             'Shuffle plays every song once before repeating any')
        self.no_repeat_action.setCheckable(True)
        self.no_repeat_action.setChecked(cfg.flag(self.config, 'norepeatshuffle'))
        self._action(play, 'Mute / Unmute', ['Alt+M'], self.toggle_mute)
        play.addSeparator()
        self.play_next_action = self._action(play, 'Play Next', ['Ctrl+Return'], self.queue_selected_next,
                                             'Play the selected songs after the current one')
        self.enqueue_action = self._action(play, 'Add to Up Next', ['Alt+Q'], self.queue_selected,
                                           'Add the selected songs to the end of Up Next')
        self._action(play, 'Clear Up Next', [], self.queue_panel.clear)
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
        self.locate_action = self._action(file, 'Locate File…', [], self.locate_selected,
                                          'Point the selected song at a file that was moved or renamed')
        self._action(file, 'Check for Missing Files', [], self.check_missing)
        self._action(file, 'Remove Missing Songs', [], self.remove_missing)
        file.addSeparator()
        self._action(file, 'Download from Internet…', ['Alt+Ctrl+D'], self.show_downloads,
                     'Download audio from bilibili, YouTube and other sites')
        self.cancel_downloads_action = self._action(file, 'Cancel Downloads', [], self.cancel_downloads)
        self.cancel_downloads_action.setEnabled(False)
        file.addSeparator()
        self._action(file, 'Settings…', ['Ctrl+,'], self.settings_dialog)
        self._action(file, 'Exit', ['Ctrl+Q'], self.quit)

        edit = bar.addMenu('Edit')
        self.edit_action = self._action(edit, 'Edit Selected…', ['Alt+E'], self.edit_selected)
        self._action(edit, 'Move Up', ['Shift+Up'], lambda: self.move_selection(-1))
        self._action(edit, 'Move Down', ['Shift+Down'], lambda: self.move_selection(+1))
        self._action(edit, 'Move to Top', ['Alt+Shift+Up'], lambda: self.move_selection(-1, edge=True))
        self._action(edit, 'Move to Bottom', ['Alt+Shift+Down'], lambda: self.move_selection(+1, edge=True))
        edit.addSeparator()
        self._action(edit, 'Search', ['Ctrl+K'], self._focus_search)
        self._action(edit, 'Add/Edit Filter…', ['Ctrl+F'], self.edit_filter)
        self._action(edit, 'Clear Filter', ['Ctrl+Alt+R'], self.clear_filter,
                     'Clear the filter, search and tag selection')

        view = bar.addMenu('View')
        view.addAction(self.tags_dock.toggleViewAction())
        view.addAction(self.queue_dock.toggleViewAction())
        view.addAction(self.downloads_dock.toggleViewAction())
        self._action(view, 'Playlist Order (Clear Sort)', [], self.clear_sort)
        self._action(view, 'Show Playing Song', ['Ctrl+J'], self.reveal_current)

        help_menu = bar.addMenu('Help')
        self._action(help_menu, 'About Shellac', [], lambda: AboutDialog(self).exec())

    def _show_context_menu(self, pos):
        if not self.selected_songs():
            return
        menu = QMenu(self)
        play = menu.addAction('Play')
        play.triggered.connect(self._play_first_selected)
        menu.addAction(self.play_next_action)
        menu.addAction(self.enqueue_action)
        menu.addSeparator()
        menu.addAction(self.edit_action)
        menu.addAction(self.locate_action)
        menu.addSeparator()
        menu.addAction(self.remove_action)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _connect_player(self):
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playingChanged.connect(self._on_playing_changed)
        self.player.ended.connect(self._on_track_ended)
        self.player.errorOccurred.connect(lambda message: self.statusBar().showMessage(message, 10000))
        self.media_keys.playPause.connect(self.toggle_play)
        self.media_keys.next.connect(self.next)
        self.media_keys.previous.connect(self.previous)
        self.media_keys.stop.connect(self.stop_playback)

    # =========================================================================================
    # playback
    # =========================================================================================

    def play_song(self, song, record=True) -> bool:
        """Start a song. Returns False (and plays nothing) if its file is missing."""
        if song is None:
            self.stop_playback()
            return False
        if song.check_missing():
            self.model.song_changed(song)
            self.statusBar().showMessage(f'File not found: {song.path}  (File › Locate File… to fix)', 10000)
            return False
        self.current = song
        if record:
            self.history.push(song)
        self.shuffle_cycle.mark_played(song)
        self.model.set_playing(song)
        self.player.play_file(song.path)
        self._show_now_playing()
        self._schedule_session_save()
        return True

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
        self._show_cover(self.current)
        if self.tray is not None:
            self.tray.setToolTip(f'Shellac — {name}' if name else 'Shellac')

    def _show_cover(self, song):
        data = read_cover(song.path) if song is not None else None
        pixmap = QPixmap()
        if not data or not pixmap.loadFromData(data):
            pixmap = QPixmap(asset('Shellac.png'))
        self.cover.setPixmap(pixmap.scaled(COVER_SIZE, COVER_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        self.cover.setToolTip((song.album or '') if song is not None else '')

    def toggle_play(self):
        if self.player.has_media:
            self.player.toggle()
        else:
            self._play_first_selected()

    def _play_first_selected(self):
        songs = self.selected_songs() or self.proxy.visible_songs()
        if songs:
            self.play_song(songs[0])

    def _shuffle(self):
        return self.shuffle_cycle if self.no_repeat_action.isChecked() else None

    def _advance(self, manual):
        """Play what comes next: queued songs first, then whatever the loop mode picks.

        Missing files are skipped (reported in the status bar) instead of stopping playback.
        """
        visible = self.proxy.visible_songs()
        for _ in range(len(visible) + len(self.queue) + 1):
            queued = self.queue.pop(lambda s: s in self.model.playlist)
            self.queue_panel.refresh()
            if queued is not None:
                song, record = queued, True
            else:
                song = pick_next(self.loop_mode, visible, self.current, manual=manual, cycle=self._shuffle())
                if song is None:
                    self.stop_playback()
                    return
                record = song is not self.current
            if self.play_song(song, record=record):
                return
            if song is self.current:  # repeat-one on a file that just vanished
                break
            self.current = song  # move past the missing song
        self.stop_playback()

    def next(self):
        song = self.history.forward()
        if song is not None and song in self.model.playlist and self.play_song(song, record=False):
            return
        self._advance(manual=True)

    def previous(self):
        song = self.history.back()
        if song is not None:
            self.play_song(song, record=False)
        elif self.current is not None:
            self.player.seek(0)

    def _on_track_ended(self):
        self._advance(manual=False)

    def _on_playing_changed(self, playing):
        self.play_button.setIcon(self._icon('pause.png' if playing else 'play.png'))
        if self.tray is not None:
            self.tray_play_action.setText('Pause' if playing else 'Play')

    def cycle_loop_mode(self):
        self.loop_mode = self.loop_mode.cycled()
        cfg.edit_config('loopmode', int(self.loop_mode))
        self._refresh_loop_button()
        self.statusBar().showMessage(f'Loop mode: {self.loop_mode.label}', 3000)

    def _refresh_loop_button(self):
        self.loop_button.setIcon(self._icon(f'loop_{self.loop_mode.icon_name}.png'))
        self.loop_button.setToolTip(f'Loop mode: {self.loop_mode.label}  (L)')

    def _toggle_no_repeat(self, checked):
        self.config['norepeatshuffle'] = str(checked)
        cfg.edit_config('norepeatshuffle', checked)
        self.shuffle_cycle.reset()

    # --- up next -----------------------------------------------------------------------------

    def queue_selected_next(self):
        songs = self.selected_songs()
        if songs:
            self.queue.play_next(songs)
            self._on_queue_changed()
            self.statusBar().showMessage(f'Playing next: {len(songs)} song(s)', 3000)

    def queue_selected(self):
        songs = self.selected_songs()
        if songs:
            self.queue.append(songs)
            self._on_queue_changed()
            self.statusBar().showMessage(f'Added {len(songs)} song(s) to Up Next', 3000)

    def _on_queue_changed(self):
        self.queue_panel.refresh()
        self.queue_dock.setWindowTitle(f'Up Next ({len(self.queue)})' if len(self.queue) else 'Up Next')
        self._schedule_session_save()

    # --- volume ------------------------------------------------------------------------------

    def set_volume(self, value):
        self.player.set_volume(value)
        self.volume_label.setText(str(value))
        self._refresh_volume_icon()
        self._schedule_session_save()

    def toggle_mute(self):
        self.player.set_muted(not self.player.muted)
        self._refresh_volume_icon()
        self._schedule_session_save()

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
    # selection, search and sorting
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

    def reveal_current(self):
        if self.current is None:
            return
        if self.proxy.row_of(self.current) < 0:
            self.statusBar().showMessage('The playing song is hidden by the filter or search', 4000)
            return
        self.select_songs([self.current])

    def _on_double_click(self, index):
        song = self.proxy.song_at(index.row())
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            self.edit_song(song)
        else:
            self.play_song(song)

    def _focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _on_search(self, text):
        self.proxy.set_search(text)
        self._refresh_filter_label()
        self._schedule_session_save()

    def _on_tags_changed(self, tags):
        self.proxy.set_required_tags(tags)
        self._refresh_filter_label()
        self._schedule_session_save()

    def clear_sort(self):
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

    def _can_reorder(self) -> bool:
        if self.proxy.is_sorted:
            self.statusBar().showMessage('The table is sorted by a column. Use View › Playlist Order to '
                                         'rearrange songs.', 6000)
            return False
        return True

    def move_selection(self, delta, edge=False):
        songs = self.selected_songs()
        if not songs or not self._can_reorder():
            return
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
            edge = True
        visible = self.proxy.visible_songs()
        order = moved_to_edge(visible, songs, top=delta < 0) if edge else shifted(visible, songs, delta)
        if all(a is b for a, b in zip(order, visible)):
            return
        self.model.reorder(order)
        self.table.scrollTo(self.proxy.index(self.proxy.row_of(songs[0 if delta < 0 else -1]), 0))

    def _on_songs_dragged(self, paths, row):
        if not self._can_reorder():
            return
        moving = [s for s in (self.model.playlist.get(p) for p in paths) if s is not None]
        visible = self.proxy.visible_songs()
        moving_ids = {id(s) for s in moving}
        # Insert before the first song at or after the drop point that isn't itself being moved.
        anchor = next((s for s in visible[row:] if id(s) not in moving_ids), None)
        rest = [s for s in visible if id(s) not in moving_ids]
        at = rest.index(anchor) if anchor is not None else len(rest)
        self.model.reorder(rest[:at] + moving + rest[at:])
        self.select_songs(moving)

    def _on_files_dropped(self, paths, row):
        visible = self.proxy.visible_songs()
        before = visible[row] if row < len(visible) and not self.proxy.is_sorted else None
        self.open_paths(paths, before=before)

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
        song = song_from_file(path, artist_as_tag=cfg.flag(self.config, 'artisttags'))
        dialog = SongDialog(self, 'Add Song', song.name, song.tags, song.weight, song.path)
        if dialog.exec():
            self.model.playlist.update(song, dialog.name, dialog.tags, dialog.weight)
            self.model.add_songs([song])

    def add_folder_dialog(self):
        dialog = self._file_dialog(QFileDialog.FileMode.Directory, 'Add Folder')
        dialog.setOption(QFileDialog.Option.ShowDirsOnly)
        if dialog.exec():
            self.add_paths(dialog.selectedFiles())

    def add_paths(self, items, done_message='Added {added} songs', before=None, on_done=None):
        """Add files, folders or playlist entries in the background, at the end or before `before`."""
        counts = {'added': 0, 'skipped': 0}

        def on_batch(songs):
            row = self.model.row_of(before) if before is not None and before in self.model.playlist else None
            added = len(self.model.add_songs(songs, row))
            counts['added'] += added
            counts['skipped'] += len(songs) - added
            self.statusBar().showMessage(f"Adding songs… {counts['added']}")

        def finished():
            message = done_message.format(**counts)
            if counts['skipped']:
                message += f" ({counts['skipped']} already in the playlist)"
            self.statusBar().showMessage(message, 6000)
            if on_done is not None:
                on_done()

        self.scanner.scan(items, on_batch, finished, artist_as_tag=cfg.flag(self.config, 'artisttags'))

    def open_paths(self, paths, before=None):
        """Open dropped or command-line paths: playlists are loaded, audio files and folders added."""
        media = []
        for path in paths:
            if path.lower().endswith('.slp'):
                self.load_playlist(path)
            elif os.path.isdir(path) or is_audio_file(path):
                media.append(path)
        if media:
            self.add_paths(media, before=before)

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

    def _forget(self, songs):
        """Remove songs from everything that refers to them."""
        if self.current in songs:
            self.stop_playback()
        self.model.remove_songs(songs)
        self.history.remove(songs)
        self.queue.remove(songs)
        self._on_queue_changed()

    def remove_selected(self):
        songs = self.selected_songs()
        if songs:
            self._forget(songs)

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
        self.queue.clear()
        self._on_queue_changed()

    def edit_selected(self):
        songs = self.selected_songs()
        if songs:
            self.edit_song(songs[0])

    def edit_song(self, song):
        dialog = SongDialog(self, 'Edit Song', song.name, song.tags, song.weight, song.path)
        if dialog.exec():
            self.model.update_song(song, dialog.name, dialog.tags, dialog.weight)
            self._on_song_edited(song)

    def _on_song_edited(self, song):
        if song is self.current:
            self._show_now_playing()
        if song in self.queue:
            self.queue_panel.refresh()

    # --- missing files -----------------------------------------------------------------------

    def locate_selected(self):
        songs = self.selected_songs()
        if not songs:
            return
        song = songs[0]
        start = os.path.dirname(song.path) if os.path.isdir(os.path.dirname(song.path)) else self.song_dir
        dialog = self._file_dialog(QFileDialog.FileMode.ExistingFile, f'Locate “{song.name}”', AUDIO_FILTER, start)
        if not dialog.exec():
            return
        try:
            self.model.relocate(song, dialog.selectedFiles()[0])
        except ValueError as e:
            QMessageBox.warning(self, 'Locate File', str(e))
            return
        self.statusBar().showMessage(f'{song.name} now points to {song.path}', 6000)

    def check_missing(self) -> int:
        missing = self.model.refresh_missing()
        self.statusBar().showMessage(f'{missing} missing file(s)' if missing else 'All files found', 6000)
        return missing

    def remove_missing(self):
        self.model.refresh_missing()
        missing = [s for s in self.model.playlist if s.missing]
        if not missing:
            self.statusBar().showMessage('All files found', 4000)
            return
        answer = QMessageBox.question(self, 'Remove Missing Songs',
                                      f'Remove {len(missing)} song(s) whose files can no longer be found?')
        if answer == QMessageBox.StandardButton.Yes:
            self._forget(missing)

    # --- filter ------------------------------------------------------------------------------

    def edit_filter(self):
        dialog = FilterDialog(self, self.proxy.filter, self.model.playlist.all_tags())
        if dialog.exec():
            self.set_filter(dialog.filter)

    def clear_filter(self):
        self.set_filter(Filter())
        self.search.clear()
        self.tag_browser.set_checked([])

    def set_filter(self, new_filter):
        self.proxy.set_filter(new_filter)
        self._refresh_filter_label()
        self._schedule_session_save()

    def _refresh_filter_label(self):
        parts = []
        if not self.proxy.filter.is_empty:
            parts.append(f'Filter: {self.proxy.filter.describe()}')
        if self.proxy.required_tags:
            parts.append('Tags: ' + ', '.join(self.proxy.required_tags))
        if self.proxy.search:
            parts.append(f'Search: “{self.search.text().strip()}”')
        if parts:
            parts.append(f'{self.proxy.rowCount()} of {len(self.model.playlist)} songs')
        self.filter_label.setText('  —  '.join(parts))

    # =========================================================================================
    # downloads
    # =========================================================================================

    def show_downloads(self):
        self.downloads_dock.show()
        self.downloads_dock.raise_()
        self.download_panel.focus_url()

    @property
    def downloads(self):
        """Running download jobs."""
        return self.download_panel.running_jobs

    def start_download(self, request):
        self.download_panel.start(request)

    def _remember_download_settings(self, settings):
        self.config['downloadconfig'] = settings.dump()
        cfg.edit_config('downloadconfig', self.config['downloadconfig'])

    def _on_song_downloaded(self, song):
        self.model.add_songs([song])

    def _on_downloads_busy(self, busy):
        self.cancel_downloads_action.setEnabled(busy)
        running = len(self.downloads)
        self.download_label.setText(f'Downloading {running}…' if running else '')
        self.downloads_dock.setWindowTitle(f'Downloads ({running})' if running else 'Downloads')

    def cancel_downloads(self):
        self.download_panel.cancel_all()

    # =========================================================================================
    # settings and system integration
    # =========================================================================================

    def settings_dialog(self):
        import qt_material
        dialog = SettingsDialog(self, self.config, qt_material.list_themes())
        if not dialog.exec():
            return
        values = dialog.values()
        theme_changed = values['theme'] != self.config.get('theme')
        for key, value in values.items():
            cfg.edit_config(key, value)
        self.config = cfg.load_config()  # re-resolves and creates the folders
        self.song_dir = self.config['songdir']
        self.download_dir = self.config['downloaddir']
        self.no_repeat_action.setChecked(cfg.flag(self.config, 'norepeatshuffle'))
        if theme_changed:
            apply_theme(QApplication.instance(), self.config['theme'])
        self._apply_system_settings()

    def _apply_system_settings(self):
        if cfg.flag(self.config, 'mediakeys'):
            taken = self.media_keys.enable()
            if taken:
                self.statusBar().showMessage(f'Another program is using these media keys: {", ".join(taken)}',
                                             8000)
        else:
            self.media_keys.disable()

        want_tray = cfg.flag(self.config, 'trayicon') and QSystemTrayIcon.isSystemTrayAvailable()
        if want_tray and self.tray is None:
            self._build_tray()
        elif not want_tray and self.tray is not None:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self._icon('Shellac.ico'), self)
        menu = QMenu(self)
        self.tray_play_action = menu.addAction('Pause' if self.player.is_playing else 'Play')
        self.tray_play_action.triggered.connect(self.toggle_play)
        menu.addAction('Next').triggered.connect(self.next)
        menu.addAction('Previous').triggered.connect(self.previous)
        menu.addSeparator()
        menu.addAction('Show Shellac').triggered.connect(self.bring_to_front)
        menu.addAction('Quit').triggered.connect(self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setToolTip(f'Shellac — {self.current.name}' if self.current else 'Shellac')
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible() and not self.isMinimized() and self.isActiveWindow():
                self.showMinimized()
            else:
                self.bring_to_front()

    def bring_to_front(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def on_other_instance(self, paths):
        """A second launch handed us its files."""
        self.bring_to_front()
        if paths:
            self.open_paths(paths)

    def quit(self):
        self.close()

    # =========================================================================================
    # session
    # =========================================================================================

    def _schedule_session_save(self, *_):
        if not self._restoring:
            self._session_timer.start()

    def session_state(self) -> Session:
        header = self.table.horizontalHeader()
        return Session(
            songs=[Session.song_dict(s) for s in self.model.playlist],
            current=self.current.path if self.current else None,
            position=self.player.position if self.current else 0.0,
            volume=self.player.volume,
            muted=self.player.muted,
            filter=self.proxy.filter.to_dict(),
            search=self.search.text(),
            tags=self.tag_browser.checked,
            queue=[s.path for s in self.queue],
            sort_column=self.proxy.sortColumn(),
            sort_order=self.proxy.sortOrder().value,
            window_geometry=bytes(self.saveGeometry().toBase64()).decode('ascii'),
            window_state=bytes(self.saveState().toBase64()).decode('ascii'),
            header_state=bytes(header.saveState().toBase64()).decode('ascii'),
        )

    def save_session(self):
        if self._restoring or not cfg.flag(self.config, 'restoresession'):
            return
        try:
            self.session_state().save(str(self.session_path))
        except OSError as e:
            self.statusBar().showMessage(f'Could not save the session: {e}', 6000)

    def restore_session(self, on_done=None):
        """Reload the last session. The playlist loads in the background; on_done runs when it's in."""
        session = Session.load(str(self.session_path))
        self._restoring = True

        if session.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(session.window_geometry.encode('ascii')))
        if session.window_state:
            self.restoreState(QByteArray.fromBase64(session.window_state.encode('ascii')))
        if session.header_state:
            self.table.horizontalHeader().restoreState(QByteArray.fromBase64(session.header_state.encode('ascii')))
        self.volume.setValue(max(0, min(MAX_VOLUME, session.volume)))
        if session.muted != self.player.muted:
            self.toggle_mute()
        self.proxy.set_filter(Filter.from_dict(session.filter) if session.filter else Filter())
        self.search.setText(session.search)

        def finish():
            playlist = self.model.playlist
            self.tag_browser.refresh()
            self.tag_browser.set_checked([t for t in session.tags if isinstance(t, str)])
            self.queue.append([s for s in (playlist.get(p) for p in session.queue if isinstance(p, str)) if s])
            self._on_queue_changed()
            sort_order = Qt.SortOrder(session.sort_order) if session.sort_order in (0, 1) else Qt.SortOrder.AscendingOrder
            self.table.horizontalHeader().setSortIndicator(session.sort_column, sort_order)
            song = playlist.get(session.current) if isinstance(session.current, str) else None
            if song is not None and not song.check_missing():
                self.current = song
                self.history.push(song)
                self.shuffle_cycle.mark_played(song)
                self.model.set_playing(song)
                self.player.load(song.path, session.position)
                self._show_now_playing()
                self.select_songs([song])
            self._refresh_filter_label()
            self._restoring = False
            if on_done is not None:
                on_done()

        entries = session.entries()
        if entries:
            self.add_paths(entries, 'Restored {added} songs from the last session', on_done=finish)
        else:
            finish()

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
        self._session_timer.stop()
        self.save_session()
        self.player.stop()
        self.download_panel.shutdown()
        self.scanner.wait(3000)
        self.media_keys.disable()
        if self.tray is not None:
            self.tray.hide()
        super().closeEvent(event)


def apply_theme(app, theme):
    import qt_material
    try:
        qt_material.apply_stylesheet(app, theme=theme or 'dark_teal.xml')
    except Exception:  # noqa: BLE001 - an unknown theme name in the config shouldn't stop Shellac
        qt_material.apply_stylesheet(app, theme='dark_teal.xml')
