import os

from shellac.core.song import Song, default_name, is_audio_file, parse_tags, path_key, song_from_file


def test_parse_tags_strips_blanks_and_duplicates():
    assert parse_tags('') == []
    assert parse_tags(' Artist , rock,, rock ,live') == ['Artist', 'rock', 'live']


def test_artist_is_first_tag(make_song):
    assert make_song('a').artist == '/'
    assert make_song('a', ['X', 'rock']).artist == 'X'


def test_songs_compare_by_identity(make_song):
    a, b = make_song('same'), make_song('same')
    assert a != b and a.key == b.key


def test_path_normalisation(tmp_path):
    song = Song(str(tmp_path) + os.sep + 'x.mp3', 'x')
    assert '\\' not in song.path and os.path.isabs(song.path)
    assert path_key(song.path) == path_key(str(tmp_path / 'x.mp3'))


def test_is_audio_file():
    assert is_audio_file('a/B.MP3') and is_audio_file('c.flac')
    assert not is_audio_file('c.txt') and not is_audio_file('noext')


def test_missing_file_still_makes_a_song(tmp_path):
    song = song_from_file(str(tmp_path / 'gone.mp3'))
    assert song.name == 'gone' and song.duration is None and not song.exists


def test_default_name_prefers_title():
    assert default_name('/x/a.b.mp3') == 'a.b'
    assert default_name('/x/a.mp3', 'Title') == 'Title'
