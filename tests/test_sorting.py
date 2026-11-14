"""The proxy's cached sort keys must never go stale: after every kind of change, the table must still
be sorted by the current values."""
import random

import pytest
from PyQt6.QtCore import Qt

from shellac.core.filter import Filter, TagTerm
from shellac.core.song import Song
from shellac.ui.playlist_model import (
    ALBUM,
    ARTIST,
    LENGTH,
    NAME,
    TAGS,
    WEIGHT,
    FilterProxy,
    PlaylistModel,
    sort_key,
)

COLUMNS = (NAME, LENGTH, TAGS, ARTIST, ALBUM, WEIGHT)


def library(n, rng, start=0):
    tags = ['Ann', 'bob', 'Cat', 'jazz', 'Rock', 'live', '周', 'zed']
    return [Song(f'C:/x/{start + i}.mp3', rng.choice(['b', 'A', 'c', 'á', '夜', 'B']) + str(rng.randint(0, 5)),
                 rng.sample(tags, rng.randint(0, 4)), rng.randint(0, 3),
                 rng.choice([None, 10.0, 200.5, 3.0]), rng.choice([None, 'X', 'y']))
            for i in range(n)]


def check_order(model, proxy, column, order):
    """Visible keys are in sorted order and exactly the filtered songs are shown.

    Ties are not checked: when rows are inserted into an already sorted view, Qt does not promise
    to keep equal keys in playlist order (true with or without the key cache).
    """
    visible = proxy.visible_songs()
    wanted = [s for s in model.playlist if proxy.filterAcceptsRow(model.row_of(s), None)]
    assert sorted(map(id, visible)) == sorted(map(id, wanted))
    keys = [sort_key(s, column) for s in visible]
    assert keys == sorted(keys, reverse=order == Qt.SortOrder.DescendingOrder)


@pytest.mark.parametrize('column', COLUMNS)
@pytest.mark.parametrize('order', [Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder])
def test_sorted_order_survives_every_change(qtbot, column, order):
    rng = random.Random(column * 10 + order.value)
    model = PlaylistModel()
    proxy = FilterProxy(model)
    model.add_songs(library(60, rng))
    proxy.sort(column, order)

    def check():
        check_order(model, proxy, column, order)
    check()

    model.add_songs(library(15, rng, start=100), row=10)  # insert while sorted
    check()
    model.remove_songs(rng.sample(list(model.playlist), 12))
    check()
    for song in rng.sample(list(model.playlist), 8):  # in-place edits and dialog edits
        proxy.setData(proxy.index(proxy.row_of(song), NAME), rng.choice(['zz', 'aa', 'Mm']))
        model.update_song(song, tags=rng.sample(['Ann', 'zed', 'jazz'], 2), weight=rng.randint(0, 9))
    check()
    model.reorder(list(reversed(list(model.playlist))))  # playlist order changes tie order
    check()
    proxy.set_filter(Filter(rules=[[TagTerm('jazz', False)]]))
    check()
    proxy.set_filter(Filter())
    proxy.sort(-1)
    assert proxy.visible_songs() == list(model.playlist)
    model.clear()
    proxy.sort(column, order)
    assert proxy.rowCount() == 0
