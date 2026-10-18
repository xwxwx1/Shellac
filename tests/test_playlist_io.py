import json

import pytest

from shellac.core import playlist_io
from shellac.core.playlist_io import PlaylistFormatError


def test_roundtrip_unicode_and_separators(make_song, tmp_path):
    songs = [make_song('歌; with::separators', ['艺术家', 'a, b?']), make_song('plain', weight=4)]
    path = tmp_path / 'list.slp'
    playlist_io.save(str(path), songs)
    assert json.loads(path.read_text(encoding='utf-8'))['format'] == 'shellac-playlist'
    entries = playlist_io.load(str(path))
    assert [(e.path, e.name, list(e.tags), e.weight) for e in entries] == \
           [(s.path, s.name, s.tags, s.weight) for s in songs]


def test_legacy_format(tmp_path):
    path = tmp_path / 'old.slp'
    path.write_bytes('path::./music/歌.mp3;name::歌;tags::A, b;weight::2\n'
                     'path::C:/x/y.mp3;name::y;tags::;weight::1\n\n'.encode())
    first, second = playlist_io.load(str(path))
    assert first.path.replace('\\', '/').endswith('/music/歌.mp3')
    assert (first.name, first.tags, first.weight) == ('歌', ('A', 'b'), 2)
    assert second.tags == ()  # an empty tags field means no tags, not one blank tag


def test_legacy_locale_encoded_file_is_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(playlist_io.locale, 'getpreferredencoding', lambda _=False: 'gbk')
    path = tmp_path / 'old.slp'
    path.write_bytes('path::C:/m/歌.mp3;name::歌;tags::;weight::1\n'.encode('gbk'))
    assert playlist_io.load(str(path))[0].name == '歌'


@pytest.mark.parametrize('content', ['{not json', '{"format": "other"}', 'garbage line\n'])
def test_bad_files_raise(tmp_path, content):
    path = tmp_path / 'bad.slp'
    path.write_text(content, encoding='utf-8')
    with pytest.raises(PlaylistFormatError):
        playlist_io.load(str(path))
