"""Benchmark filtering, searching and sorting on a large, densely tagged playlist.

    python benchmarks/bench_library.py [--songs 2000] [--repeat 7]

Runs offscreen against the real MainWindow (isolated config, no files needed: songs point at paths
that don't exist and are never read). Times are wall-clock milliseconds; each line shows the median
and the worst of the repeats. One screen frame at 60 Hz is ~16 ms; anything over ~100 ms is a
visible stall.
"""
from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from shellac import config  # noqa: E402
from shellac.core.filter import Filter, TagTerm, parse_rules  # noqa: E402
from shellac.core.ordering import shifted  # noqa: E402
from shellac.core.song import Song  # noqa: E402
from shellac.ui.playlist_model import ALBUM, ARTIST, LENGTH, NAME, TAGS, WEIGHT  # noqa: E402

RESULTS = []


def make_library(n: int, seed: int = 1):
    rng = random.Random(seed)
    artists = [f'Artist {i:03d}' for i in range(150)] + ['Miles Davis', '周杰伦', 'Debussy']
    genres = [f'genre-{i}' for i in range(60)] + ['jazz', 'rock', 'classical', 'live']
    moods = [f'mood {i}' for i in range(80)]
    misc = [f'tag{i}' for i in range(110)]
    pool = genres + moods + misc
    words = ['Blue', 'Night', 'Song', 'River', 'Light', '夜曲', 'Suite', 'No.', 'Remix', 'Live', 'Theme', 'Moon']
    songs = []
    for i in range(n):
        artist = rng.choice(artists)
        tags = [artist] + rng.sample(pool, rng.randint(12, 30))
        name = ' '.join(rng.choice(words) for _ in range(rng.randint(2, 6))) + f' {i}'
        album = rng.choice([None, f'Album {rng.randint(1, 300)}', 'Kind of Blue'])
        songs.append(Song(f'C:/nonexistent/library/{i:05d}.mp3', name, tags, rng.randint(0, 9),
                          rng.uniform(30, 900), album))
    return songs


ROWS = None  # callable giving the visible row count, set once the window exists


def timed(label, fn, repeat, setup=None, note=''):
    samples = []
    for _ in range(repeat):
        if setup:
            setup()
        QApplication.processEvents()
        start = time.perf_counter()
        fn()
        QApplication.processEvents()  # include whatever the change queued (repaints, signals)
        samples.append((time.perf_counter() - start) * 1000)
    if ROWS is not None and not note:
        note = f'{ROWS()} rows shown'
    RESULTS.append((label, statistics.median(samples), max(samples), note))
    print(f'  {label:<58} {statistics.median(samples):8.2f} ms   (max {max(samples):8.2f})  {note}', flush=True)


def section(title):
    print(f'\n{title}')
    RESULTS.append((f'## {title}', None, None, ''))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--songs', type=int, default=2000)
    parser.add_argument('--repeat', type=int, default=7)
    args = parser.parse_args()
    n, repeat = args.songs, args.repeat

    tmp = Path(tempfile.mkdtemp())
    config.CONFIG_DIR = tmp / 'cfg'
    config.CONFIG_PATH = tmp / 'cfg' / 'config.txt'
    config.DATA_DIR = tmp / 'data'
    app = QApplication([])
    cfg = config.load_config()
    cfg.update(mediakeys='False', trayicon='False', restoresession='False')

    from shellac.ui.main_window import MainWindow
    library = make_library(n)
    tag_counts = sum(len(s.tags) for s in library)
    print(f'{n} songs, {tag_counts} tag assignments ({tag_counts / n:.1f} per song), '
          f'{len({t for s in library for t in s.tags})} distinct tags')

    # --- core, no Qt -------------------------------------------------------------------------
    section('Core filter checks (pure Python, all songs)')
    filters = {
        'empty filter': Filter(),
        'one tag': Filter(rules=[[TagTerm('jazz')]]),
        'tag AND NOT tag': Filter(rules=[[TagTerm('jazz'), TagTerm('live', False)]]),
        'dense DNF: 6 rules x 4 terms': Filter(rules=[[TagTerm(f'genre-{r * 4 + k}', k % 2 == 0) for k in range(4)]
                                                      for r in range(6)]),
        'regex': Filter(regex=r'(?i)night|moon'),
        'regex OR tags (non-strict)': Filter(regex='Remix', rules=[[TagTerm('rock')]], strict=False),
    }
    for label, f in filters.items():
        timed(f'check() x{n}: {label}', lambda f=f: [f.check(s) for s in library], repeat)
    query = ' OR '.join(' AND '.join(f'"genre-{r}{k}"' for k in range(4)) for r in range(20))
    timed('parse_rules: 20 rules x 4 terms', lambda: parse_rules(query), repeat)

    # --- window ------------------------------------------------------------------------------
    window = MainWindow(cfg)
    window.resize(1400, 900)
    window.show()
    QApplication.processEvents()
    model, proxy, table, header = window.model, window.proxy, window.table, window.table.horizontalHeader()
    global ROWS

    section('Loading into the table')

    def clear():
        model.clear()
        window.tag_browser.refresh()

    def load_batched():
        for i in range(0, n, 50):  # the scanner delivers 50 songs per batch
            model.add_songs(library[i:i + 50])
    timed(f'add {n} songs in batches of 50 (scanner path)', load_batched, 3, setup=clear)
    timed(f'add {n} songs in one batch', lambda: model.add_songs(library), 3, setup=clear)
    timed('tag browser rebuild (counts + list)',
          lambda: (setattr(window.tag_browser, '_counts', None), window.tag_browser.refresh()), repeat)
    timed('tag browser refresh with nothing changed', window.tag_browser.refresh, repeat)
    ROWS = proxy.rowCount

    section('Filtering through the proxy (what the table shows)')

    def reset_filters():
        window.set_filter(Filter())
        window.search.clear()
        window.tag_browser.set_checked([])
    for label, f in list(filters.items())[1:]:
        timed(f'set filter: {label}', lambda f=f: window.set_filter(f), repeat, setup=reset_filters)
    timed('clear filter (back to all songs)', lambda: window.set_filter(Filter()), repeat,
          setup=lambda: window.set_filter(filters['dense DNF: 6 rules x 4 terms']))
    timed('tick one tag in the Tags panel', lambda: window.tag_browser.set_checked(['jazz']), repeat,
          setup=reset_filters)
    timed('tick three tags', lambda: window.tag_browser.set_checked(['jazz', 'mood 3', 'tag7']), repeat,
          setup=reset_filters)

    reset_filters()
    section('Search box, per keystroke')
    typed = 'blue night'
    for i in range(1, len(typed) + 1):
        prefix = typed[:i]
        if prefix.endswith(' '):
            continue
        timed(f'type "{prefix}"', lambda p=prefix: window.search.setText(p), repeat,
              setup=lambda p=prefix: window.search.setText(p[:-1]))
    timed('clear search', window.search.clear, repeat, setup=lambda: window.search.setText('blue night'))
    window.search.clear()

    reset_filters()
    assert proxy.rowCount() == n, 'sorting must be measured on the whole list'
    section('Sorting (header clicks)')
    for column, name in ((NAME, 'Name'), (LENGTH, 'Length'), (TAGS, 'Tags'), (ARTIST, 'Artist'),
                         (ALBUM, 'Album'), (WEIGHT, 'Weight')):
        timed(f'sort by {name} ascending', lambda c=column: header.setSortIndicator(c, Qt.SortOrder.AscendingOrder),
              repeat, setup=window.clear_sort)
        timed(f'sort by {name}: flip to descending',
              lambda c=column: header.setSortIndicator(c, Qt.SortOrder.DescendingOrder), repeat,
              setup=lambda c=column: header.setSortIndicator(c, Qt.SortOrder.AscendingOrder))
    timed('clear sort (back to playlist order)', window.clear_sort, repeat,
          setup=lambda: header.setSortIndicator(TAGS, Qt.SortOrder.AscendingOrder))

    section('Sorted and filtered together')
    header.setSortIndicator(TAGS, Qt.SortOrder.AscendingOrder)
    timed('sorted by Tags: set dense DNF filter', lambda: window.set_filter(filters['dense DNF: 6 rules x 4 terms']),
          repeat, setup=reset_filters)
    timed('sorted by Tags: type a search letter', lambda: window.search.setText('bl'), repeat,
          setup=lambda: window.search.setText('b'))
    reset_filters()
    timed('sorted by Tags: change playing song (2 rows repaint/re-sort)',
          lambda: model.set_playing(library[random.randrange(n)]), repeat * 3)
    timed('sorted by Tags: edit a cell in place (tags)',
          lambda: proxy.setData(proxy.index(random.randrange(n), TAGS), 'jazz, rock, live'), repeat * 3)
    window.clear_sort()

    reset_filters()
    section('Playback and editing helpers on the full list')
    window.set_filter(filters['one tag'])
    timed('visible_songs() (runs on every Next / track end)', proxy.visible_songs, repeat)
    picks = random.Random(2).sample(library, 100)
    timed('row_of() for 100 songs', lambda: [proxy.row_of(s) for s in picks], repeat)
    visible = proxy.visible_songs()
    chosen = visible[::5]
    timed(f'move {len(chosen)} selected songs up one (filtered)',
          lambda: model.reorder(shifted(proxy.visible_songs(), chosen, -1)), repeat)
    timed('select 100 songs', lambda: window.select_songs(picks), repeat)
    window.set_filter(Filter())
    timed('build session state (save)', window.session_state, repeat)
    timed('repaint the visible table', lambda: table.viewport().repaint(), repeat)

    print()
    slow = [(label, med) for label, med, _, _ in RESULTS if med is not None and med > 16]
    if slow:
        print('Slower than one frame (16 ms):')
        for label, med in sorted(slow, key=lambda x: -x[1]):
            print(f'  {med:8.1f} ms  {label}')
    else:
        print('Everything finished within one frame (16 ms).')
    window.close()


if __name__ == '__main__':
    main()
