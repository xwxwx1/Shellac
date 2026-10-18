import random

from shellac.core.ordering import LoopMode, moved_to_edge, next_in_list, pick_next, shifted, weighted_choice


def seq(*values):
    it = iter(values)
    return lambda: next(it)


def test_loop_mode_cycles_and_names():
    assert LoopMode.STOP.cycled() is LoopMode.REPEAT_ONE
    assert [m.icon_name for m in LoopMode] == ['repeat', 'list', 'shuffle', 'none']


def test_weighted_choice_respects_weights_and_exclusion(make_song):
    a, b, c = make_song('a', weight=1), make_song('b', weight=3), make_song('c', weight=0)
    songs = [a, b, c]
    # Excluding a leaves only b with any weight.
    assert all(weighted_choice(songs, a, rng=lambda r=r: r) is b for r in (0, 0.5, 0.999999))
    assert weighted_choice(songs, None, rng=seq(0.2)) is a  # 0.2*4 = 0.8 < 1
    assert weighted_choice(songs, None, rng=seq(0.3)) is b
    # Floating-point overshoot never returns None or a weight-0 song.
    assert weighted_choice(songs, None, rng=lambda: 1.0) is b


def test_weighted_choice_edge_cases(make_song):
    only = make_song('only')
    assert weighted_choice([], None) is None
    assert weighted_choice([only], only) is only
    zero = [make_song('x', weight=0), make_song('y', weight=0)]
    assert weighted_choice(zero, None, rng=seq(0.6)) is zero[1]


def test_weighted_choice_distribution(make_song):
    rng = random.Random(1)
    a, b = make_song('a', weight=1), make_song('b', weight=3)
    picks = [weighted_choice([a, b], None, rng.random) for _ in range(4000)]
    assert 0.7 < picks.count(b) / len(picks) < 0.8


def test_next_in_list_wraps_and_handles_missing(make_song):
    a, b = make_song('a'), make_song('b')
    assert next_in_list([a, b], a) is b
    assert next_in_list([a, b], b) is a
    assert next_in_list([a, b], make_song('hidden')) is a
    assert next_in_list([], a) is None


def test_pick_next_modes(make_song):
    a, b, c = make_song('a'), make_song('b'), make_song('c')
    songs = [a, b, c]
    assert pick_next(LoopMode.REPEAT_ONE, songs, b, manual=False) is b
    assert pick_next(LoopMode.REPEAT_ONE, songs, b, manual=True) is c
    assert pick_next(LoopMode.LIST, songs, c, manual=False) is a
    assert pick_next(LoopMode.STOP, songs, a, manual=False) is None
    assert pick_next(LoopMode.STOP, songs, a, manual=True) is b
    assert pick_next(LoopMode.SHUFFLE, songs, a, manual=False, rng=lambda: 0) is b


def test_shifted():
    order = list('abcde')
    assert shifted(order, ['b', 'd'], -1) == list('badce')
    assert shifted(order, ['a', 'b', 'd'], -1) == list('abdce')  # a and b are blocked at the top
    assert shifted(order, ['d', 'e'], +1) == list('abcde')
    assert shifted(order, ['a', 'c'], +1) == list('badce')


def test_moved_to_edge():
    order = list('abcde')
    assert moved_to_edge(order, ['d', 'b'], top=True) == list('bdace')
    assert moved_to_edge(order, ['b', 'd'], top=False) == list('acebd')
