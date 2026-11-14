import pytest

from shellac.core.playlist import Playlist
from shellac.core.song import Song


def test_add_dedups_by_file_not_name(make_song, tmp_path):
    p = Playlist()
    a = make_song('a')
    same_file = Song(a.path, 'other name')
    same_name = Song(str(tmp_path / 'elsewhere' / 'a.mp3'), 'a')
    assert p.add([a, same_file, same_name]) == [a, same_name]
    assert len(p) == 2 and p.get(a.path) is a


def test_add_at_position_and_index(make_song):
    a, b, c = make_song('a'), make_song('b'), make_song('c')
    p = Playlist([a, c])
    p.add([b], position=1)
    assert list(p) == [a, b, c]
    assert [p.index(s) for s in (a, b, c)] == [0, 1, 2]


def test_remove(make_song):
    a, b, c = make_song('a'), make_song('b'), make_song('c')
    p = Playlist([a, b, c])
    assert p.remove([b, make_song('stranger')]) == [b]
    assert list(p) == [a, c] and b not in p
    with pytest.raises(ValueError):
        p.index(b)
    p.add([b])  # can be re-added once removed
    assert list(p) == [a, c, b]


def test_reorder_subset_keeps_others_in_place(make_song):
    a, b, c, d, e = (make_song(n) for n in 'abcde')
    p = Playlist([a, b, c, d, e])
    p.reorder([d, b])  # e.g. b and d visible through a filter, d moved above b
    assert list(p) == [a, d, c, b, e]
    assert p.index(b) == 3


def test_update_and_tags(make_song):
    a = make_song('a', ['X'])
    p = Playlist([a, make_song('b', ['Y', 'X'])])
    p.update(a, name='new', tags=['Z'], weight=3)
    assert (a.name, a.tags, a.weight) == ('new', ['Z'], 3)
    assert p.all_tags() == ['Z', 'Y', 'X']


def test_relocate(make_song, tmp_path):
    a, b = make_song('a'), make_song('b')
    p = Playlist([a, b])
    new = tmp_path / 'moved' / 'a.mp3'
    new.parent.mkdir()
    new.touch()
    p.relocate(a, str(new))
    assert p.get(str(new)) is a and a.path == new.as_posix() and not a.missing
    with pytest.raises(ValueError, match='already in the playlist'):
        p.relocate(a, b.path)
    assert p.get(str(new)) is a
