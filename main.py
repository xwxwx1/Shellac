import os
import re
import sys
from copy import deepcopy, copy
from ctypes import windll

import tinytag
import keyboard
from PyQt6.QtCore import QAbstractTableModel, QRect, Qt, QMetaObject, QModelIndex, QSize, QPoint, QItemSelection, QItemSelectionModel, QUrl, QStandardPaths
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QAudioDevice
from PyQt6.QtGui import QAction, QIcon, QFontMetrics, QPainter, QPixmap, QKeySequence
from PyQt6.QtWidgets import QApplication, QMainWindow, QSlider, QMenu, QFileDialog, QTableView, QPushButton, \
    QWidget, QLabel, QDialog, QTextEdit, QDialogButtonBox, QSpinBox, QCheckBox, QTreeWidget, QTreeWidgetItem, \
    QAbstractItemView, QComboBox
from random import random
import qt_material
from you_get import common as you_get_common
from pyffmpeg import FFmpeg
from threading import Thread
import bisect

audio_formats = ['mp3', 'flac', 'wav', 'ogg', 'wma', 'aac', 'alac']
video_formats = ['mp4', 'flv', 'mkv', 'avi', 'mov', '3gp']

windll.shell32.SetCurrentProcessExplicitAppUserModelID("shellac")


def std_time(x, level=0):
    x = round(x)
    def n(x):
        x = str(x)
        while len(x) < 2:
            x = '0' + x
        return x
    if level == 0:
        return f"{std_time(x // 60, level=1)}:{n(x % 60)}"
    elif level == 1:
        if x >= 60:
            return f"{x//60}:{n(x % 60)}"
        else:
            return n(x)


class VersionPopup(QMainWindow):
    def __init__(self):
        super().__init__()
        self.root = QWidget(self)
        self.layout().addWidget(self.root)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(600, 300)
        qt_material.apply_stylesheet(self, theme="dark_teal.xml")
        self.test = QLabel("TEST", self.root)
        self.logo = QLabel(self.root)
        self.logo_pixmap = QPixmap("assets/shellac_banner.jpg")
        self.logo.setPixmap(self.logo_pixmap)
        self.logo.setGeometry(0, 0, 600, 300)


class RollingLabel(QLabel):
    def __init__(self, parent, flags):
        super().__init__(parent, flags)
        self.timerID = -1
        self.time = 0
        self.shift = -25
        self.setAlignment(Qt.AlignmentFlag.AlignLeft)

    @property
    def text_width(self):
        return QFontMetrics(self.font()).size(Qt.TextFlag.TextSingleLine, self.text()).width()

    @property
    def is_rolling(self):
        return self.timerID >= 0

    def update_rolling_state(self):
        self.shift = -25
        if self.text_width > self.width():
            self.timerID = self.startTimer(20)
        else:
            if self.timerID >= 0:
                self.killTimer(self.timerID)
                self.timerID = -1

    def timerEvent(self, a0):
        self.shift += 1
        if self.text_width - self.width() > self.shift:
            self.shift = -25
        self.repaint()

    def paintEvent(self, a0):
        if not self.is_rolling:
            super().paintEvent(a0)
            return

        if self.shift > self.text_width:
            self.shift = -20

        shift = self.shift if self.shift > 0 else 0

        pen = QPainter(self)
        rc = self.rect()
        text = self.text() + ' ' + self.text()
        rc.setLeft(rc.left() - shift)
        pen.drawText(rc, Qt.AlignmentFlag.AlignLeft, text)

    def setText(self, a0):
        super().setText(a0)
        self.update_rolling_state()

    def resize(self, a0):
        super().resize(a0)
        self.update_rolling_state()


class QSSLoader:
    def __init__(self):
        pass

    @staticmethod
    def read_qss_file(qss_file_name):
        with open(qss_file_name, 'r',  encoding='UTF-8') as file:
            return file.read()


class Playback:
    def __init__(self, path=None):
        self.volume = 66
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.set_volume(self.volume)
        if path:
            self.media_player.setSource(QUrl.fromLocalFile(path))

    def load(self, path):
        self.media_player.setSource(QUrl.fromLocalFile(path))

    def seek(self, pos):
        if not self.is_valid:
            return
        self.media_player.setPosition(pos*1000)

    def play(self):
        self.media_player.play()

    def pause(self):
        self.media_player.pause()

    def resume(self):
        self.media_player.play()

    def stop(self):
        self.media_player.stop()
        self.media_player = QMediaPlayer()
        self.media_player.setAudioOutput(self.audio_output)

    def set_volume(self, v):
        self.volume = v
        # print(v)
        # self.audio_output.setVolume(QAudio.convertVolume(v, QAudio.VolumeScale.LogarithmicVolumeScale, QAudio.VolumeScale.LinearVolumeScale))
        self.audio_output.setVolume(v)

    def refresh_audio_stream(self):
        # print(self.audio_output.device().description())
        self.audio_output.setDevice(QAudioDevice())
        pass

    @property
    def has_ended(self):
        return self.is_valid and self.media_player.position() >= self.media_player.duration()

    @property
    def duration(self):
        return self.media_player.duration() / 1000

    @property
    def curr_pos(self):
        return self.media_player.position() / 1000

    @property
    def is_paused(self):
        return self.media_player.playbackState() == QMediaPlayer.PlaybackState.PausedState

    @property
    def is_playing(self):
        return self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @property
    def is_stopped(self):
        return self.media_player.playbackState() == QMediaPlayer.PlaybackState.StoppedState

    @property
    def is_valid(self):
        return self.media_player.mediaStatus() in [QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia]


class PlaylistModel(QAbstractTableModel):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self._data = [] if data is None else [[i.name, std_time(i.length), ', '.join(i.tags), i.artist, i.weight] for i in data]
        self.headers = ['Name', 'Length', 'Tags', 'Artist', 'Weight']

    def set_playlist(self, playlist):
        self.beginResetModel()
        self._data = [] if playlist is None or not len(playlist) else [
            [i.name, std_time(i.length), ', '.join(i.tags), i.artist, i.weight] for i in playlist]
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._data[index.row()][index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.headers[section]
        return None


class Filter:
    def __init__(self, regex='', tags=(), strict=True):
        self.strict = strict
        self.regex = regex
        self.tags = [list(i) for i in tags]

    @property
    def tags_enabled(self):
        return len(self.tags) != 0

    @property
    def regex_enabled(self):
        return self.regex != ''

    def check(self, song):
        regex_result = re.search(self.regex, song.name) is not None if self.regex_enabled else True
        if self.tags_enabled:
            tags_result = False
            for i in self.tags:
                check = True
                for j in i:
                    if j[0] not in song.tags and j[1] or \
                        j[0] in song.tags and not j[1]:
                        check = False
                if check:
                    tags_result = True
        else:
            tags_result = True

        if not self.regex_enabled and not self.tags_enabled:
            return True
        if not self.regex_enabled:
            return tags_result
        if not self.tags_enabled:
            return regex_result

        if self.strict:
            return regex_result and tags_result
        else:
            return regex_result or tags_result


class FilterDialog(QDialog):
    def __init__(self, parent=None, filter=None):
        super().__init__(parent)
        self.initUI()
        self.row_height = 25
        if filter is not None:
            self.strict_checkbox.setChecked(filter.strict)
            self.regex_input.setText(filter.regex)
            filter = filter.tags
            for i in range(len(filter)):
                self.add_rule()
            for i, rule in enumerate(filter):
                self.tags_frame.setCurrentItem(self.tags_frame.topLevelItem(i))
                for j in range(len(rule)-1):
                    self.add_tag()
                for j, tag in enumerate(rule):
                    self.tags_frame.topLevelItem(i).child(j).setText(0, ('' if tag[1] else 'NOT ')+'"'+tag[0]+'"')
        self.update_text()

    def initUI(self):
        self.resize(500, 720)
        self.root = QWidget(self)

        self.regex_label = QLabel("Regular Expression", self.root)
        self.regex_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.regex_label.setGeometry(10, 10, 480, 20)

        self.regex_input = QTextEdit(self.root)
        self.regex_input.setGeometry(10, 30, 480, 40)
        self.regex_input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.strict_checkbox = QCheckBox("Strict mode: regex AND tags", self.root)
        self.strict_checkbox.setGeometry(10, 80, 480, 20)

        self.tags_frame = QTreeWidget(self.root)
        self.tags_frame.setGeometry(0, 170, 500, 400)
        self.tags_frame.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tags_frame.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tags_frame.setHeaderLabel("tags")
        self.add_rule_button = QPushButton("Add Rule", self.root)
        self.add_rule_button.setGeometry(10, 130, 100, 30)
        self.add_rule_button.clicked.connect(self.add_rule)
        self.add_rule_button.setShortcut('Ctrl+R')
        self.add_tag_button = QPushButton("Add Tag", self.root)
        self.add_tag_button.setGeometry(120, 130, 100, 30)
        self.add_tag_button.clicked.connect(self.add_tag)
        self.add_tag_button.setShortcut('Ctrl+T')
        self.delete_button = QPushButton("Delete", self.root)
        self.delete_button.setGeometry(230, 130, 100, 30)
        self.delete_button.clicked.connect(self.delete)
        self.delete_button.setShortcut('Ctrl+Delete')

        self.tag_edit = QTextEdit(self.root)
        self.tag_edit.setGeometry(10, 580, 380, 40)
        self.tag_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.set_tag_button = QPushButton("Set Tag", self.root)
        self.set_tag_button.setGeometry(400, 580, 90, 40)
        self.set_tag_button.clicked.connect(self.set_tag)
        self.set_tag_button.setShortcut('Ctrl+E')
        self.negated_checkbox = QCheckBox("Negate", self.root)
        self.negated_checkbox.setGeometry(10, 620, 100, 25)
        _button1 = QPushButton(self.root)
        _button1.setMaximumWidth(0)
        _button1.clicked.connect(self.down)
        _button1.setShortcut('Ctrl+Down')
        _button2 = QPushButton(self.root)
        _button2.setMaximumWidth(0)
        _button2.clicked.connect(self.up)
        _button2.setShortcut('Ctrl+Up')
        _button3 = QPushButton(self.root)
        _button3.setMaximumWidth(0)
        _button3.clicked.connect(self.negate)
        _button3.setShortcut('Ctrl+N')

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok, self.root)
        self.buttons.setGeometry(0, 660, 160, 60)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

    def down(self):
        self.tags_frame.setCurrentItem(self.tags_frame.itemBelow(self.tags_frame.currentItem()))

    def up(self):
        self.tags_frame.setCurrentItem(self.tags_frame.itemAbove(self.tags_frame.currentItem()))

    def negate(self):
        self.negated_checkbox.setChecked(not self.negated_checkbox.isChecked())

    def delete(self):
        curr = self.tags_frame.currentItem()
        if curr is None:
            return 1
        if curr.parent() is None:
            self.tags_frame.takeTopLevelItem(self.tags_frame.indexOfTopLevelItem(curr))
        else:
            parent = curr.parent()
            parent.takeChild(parent.indexOfChild(curr))
            if parent.childCount() == 0:
                self.tags_frame.takeTopLevelItem(self.tags_frame.indexOfTopLevelItem(parent))
        self.update_text()

    def update_text(self):
        final_text = []
        for a in range(self.tags_frame.topLevelItemCount()):
            i = self.tags_frame.topLevelItem(a)
            suite_text = []
            for b in range(i.childCount()):
                j = i.child(b)
                if j.text(0):
                    suite_text.append(j.text(0))
            suite_text = ' AND '.join(suite_text)
            i.setText(0, suite_text)
            if suite_text:
                final_text.append(suite_text)
        final_text = ' OR '.join(final_text)
        self.tags_frame.setHeaderLabel(final_text)

    def set_tag(self):
        curr = self.tags_frame.currentItem()
        if curr is None:
            return
        if curr.parent() is None:
            curr = curr.child(0)
        curr.setText(0, ("NOT " if self.negated_checkbox.isChecked() else "") + f'"{self.tag_edit.toPlainText()}"')
        self.update_text()

    def add_tag(self):
        i = self.tags_frame.currentItem()
        if i is None:
            return
        if i.parent() is None:
            i = i.child(0)
        item = QTreeWidgetItem(i.parent())
        item.setSizeHint(0, QSize(self.width(), self.row_height))
        self.tags_frame.setCurrentItem(item)

    def add_rule(self):
        item = QTreeWidgetItem()
        enter = QTreeWidgetItem(item)
        item.setSizeHint(0, QSize(self.width(), self.row_height))
        enter.setSizeHint(0, QSize(self.width(), self.row_height))
        self.tags_frame.addTopLevelItem(item)
        item.setExpanded(True)
        self.tags_frame.setCurrentItem(enter)

    @property
    def filter(self):
        f = []
        for a in range(self.tags_frame.topLevelItemCount()):
            f.append([])
            i = self.tags_frame.topLevelItem(a)
            for b in range(i.childCount()):
                j = i.child(b)
                if j.text(0):
                    negated = len(j.text(0)) > 4 and j.text(0)[:4] == 'NOT '
                    f[a].append(('"'.join(j.text(0).split('"')[1:-1]), not negated))
        return Filter(self.regex_input.toPlainText(), f, self.strict_checkbox.isChecked())

class Song:
    def __init__(self, path, name=None, weight=1, tags=None):
        self.path = path.replace('\\', '/')
        if path[0:2] == './':
            self.path = os.getcwd().replace('\\', '/') + path[1:]
        self.name = name
        self.weight = weight
        tag = tinytag.TinyTag.get(self.path)
        if self.name is None:
            self.name = tag.title if tag.title else ''.join(self.path.split('/')[-1].split('.')[:-1])
        self.tags = [] if tags is None else tags
        self.length = tag.duration

    @property
    def artist(self):
        if len(self.tags) == 0:
            return '/'
        return self.tags[0]

    def __str__(self):
        return f'{self.name}, {self.tags}, {self.weight}'


class Playlist:
    def __init__(self, lists=()):
        self.list = list(lists)
        self.filtered_list = self.list[:]
        self.length = len(self.list)
        self.tags = []
        self.tag_catalog = {}
        self.filter = Filter()
        self.selected = []

    def select(self, song):
        if song in self.filtered_list and song not in self.selected:
            self.selected.append(song)

    def clear_select(self):
        self.selected.clear()

    def reselect(self, song):
        self.clear_select()
        self.select(song)

    def toggle_select(self, song):
        if song in self.selected:
            self.selected.remove(song)
        elif song in self.filtered_list:
            self.selected.append(song)

    def is_empty_selection(self):
        return len(self.selected) == 0

    def count_selected(self):
        return len(self.selected)

    def set_filter(self, filter):
        self.filter = filter
        self.filtered_list = []
        for song in self.list:
            if self.filter.check(song):
                self.filtered_list.append(song)
        for song in self.selected:
            if not self.filter.check(song):
                self.selected.remove(song)

    def add(self, song, position=None):
        if self.get_index(song.name) is not None:
            return
        if position is None:
            self.list.append(song)
        else:
            self.list.insert(position, song)
        if self.filter.check(song):
            if position is None:
                self.filtered_list.append(song)
            else:
                self.filtered_list.insert(self.get_filtered_position(position), song)
        for i in song.tags:
            if i not in self.tags:
                self.tags.append(i)
                self.tag_catalog[i] = set()
            self.tag_catalog[i].add(song)
        self.length += 1

    def get_filtered_position(self, pos):
        if pos >= len(self.list):
            return len(self.filtered_list)
        filtered_i = 0
        for i in range(pos):
            if self.list[i] in self.filtered_list:
                filtered_i += 1
        return filtered_i

    def get_unfiltered_position(self, pos):
        if pos > len(self.filtered_list):
            pos = len(self.filtered_list) - 1
        return self.get_index(self.filtered_list[pos])

    def __len__(self):
        return len(self.filtered_list)

    def __getitem__(self, item):
        if isinstance(item, Song):
            return item
        if isinstance(item, str):
            return self.list[self.get_index(item)]
        return self.filtered_list[item]

    def __iter__(self):
        return self.filtered_list.__iter__()

    def delete(self, indicator):
        if isinstance(indicator, int):
            index = int(indicator)
        elif isinstance(indicator, Song):
            index = self.get_index(indicator)
        elif isinstance(indicator, str):
            index = None
            for i, song in enumerate(self.list):
                if song.name == str(indicator):
                    index = i
                    break
            if index is None: return
        elif isinstance(indicator, (tuple, list, set)):
            for i in list(indicator):
                self.delete(i)
            return
        else:
            return
        s = self.list.pop(index)
        if s in self.filtered_list:
            self.filtered_list.remove(s)
        if s in self.selected:
            self.selected.remove(s)
        for i in s.tags:
            if i in self.tag_catalog and s in self.tag_catalog[i]:
                self.tag_catalog[i].remove(s)
            if i in self.tags and len(self.tag_catalog[i]) == 0:
                self.tags.remove(i)

    def get_index(self, id):
        for i, j in enumerate(self.list):
            if isinstance(id, str) and j.name == id or \
               isinstance(id, Song) and id is j:
                return i
        return None

    def get_song(self, id):
        try:
            id = round(float(id))
        except ValueError:
            pass
        if isinstance(id, str):
            return self.list[self.get_index(id)]
        else:
            return self.list[int(id)]

    def random(self, last=None):
        """
        takes in the last played song as the index to be excluded or none, and returns the index of the song to be played

        :type last: int
        """
        total = 0
        for song in self.filtered_list[:last]+self.filtered_list[last+1:] if last is not None else self.filtered_list:
            total += song.weight
        select = random() * total

        for index, song in enumerate(self.filtered_list):
            if select - song.weight > 0:
                select -= song.weight
            else:
                return index, song

    def change_position(self, song, to):
        if song not in self.list:
            return
        i = self.list.index(song)
        self.list[i] = "change_position placeholder"
        self.list.insert(self.get_unfiltered_position(to), song)
        self.list.remove("change_position placeholder")
        if song in self.filtered_list:
            f_i = self.filtered_list.index(song)
            self.filtered_list[f_i] = "change_position placeholder"
            self.filtered_list.insert(to, song)
            self.filtered_list.remove("change_position placeholder")

    def move_up(self, index, k, to_top=True, is_filtered=True):
        if is_filtered:
            index = self.get_unfiltered_position(index)
        song = self.list[index]
        if to_top:
            self.change_position(song, 0)
        else:
            position = index - min(index, k)
            self.change_position(song, position)

    def move_down(self, index, k, to_bottom=True, is_filtered=True):
        if is_filtered:
            index = self.get_unfiltered_position(index)
        song = self.list[index]
        if to_bottom:
            self.change_position(song, len(self.list))
        else:
            position = index + min(len(self.list)-index, k) + 1
            self.change_position(song, position)

    def update(self, id, name=None, tags=None, weight=None):
        song = self[id]
        name = song.name if name is None else name
        tags = song.tags if tags is None else tags
        weight = song.weight if weight is None else weight
        index = self.get_index(song)
        self.delete(song)
        song.name = name
        song.tags = tags
        song.weight = weight
        self.add(song, index)


class AddSongDialog(QDialog):
    def __init__(self, parent, filepath):
        super().__init__(parent)
        self.setupUi()
        self.name_input.setText('.'.join(filepath.replace('\\', '/').split('/')[-1].split('.')[:-1]))
        self.weight_input.setValue(1)

    def setupUi(self):
        self.setObjectName("Dialog")
        self.resize(400, 300)
        self.buttonBox = QDialogButtonBox(self)
        self.buttonBox.setGeometry(QRect(280, 20, 100, 241))
        self.buttonBox.setOrientation(Qt.Orientation.Vertical)
        self.buttonBox.setStandardButtons(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.label = QLabel(self)
        self.label.setGeometry(QRect(10, 10, 55, 16))
        self.label.setObjectName("label")
        self.name_input = QTextEdit(self)
        self.name_input.setGeometry(QRect(10, 30, 221, 80))
        self.name_input.setObjectName("textEdit")
        self.tags_input = QTextEdit(self)
        self.tags_input.setGeometry(QRect(10, 140, 221, 80))
        self.tags_input.setObjectName("textEdit_2")
        self.label_2 = QLabel(self)
        self.label_2.setGeometry(QRect(10, 120, 271, 16))
        self.label_2.setObjectName("label_2")
        self.label_3 = QLabel(self)
        self.label_3.setGeometry(QRect(10, 230, 55, 16))
        self.label_3.setObjectName("label_3")
        self.weight_input = QSpinBox(self)
        self.weight_input.setGeometry(QRect(180, 230, 60, 22))
        self.weight_input.setMinimum(1)
        self.weight_input.setObjectName("spinBox")

        self.label.setText("Name:")
        self.label_2.setText("Tags (separated by \',\'):")
        self.label_3.setText("Weight:")
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        QMetaObject.connectSlotsByName(self)


class Player(QMainWindow):
    def __init__(self):
        super().__init__()
        self.playing = None
        self.loop_mode = 0
        self.playlist = Playlist()
        self.hist = []
        self.hist_pointer = -1
        self.volume = 1
        self.playlist_literal = ''
        self.player = Playback()
        self.is_dragging = False
        self.is_loading = False
        self.is_downloading = False
        self.download_thread = []
        self.downloading_count = 0
        self.download_data = {}
        self.save_path = ''
        self.startTimer(1)
        self.drag = None
        self.is_muted = False
        self.next_to_play = None
        self.ffmpeg = FFmpeg()
        self.device_reset_cooldown = 0
        self.icon = QIcon('assets/Shellac.ico')
        with open("config.txt") as config: # TODO more comprehensive loading and editing of config?
            config = {j[0]: ':'.join(j[1:]) for j in [i[:-1].split(':') for i in config.readlines()]} # stupidass python which reads each line into dict form, key and value separated with the first ":" in a line
            self.song_dir = config['songdir']
            self.download_dir = config['downloaddir']
            self.download_config = {j[0]: ':'.join(j[1:]) for j in [i.split(':') for i in config['downloadconfig'].split(';')]}
            self.file_folders = ['',
                                 QStandardPaths.standardLocations(QStandardPaths.StandardLocation.DesktopLocation)[0],
                                 QStandardPaths.standardLocations(QStandardPaths.StandardLocation.MusicLocation)[0],
                                 self.song_dir
            ]
            self.file_folders.extend(config['folders'].split(';'))
            self.loop_mode = int(config['loopmode'])
            self.save_path = config['savedir']
        self.initUI()


    def next(self):
        if self.hist_pointer != -1:
            assert self.hist_pointer < 0
            self.play_song(self.hist[self.hist_pointer + 1], 0)
            self.hist_pointer += 1
            return
        if len(self.playlist) == 0 or not self.playing or self.playing not in self.playlist:
            return
        if self.loop_mode == 0:
            self.play(self.playing, 0)
        elif self.loop_mode == 1:
            self.play(0 if self.playing is self.playlist[-1] else self.playlist.get_index(self.playing) + 1)
        elif self.loop_mode == 2:
            self.play(self.playlist.random(self.playlist.get_index(self.playing))[0])
        elif self.loop_mode == 3:
            self.song_view.setText('Now Playing: ')
            self.time_view.setText('--:--')
            self.playing = None
            self.player.clear()
            return

    def play(self, index, startpos=0):
        if isinstance(index, QModelIndex):
            self.list.setCurrentIndex(index)
            index = index.row()
        self.playing = self.playlist[index]
        self.hist.append(self.playing)
        self.play_song(index, startpos)

    def play_song(self, song, pos=0):
        self.song_view.setText('Now Playing: ' + self.playlist[song].name)
        self.is_loading = True
        self.player.load(self.playlist[song].path)
        self.player.play()
        self.player.seek(pos)
        self.player.set_volume(2/3 * (0 if self.is_muted else self.volume))
        self.is_loading = False


    def last(self):
        if -self.hist_pointer < len(self.hist):
            self.playing = self.hist[self.hist_pointer - 1]
            self.play_song(self.playing, 0)
            self.hist_pointer -= 1
        else:
            self.song_view.setText('Now Playing: ')
            self.time_view.setText('--:--')
            self.playing = None
            self.player.clear()


    def change_loop(self):
        # 0: repeat; 1: loop; 2: shuffle play; 3: stop playing
        self.loop_mode += 1
        self.loop_mode %= 4
        self.edit_config('loopmode', self.loop_mode)
        self.refresh_loop_icon()

    def refresh_loop_icon(self):
        self.loop_button.setIcon(QIcon(f"assets/loop_{['repeat', 'list', 'shuffle', 'none'][self.loop_mode]}.png"))

    def save(self):
        if not self.window().isActiveWindow():
            return
        file, _ = self.file_dialog.getSaveFileName(self, directory=self.save_path, filter="Shellac Playlist Files(*.slp)", options=QFileDialog.Option.DontUseNativeDialog)
        self.save_path = file
        self.edit_config('savedir', file)
        if not file:
            return
        with open(file, mode='w+') as f:
            for i in self.playlist:
                f.write(
                    f"path::{i.path};name::{i.name};tags::{', '.join(i.tags)};weight::{i.weight}\n"
                )

    def load(self):
        if not self.window().isActiveWindow():
            return
        file, _ = self.file_dialog.getOpenFileName(self, directory=self.save_path, filter="Shellac Playlist files(*.slp)", options=QFileDialog.Option.DontUseNativeDialog)
        if not file:
            return
        self.load_playlist(file)
        self.save_path = file
        self.edit_config('savedir', file)

    def load_playlist(self, file):
        try:
            with open(file) as f:
                for i in f.readlines():
                    data = {j.split('::')[0]: j.split('::')[1] for j in i[:-1].split(';')}
                    self.add(data['path'], data['name'], int(data['weight']), data['tags'].split(', '))
        except FileNotFoundError:
            return

    def download(self):
        dialog = QDialog()
        dialog.resize(500, 780)
        x = 10
        y = 10
        w = 480
        url_l = QLabel('URL of video or audio:', dialog)
        url_l.setGeometry(x, y, w, 20)
        y += 20
        url_t = QTextEdit(self.download_config['url'], dialog)
        url_t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        url_t.setGeometry(x, y, w, 40)
        y += 50

        name_l = QLabel('Name of song (Must be given):', dialog)
        name_l.setGeometry(x, y, w, 20)
        y += 20
        name_t = QTextEdit(self.download_config['name'], dialog)
        name_t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        name_t.setGeometry(x, y, w, 40)
        y += 50

        start_l = QLabel('Starting Position (0:00 if left blank):', dialog)
        start_l.setGeometry(x, y, w, 20)
        y += 20
        start_t = QTextEdit(self.download_config['start'], dialog)
        start_t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        start_t.setGeometry(x, y, w, 40)
        y += 50

        end_l = QLabel('Ending Position (end of file if left blank):', dialog)
        end_l.setGeometry(x, y, w, 20)
        y += 20
        end_t = QTextEdit(self.download_config['end'], dialog)
        end_t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        end_t.setGeometry(x, y, w, 40)
        y += 50

        tags_l = QLabel('Tags:', dialog)
        tags_l.setGeometry(x, y, w, 20)
        y += 20
        tags_t = QTextEdit(self.download_config['tags'], dialog)
        tags_t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tags_t.setGeometry(x, y, w, 40)
        y += 50

        yargs_l = QLabel('Other you-get arguments:', dialog)
        yargs_l.setGeometry(x, y, w, 20)
        y += 20
        yargs_t = QTextEdit(self.download_config['yargs'], dialog)
        yargs_t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        yargs_t.setGeometry(x, y, w, 40)
        y += 50

        fiargs_l = QLabel('Other ffmpeg arguments (input):', dialog)
        fiargs_l.setGeometry(x, y, w, 20)
        y += 20
        fiargs_t = QTextEdit(self.download_config['fiargs'], dialog)
        fiargs_t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fiargs_t.setGeometry(x, y, w, 40)
        y += 50

        foargs_l = QLabel('Other ffmpeg arguments (output):', dialog)
        foargs_l.setGeometry(x, y, w, 20)
        y += 20
        foargs_t = QTextEdit(self.download_config['foargs'], dialog)
        foargs_t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        foargs_t.setGeometry(x, y, w, 40)
        y += 50

        filetype_l = QLabel('Filetype:', dialog)
        filetype_l.setGeometry(x, y, w, 20)
        y += 20
        filetype_t = QComboBox(dialog)
        filetype_t.addItems(audio_formats)
        filetype_t.setCurrentIndex(audio_formats.index(self.download_config['ftype']))
        filetype_t.setGeometry(x, y, w, 40)
        y += 50

        weight_l = QLabel('Weight:', dialog)
        weight_l.setGeometry(x, y, w, 20)
        y += 20
        weight_t = QSpinBox(dialog)
        weight_t.setValue(int(self.download_config['weight']))
        weight_t.setGeometry(x, y, w, 40)
        y += 50

        save_box = QCheckBox("Save config", dialog)
        save_box.setGeometry(x, y, 100, 30)
        save_box.setChecked(True)
        save_box.setCheckable(True)

        delete_box = QCheckBox("Delete video file", dialog)
        delete_box.setGeometry(x+125, y, 150, 30)
        delete_box.setChecked(self.download_config['deletevid'] == 'True')
        delete_box.setCheckable(True)

        dialog.buttons = QDialogButtonBox(dialog)
        dialog.buttons.setOrientation(Qt.Orientation.Horizontal)
        dialog.buttons.setGeometry(x+300, y, w-300, 790-y)
        dialog.buttons.setStandardButtons(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        dialog.buttons.accepted.connect(dialog.accept)
        dialog.buttons.rejected.connect(dialog.reject)
        dialog.setWindowTitle("Download")
        dialog.exec()

        if dialog.result() == 0:
            return

        name = name_t.toPlainText()
        for char in [':', '*', '/', '\\', '<', '>', '|', '"', '?']:
            name = name.replace(char, '')

        self.download_data = {'url': url_t.toPlainText(),
                              'start': start_t.toPlainText(),
                              'end': end_t.toPlainText(),
                              'name': name,
                              'tags': tags_t.toPlainText(),
                              'ftype': filetype_t.currentText(),
                              'yargs': yargs_t.toPlainText().strip(),
                              'fiargs': fiargs_t.toPlainText().strip(),
                              'foargs': foargs_t.toPlainText(),
                              'weight': weight_t.value(),
                              'deletevid': str(delete_box.isChecked())}
        if save_box.isChecked():
            self.download_config = self.download_data
            self.save_download_config()

        try:
            assert int(start_t.toPlainText().split(':')[0])
            assert int(start_t.toPlainText().split(':')[1])
            assert len(start_t.toPlainText().split(':')) == 2
        except:
            print(f'ERROR: Invalid starting time received: {start_t.toPlainText()}')
            return

        try:
            int(end_t.toPlainText().split(':')[0])
            int(end_t.toPlainText().split(':')[1])
            assert len(end_t.toPlainText().split(':')) == 2
        except:
            print(f'ERROR: Invalid ending time received: {end_t.toPlainText()}')
            return
        try:
            assert len(name) >= 1
        except:
            print(f'ERROR: No name entered')

        for i in self.download_thread:
            if not i.is_alive():
                self.download_thread.remove(i)
        self.download_thread.append(Thread(target=self.execute_download))
        self.download_thread[-1].start()




    def save_download_config(self):
        self.edit_config('downloadconfig', ';'.join([f'{i}:{self.download_config[i]}' for i in self.download_config.keys()]))

    def edit_config(self, key, value):
        with open('config.txt', mode='r') as f:
            data = f.readlines()
        found = False
        for i, line in enumerate(data):
            if len(line) > 0 and line[:len(key)] == key:
                data[i] = f'{key}:{value}\n'
                found = True
        if not found:
            data.append(f'{key}:{value}\n')
        with open('config.txt', mode='w+') as f:
            f.writelines(data)

    def execute_download(self):
        url = self.download_data['url']
        name = self.download_data['name']
        start = self.download_data['start']
        end = self.download_data['end']
        yargs = self.download_data['yargs']
        fiargs = self.download_data['fiargs']
        foargs = self.download_data['foargs']
        tags = self.download_data['tags']
        ftype = self.download_data['ftype']
        weight = self.download_data['weight'] # Forgor how to do parameters in threading

        def parse_args(s): # turn '-f "foo \"bar" -b' into ['-f', 'foo "bar', '-b']
            quotes = []
            for pos, char in enumerate(s):
                if char == '"' and (pos == 0 or s[pos-1] == '\\'):
                    quotes.append(pos)
            if len(quotes) % 2 != 0:
                print('Some arguments entered had incorrent quotation marks!')
                return []
            quotes = [(quotes[2*i], quotes[2*i+1]) for i in range(len(quotes)//2)]

            def check_in_quotes(quotes, pos):
                for pair in quotes:
                    if pair[0] < pos < pair[1]:
                        return True
                return False

            args = []
            lastpos = 0
            for pos, char in enumerate(s):
                if char == ' ' and not check_in_quotes(quotes, pos):
                    args.append(s[lastpos:pos])
                    lastpos = pos+1
            if lastpos < len(s) - 1:
                args.append(s[lastpos:])

            for pos, arg in enumerate(args):
                if arg[0] == arg[-1] == ' ':
                    args[pos] = arg[1:-1]

            return args


        files_before = os.listdir(self.download_dir)
        if len(yargs) != 0:
            yargs = [url] + parse_args(yargs)
        else:
            yargs = [url]
        yargs.extend(['-o', self.download_dir, '-O', name])
        you_get_common.main(yargs=yargs)
        files = os.listdir(self.download_dir)
        for file in files_before:
            if '.'.join(file.split('.')[:-1]) == name and file.split('.')[-1] in video_formats.extend(audio_formats):
                continue
            try:
                files.remove(file)
            except ValueError:
                pass
        downloaded_video = ''
        for file in files:
            if '.'.join(file.split('.')[:-1]) == name and file.split('.')[-1] in video_formats.extend(audio_formats):
                downloaded_video = self.download_dir + file
                break
        if downloaded_video == '':
            print(f"Download failed on URL: {url}")
            return
        if start:
            fiargs += ' -ss ' + start
        if end:
            fiargs += ' -to ' + end
        self.ffmpeg.options(f'{fiargs} -i "{downloaded_video}" {foargs} "{self.song_dir}{name}.{ftype}"')
        converted_song = self.song_dir + name + '.' + ftype
        self.add(converted_song, name, weight, tags.split(','))
        if self.download_config['deletevid'] == 'True':
            os.remove(downloaded_video)


    def add_song(self, path=None):
        if not self.window().isActiveWindow():
            return
        if isinstance(path, str):
            file = path
        else:
            file, _ = self.file_dialog.getOpenFileName(self, filter=f"Audio Files({';'.join([f'*.{i}' for i in audio_formats])})", directory=self.song_dir, options=QFileDialog.Option.DontUseNativeDialog)
            if not file:
                return
        # orig_path = file
        # file = self.song_dir + file.replace('\\', '/').split('/')[-1]
        # try:
        #     shutil.copy(orig_path, self.song_dir)
        # except shutil.SameFileError:
        #     pass
        dialog = AddSongDialog(self, file)
        dialog.exec()
        if dialog.result() == 1:
            self.add(file, dialog.name_input.toPlainText(), int(dialog.weight_input.text()), dialog.tags_input.toPlainText().split(', '))

    def add(self, path, name=None, weight=1, tags=()):
        song = Song(path, name, weight, list(tags))
        self.playlist.add(song)
        self.model.set_playlist(self.playlist)


    def add_folder(self):
        if not self.window().isActiveWindow():
            return
        filepath = self.file_dialog.getExistingDirectory(options=QFileDialog.Option.DontUseNativeDialog)
        self.load_folder(filepath)

    def load_folder(self, filepath):
        for root, dir, files in os.walk(filepath):
            for file in files:
                file = os.path.join(root, file)
                if file.split('.')[-1] in audio_formats:
                    self.add(file)

    def remove_song(self):
        if not self.window().isActiveWindow():
            return
        if self.playlist.is_empty_selection():
            return
        if self.playing in self.playlist.selected:
            self.player.stop()
        self.playlist.delete(self.playlist.selected)
        self.model.set_playlist(self.playlist)

    def deselect(self):
        if not self.window().isActiveWindow():
            return
        self.playlist.clear_select()
        self.refresh_selection_highlight()

    def refresh_selection_highlight(self):
        self.list.clearSelection()
        for index, song in enumerate(self.playlist):
            if song in self.playlist.selected:
                self.list.selectionModel().select(
                    QItemSelection(self.model.index(index, 0, QModelIndex()), self.model.index(index, self.model.columnCount()-1, QModelIndex())),
                    QItemSelectionModel.SelectionFlag.Select)

    # def handle_keys(self, key_event):
    #


    def initUI(self):
        self.setObjectName("MainWindow")
        self.resize(1920, 1080)
        self.centralwidget = QWidget(self)
        self.centralwidget.setObjectName("centralwidget")
        self.list = QTableView(self.centralwidget)
        self.list.keyboardSearch = lambda x: None
        self.list.setGeometry(QRect(20, 10, 1450, 660))
        self.list.setObjectName("playlist")
        self.list.horizontalHeader().setStretchLastSection(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        button_ypos = 710
        self.pause_button = QPushButton(self.centralwidget)
        self.pause_button.setGeometry(QRect(72, button_ypos, 24, 24))
        self.pause_button.setObjectName("pause_button")
        self.pause_button.setIcon(QIcon("assets/pause.png"))
        self.pause_button.setShortcut("Space")
        self.last_button = QPushButton(self.centralwidget)
        self.last_button.setGeometry(QRect(45, button_ypos, 24, 24))
        self.last_button.setObjectName("last_button")
        self.last_button.setIcon(QIcon("assets/last.png"))
        self.last_button.setShortcut(Qt.Key.Key_BracketLeft)
        self.next_button = QPushButton(self.centralwidget)
        self.next_button.setGeometry(QRect(99, button_ypos, 24, 24))
        self.next_button.setObjectName("next_button")
        self.next_button.setIcon(QIcon("assets/next.png"))
        self.next_button.setShortcut(Qt.Key.Key_BracketRight)
        self.loop_button = QPushButton(self.centralwidget)
        self.loop_button.setGeometry(QRect(135, button_ypos, 24, 24))
        self.loop_button.setObjectName("loop_button")
        self.loop_button.setShortcut('L')
        self.refresh_loop_icon()
        self.up_button = QPushButton(self.centralwidget)
        self.up_button.setGeometry(QRect(600, button_ypos, 24, 24))
        self.up_button.setObjectName("up_button")
        self.up_button.setIcon(QIcon("assets/up.png"))
        self.up_button.setShortcut(Qt.Key.Key_Up + Qt.Key.Key_Shift)

        self.down_button = QPushButton(self.centralwidget)
        self.down_button.setGeometry(QRect(635, button_ypos, 24, 24))
        self.down_button.setObjectName("down_button")
        self.down_button.setIcon(QIcon("assets/down.png"))
        self.down_button.setShortcut(Qt.Key.Key_Down + Qt.Key.Key_Shift)
        self.progress_bar = QSlider(Qt.Orientation.Horizontal, self.centralwidget)
        self.progress_bar.setGeometry(QRect(20, button_ypos-25, 1450, 10))
        self.progress_bar.setObjectName("progress_bar")
        self.volume_control = QSlider(Qt.Orientation.Horizontal, self.centralwidget)
        self.volume_control.setGeometry(210, button_ypos, 120, 24)
        self.volume_control.setObjectName("volume_control")
        self.volume_control.setMaximum(150)
        self.volume_control.setMinimum(0)
        self.volume_control.setSingleStep(1)
        self.volume_control.setValue(100)
        self.mute_button = QPushButton(self.centralwidget)
        self.mute_button.setGeometry(180, button_ypos, 24, 24)
        self.mute_button.setIcon(QIcon('assets/volume_3.png'))
        self.volume_view = QLabel('100', self.centralwidget)
        self.volume_view.setGeometry(330, button_ypos + 5, 30, 16)
        self.volume_view.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.time_view = QLabel('--:--', self.centralwidget)
        self.time_view.setGeometry(QRect(360, button_ypos + 5, 200, 16))
        self.time_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_view.setObjectName("time_view")
        self.song_view = RollingLabel('Now Playing: ', self.centralwidget)
        self.song_view.setGeometry(QRect(750, button_ypos + 5, 700, 16))
        self.song_view.setObjectName("song_view")

        self.setCentralWidget(self.centralwidget)
        self.pause_button.clicked.connect(self.toggle_pause)
        self.last_button.clicked.connect(self.last)
        self.loop_button.clicked.connect(self.change_loop)
        self.next_button.clicked.connect(self.next)
        self.list.doubleClicked.connect(self.play_item)
        self.list.clicked.connect(self.select)
        self.up_button.clicked.connect(self.up_song)
        self.down_button.clicked.connect(self.down_song)
        QMetaObject.connectSlotsByName(self)
        self.model = PlaylistModel()
        self.list.setModel(self.model)
        self.progress_bar.sliderPressed.connect(self.start_drag)
        self.progress_bar.sliderReleased.connect(self.stop_drag)
        self.progress_bar.valueChanged.connect(self.slider_changed)
        self.mute_button.clicked.connect(self.toggle_mute)
        self.volume_control.valueChanged.connect(self.change_volume)

        # ----------------------------------- #

        playmenu = QMenu('Play', self)
        next_song = QAction('Next song', self)
        next_song.setShortcut('Alt+N')
        next_song.setStatusTip('Switches to next song, based on playlist and loop.')
        next_song.triggered.connect(self.next)
        playmenu.addAction(next_song)

        last_song = QAction('Last song', self)
        last_song.setShortcut('Alt+B')
        last_song.setStatusTip('Switches to last song in history')
        last_song.triggered.connect(self.last)
        playmenu.addAction(last_song)

        change_loop = QAction('Change loop', self)
        change_loop.setShortcut('Alt+L')
        change_loop.setStatusTip('Switches the loop type')
        change_loop.triggered.connect(self.change_loop)
        playmenu.addAction(change_loop)

        select = QAction('Select', self)
        select.setShortcut('Alt+P')
        select.setStatusTip('Selects a file based on information')
        select.triggered.connect(self.select)
        playmenu.addAction(select)

        deselect = QAction('Deselect', self)
        deselect.setShortcut('Esc')
        deselect.setStatusTip('Deselects the selection file')
        deselect.triggered.connect(self.deselect)
        playmenu.addAction(deselect)

        toggle_mute = QAction('Mute/Unmute', self)
        toggle_mute.setShortcut('Alt+M')
        toggle_mute.setStatusTip('Toggles the mute state')
        toggle_mute.triggered.connect(self.toggle_mute)
        playmenu.addAction(toggle_mute)

        # TODO complete this function: set the next song to play
        # set_next = QAction('Set Next', self)
        # set_next.triggered.connect(self.set_next)
        # playmenu.addAction(set_next)

        # =======

        filemenu = QMenu('File', self)

        save = QAction('Save', self)
        save.setShortcut('Alt+S')
        save.setStatusTip('Saves the current playlist')
        save.triggered.connect(self.save)
        filemenu.addAction(save)

        load = QAction('Load', self)
        load.setShortcut('Alt+O')
        load.setStatusTip('Loads a playlist')
        load.triggered.connect(self.load)
        filemenu.addAction(load)

        add = QAction('Add song', self)
        add.setShortcut('Alt+A')
        add.setStatusTip('Adds an audio file to the playlist')
        add.triggered.connect(self.add_song)
        filemenu.addAction(add)

        add_folder = QAction('Add folder', self)
        add_folder.setShortcut('Alt+Shift+O')
        add_folder.setStatusTip('Adds a folder to the playlist')
        add_folder.triggered.connect(self.add_folder)
        filemenu.addAction(add_folder)

        delete = QAction('Delete song', self)
        delete.setShortcut('Delete')
        delete.setStatusTip('Deletes the selection song')
        delete.triggered.connect(self.remove_song)
        filemenu.addAction(delete)

        clear = QAction('Clear', self)
        clear.setShortcut('Alt+Shift+Delete')
        clear.setStatusTip('Clears the current playlist')
        clear.triggered.connect(self.clear)
        filemenu.addAction(clear)

        download = QAction('Download from internet', self)
        download.setShortcut('Alt+Ctrl+D')
        download.setStatusTip('Opens a dialog to download from an online source.')
        download.triggered.connect(self.download)
        filemenu.addAction(download)

        # ==============

        editmenu = QMenu('Edit', self)

        edit = QAction('Edit Selected', self)
        edit.setShortcut('Alt+E')
        edit.setStatusTip('Edits data of the selection item')
        edit.triggered.connect(self.edit)
        editmenu.addAction(edit)

        edit_filter = QAction('Add/Edit Filter', self)
        edit_filter.setShortcut('Ctrl+F')
        edit_filter.setStatusTip('Edits the filter put over the playlist')
        edit_filter.triggered.connect(self.edit_filter)
        editmenu.addAction(edit_filter)

        clear_filter = QAction('Clear Filters', self)
        clear_filter.setShortcut('Ctrl+Alt+R')
        clear_filter.setStatusTip('Clears all filters')
        clear_filter.triggered.connect(self.clear_filter)
        editmenu.addAction(clear_filter)

        # version = QAction("Version", self)
        # version.triggered.connect(self.show_version)

       # ================

        self.menu = self.menuBar()
        self.menu.addMenu(playmenu)
        self.menu.addMenu(filemenu)
        self.menu.addMenu(editmenu)
        # self.menu.addAction(version)

        self.file_dialog = QFileDialog(self)
        self.file_dialog.setWindowIcon(QIcon('assets/Shellac.ico'))
        self.file_dialog.setViewMode(QFileDialog.ViewMode.List)
        self.file_dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
        self.file_dialog.setSidebarUrls([
            QUrl.fromLocalFile(os.path.expanduser(path.replace('./', os.getcwd()+'/').replace('\\', '/'))) for path in self.file_folders])

        self.setWindowTitle('Shellac')
        self.show()

    def show_version(self):
        self.version_popup = VersionPopup()
        self.version_popup.show()

    def timerEvent(self, _):
        if self.player.has_ended:
            self.next()
        if self.playing is not None:
            total_time = round(self.player.duration)
            current_time = round(self.player.curr_pos)
            if not self.is_dragging:
                self.progress_bar.setMaximum(total_time)
                self.progress_bar.setValue(current_time)
                self.time_view.setText(f"{std_time(current_time)}/{std_time(total_time)}")
        else:
            self.time_view.setText("--:--/--:--")
        if self.device_reset_cooldown >= 1000:
            self.player.refresh_audio_stream()
            self.device_reset_cooldown = 0
        else:
            self.device_reset_cooldown += 1
        w.setWindowIcon(self.icon)

    def edit_filter(self):
        dialog = FilterDialog(self, self.playlist.filter)
        dialog.exec()
        if dialog.result() == 0:
            return
        self.set_filter(dialog.filter)

    def clear_filter(self):
        self.set_filter(Filter())

    def set_filter(self, filter):
        if self.playing is not None and not filter.check(self.playing):
            self.player.stop()
            self.playing = None
        self.time_view.setText("--:--/--:--")
        self.song_view.setText("Now Playing: ")
        self.hist = []
        self.hist_pointer = -1
        self.playlist.set_filter(filter)
        self.model.set_playlist(self.playlist)

    def play_item(self, item):
        self.select(item)
        if keyboard.is_pressed('ctrl'):
            self.edit()
            return
        if self.hist_pointer < -1:
            self.hist = self.hist[:self.hist_pointer]
        self.hist_pointer = -1
        self.play(item)
        self.refresh_selection_highlight()
        self.refresh_pause_icon()

    def refresh_pause_icon(self):
        if self.player and self.player.is_playing:
            self.pause_button.setIcon(QIcon('assets/pause.png'))
        else:
            self.pause_button.setIcon(QIcon('assets/play.png'))

    def start_drag(self):
        self.is_dragging = True

    def stop_drag(self):
        self.is_dragging = False
        if self.playing is not None:
            self.player.seek(self.progress_bar.sliderPosition())

    def slider_changed(self):
        if self.is_dragging:
            total_time = round(self.player.duration)
            current_time = self.progress_bar.sliderPosition()
            self.time_view.setText(
                f"{std_time(current_time)}/{std_time(total_time)}")

    def pause(self):
        if self.player.is_playing:
            self.player.pause()
            self.refresh_pause_icon()

    def unpause(self):
        if self.player.is_paused:
            self.player.resume()
            self.refresh_pause_icon()

    def toggle_pause(self):
        if not self.player.is_valid:
            return
        if self.player.is_paused:
            self.unpause()
        elif self.player.is_playing:
            self.pause()

    def change_volume(self, v):
        self.volume = v / 100
        if self.player.is_valid:
            self.player.set_volume(2/3 * (0 if self.is_muted else self.volume))
        self.refresh_mute_icon()
        self.volume_view.setText(str(v))

    def toggle_mute(self):
        self.is_muted = not self.is_muted
        if self.player.is_valid:
            self.player.set_volume(2/3 * (0 if self.is_muted else self.volume))
        self.refresh_mute_icon()

    def refresh_mute_icon(self):
        if self.volume == 0:
            self.mute_button.setIcon(QIcon('assets/volume_0.png'))
        elif self.volume <= 0.5:
            self.mute_button.setIcon(QIcon(f'assets/volume_1{"_mute" if self.is_muted else ""}'))
        elif self.volume <= 1:
            self.mute_button.setIcon(QIcon(f'assets/volume_2{"_mute" if self.is_muted else ""}'))
        else:
            self.mute_button.setIcon(QIcon(f'assets/volume_3{"_mute" if self.is_muted else ""}'))

    def clear(self):
        if not self.window().isActiveWindow():
            return
        if self.player.is_valid:
            self.player.stop()
        self.playlist = Playlist()
        self.playlist.set_filter(Filter())
        self.model.set_playlist(self.playlist)
        self.song_view.setText("Now Playing:")

    def up_song(self):
        for i in range(len(self.playlist.selected)):
            i = self.playlist.get_index(self.playlist.selected[i])
            k = 1
            for n in range(1, 10):
                if keyboard.is_pressed(str(n)):
                    k = n
            self.playlist.move_up(i, k, keyboard.is_pressed('alt'))
        self.model.set_playlist(self.playlist)
        self.refresh_selection_highlight()

    def down_song(self):
        for i in range(len(self.playlist.selected)-1, -1, -1):
            i = self.playlist.get_index(self.playlist.selected[i])
            k = 1
            for n in range(1, 10):
                if keyboard.is_pressed(str(n)):
                    k = n
            self.playlist.move_down(i, k, keyboard.is_pressed('alt'))
        self.model.set_playlist(self.playlist)
        self.refresh_selection_highlight()

    def select(self, i=None):
        if not self.window().isActiveWindow():
            return
        if not isinstance(i, QModelIndex):
            dialog = QDialog()
            label = QLabel("Enter Name/Index (separated with ; if multiple):", dialog)
            text = QTextEdit(dialog)
            buttons = QDialogButtonBox(dialog)
            buttons.setStandardButtons(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            dialog.setWindowTitle("Select Song")
            dialog.resize(300, 180)
            label.setGeometry(10, 10, 280, 30)
            text.setGeometry(10, 40, 280, 50)
            buttons.setGeometry(10, 100, 280, 80)
            dialog.setWindowIcon(QIcon('assets/Shellac.ico'))
            dialog.exec()
            if dialog.result() == 1:
                for i in text.toPlainText().split(';'):
                    self.playlist.select(self.playlist.get_song(i))
        else:
            if not keyboard.is_pressed('shift'):
                self.playlist.reselect(self.playlist[i.row()])
            else:
                self.playlist.toggle_select(self.playlist[i.row()])
        self.refresh_selection_highlight()

    def dragEnterEvent(self, a0):  # Haven't figured out how this works yet. Currently stub
        self.drag = a0.mimeData().text()
        a0.accept()

    def dropEvent(self, a0):
        if '.' not in self.drag.replace('\\', '/').split('/')[-1]:
            self.load_folder(self.drag)
            return
        file_type = self.drag.split('.')[-1]
        if file_type == 'slp':
            self.load_playlist(self.drag)
        elif file_type in audio_formats:
            self.add_song(path=self.drag)

    # def set_next(self):
    #     dialog = QDialog()
    #     dialog.resize(400, 600)
    #     buttons = QDialogButtonBox(dialog)
    #     buttons.setGeometry(0, 500, 400, 100)
    #     buttons.setStandardButtons(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
    #     buttons.accepted.connect(dialog.accept)
    #     buttons.rejected.connect(dialog.reject)
    #     dialog.setWindowTitle("Set Next to play")
    #     unset_button = QPushButton(dialog, "Unset next")
    #     unset_button.setGeometry()

    def edit(self, item=None):
        if not isinstance(item, QModelIndex) and item is not None and not isinstance(item, bool):
            to_edit = self.playlist[item.row()]
        if not self.window().isActiveWindow() or self.playlist.is_empty_selection():
            return
        to_edit = self.playlist.selected[0]
        dialog = QDialog()
        dialog.resize(300, 400)
        name_label = QLabel("Name", dialog)
        name_label.setGeometry(10, 10, 280, 20)
        name_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        name_edit = QTextEdit(to_edit.name, dialog)
        name_edit.setGeometry(10, 30, 280, 100)
        tags_label = QLabel("Tags (Artist is always the first tag)", dialog)
        tags_label.setGeometry(10, 140, 280, 20)
        tags_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        tags_edit = QTextEdit(', '.join(to_edit.tags), dialog)
        tags_edit.setGeometry(10, 160, 280, 120)
        weight_label = QLabel("Weight:", dialog)
        weight_label.setGeometry(10, 290, 280, 30)
        weight_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        weight_edit = QSpinBox(dialog)
        weight_edit.setGeometry(180, 290, 100, 30)
        weight_edit.setValue(to_edit.weight)
        weight_edit.setMinimum(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        buttons.setGeometry(10, 325, 280, 75)
        dialog.exec()
        if dialog.result() == 1:
            self.playlist.update(to_edit, name_edit.toPlainText(), tags_edit.toPlainText().split(', '), weight_edit.value())
            self.model.set_playlist(self.playlist)


style_file = 'styles/default.qss'
style_sheet = QSSLoader.read_qss_file(style_file)

app = QApplication(sys.argv)

w = Player()

w.setStyleSheet(style_sheet)
app.setWindowIcon(QIcon('assets/Shellac.ico'))
w.setWindowIcon(QIcon('assets/Shellac.ico'))



qt_material.apply_stylesheet(app, theme="dark_teal.xml")

w.show()
sys.exit(app.exec())

