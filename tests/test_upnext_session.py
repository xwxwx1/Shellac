import json
import subprocess

from shellac.core.session import Session
from shellac.core.song import read_cover, read_metadata, song_from_file
from shellac.core.upnext import UpNext
from shellac.download.ffmpeg import ffmpeg_exe


def test_upnext_order_and_availability():
    q = UpNext()
    q.append(['c', 'd'])
    q.play_next(['a', 'b'])
    assert list(q) == ['a', 'b', 'c', 'd']
    assert q.pop(lambda s: s != 'a') == 'b'  # 'a' is skipped and dropped
    q.remove(['d'])
    assert list(q) == ['c']
    q.append(['e', 'f'])
    assert q.move(0, 1) == 1 and list(q) == ['e', 'c', 'f']
    assert q.move(2, 1) == 2  # can't move past the end
    q.remove_at([0, 2])
    assert list(q) == ['c']
    assert q.pop() == 'c' and q.pop() is None


def test_session_roundtrip(tmp_path, make_song):
    path = tmp_path / 'sub' / 'session.json'
    song = make_song('歌', ['x'], weight=3)
    s = Session(songs=[Session.song_dict(song)], current=song.path, position=12.5, volume=80, muted=True,
                filter={'regex': 'a', 'rules': [], 'strict': True}, queue=[song.path], sort_column=2)
    s.save(str(path))
    loaded = Session.load(str(path))
    assert loaded == s
    entry, = loaded.entries()
    assert (entry.path, entry.name, entry.tags, entry.weight) == (song.path, '歌', ('x',), 3)


def test_session_tolerates_bad_files(tmp_path):
    path = tmp_path / 'session.json'
    assert Session.load(str(path)) == Session()
    path.write_text('{broken', encoding='utf-8')
    assert Session.load(str(path)) == Session()
    path.write_text(json.dumps({'volume': 'loud', 'position': 3, 'songs': [{'name': 'no path'}, 7]}),
                    encoding='utf-8')
    loaded = Session.load(str(path))
    assert loaded.volume == 100 and loaded.position == 3 and loaded.entries() == []


def test_metadata_artist_album_and_cover(tmp_path):
    cover = tmp_path / 'cover.png'
    song_path = tmp_path / 'tagged.mp3'
    ff = ffmpeg_exe()
    subprocess.run([ff, '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=red:s=32x32', '-frames:v', '1',
                    str(cover)], check=True)
    subprocess.run([ff, '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=duration=1', '-i', str(cover),
                    '-map', '0', '-map', '1', '-c:v', 'copy', '-disposition:v', 'attached_pic',
                    '-metadata', 'title=Title', '-metadata', 'artist=Someone', '-metadata', 'album=Record',
                    str(song_path)], check=True)
    meta = read_metadata(str(song_path))
    assert (meta.title, meta.artist, meta.album) == ('Title', 'Someone', 'Record')
    assert read_cover(str(song_path)).startswith(b'\x89PNG')

    song = song_from_file(str(song_path), artist_as_tag=True)
    assert (song.name, song.tags, song.album, song.missing) == ('Title', ['Someone'], 'Record', False)
    assert song_from_file(str(song_path), tags=['Mine'], artist_as_tag=True).tags == ['Mine']
    assert song_from_file(str(song_path)).tags == []
    assert song_from_file(str(tmp_path / 'gone.mp3')).missing
