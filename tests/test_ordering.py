import random

from shellac.core.ordering import (
    LoopMode,
    ShuffleCycle,
    moved_to_edge,
    next_in_list,
    pick_next,
    shifted,
    weighted_choice,
)


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


# --- ShuffleCycle: a song with weight w gets w slots per cycle ---------------------------------

def first_slot():
    """An rng that always draws the first song that still has slots (makes cycles predictable)."""
    return lambda: 0.0


def test_cycle_gives_each_song_its_weight_in_slots(make_song):
    a, b, c, d = (make_song(n, weight=w) for n, w in zip('abcd', [1, 3, 2, 0]))
    cycle = ShuffleCycle()
    current, picks = None, []
    for _ in range(6):  # one full cycle: 1 + 3 + 2 slots
        current = cycle.choose([a, b, c, d], current, first_slot())
        picks.append(current.name)
    assert picks == ['a', 'b', 'c', 'b', 'c', 'b']  # never the same song twice in a row
    assert [cycle.plays(s) for s in (a, b, c, d)] == [1, 3, 2, 0]
    # Every slot is used, so the next pick starts a new cycle (and still avoids the playing song).
    assert cycle.choose([a, b, c, d], current, first_slot()) is a
    assert [cycle.plays(s) for s in (a, b, c, d)] == [1, 0, 0, 0]


def test_random_cycles_respect_slots(make_song):
    songs = [make_song(n, weight=w) for n, w in zip('abcde', [1, 4, 2, 0, 3])]
    for seed in range(40):
        rng = random.Random(seed)
        cycle = ShuffleCycle()
        current, plays = None, {s: 0 for s in songs}
        for _ in range(60):
            previous = current
            current = cycle.choose(songs, current, rng.random)
            assert current is not previous and current.weight > 0
            after = {s: cycle.plays(s) for s in songs}
            if sum(after.values()) < sum(plays.values()) + 1:
                # A new cycle started: the old one had used every slot except the playing song's.
                assert all(plays[s] == s.weight for s in songs if s is not previous)
                assert sum(after.values()) == 1
            else:
                assert after[current] == plays[current] + 1  # exactly one slot per pick
            assert all(after[s] <= s.weight for s in songs)
            plays = after


def test_long_run_frequency_follows_weight(make_song):
    songs = [make_song(n, weight=w) for n, w in zip('abcd', [1, 2, 3, 4])]
    rng = random.Random(7)
    cycle = ShuffleCycle()
    current, counts = None, dict.fromkeys(songs, 0)
    for _ in range(20000):
        current = cycle.choose(songs, current, rng.random)
        counts[current] += 1
    shares = [counts[s] / 20000 for s in songs]
    # Ideal shares are 0.1/0.2/0.3/0.4; avoiding back-to-back repeats trims the heaviest song a little.
    for share, ideal in zip(shares, (0.1, 0.2, 0.3, 0.4)):
        assert abs(share - ideal) < 0.03


def test_manual_plays_use_up_slots(make_song):
    a, b, c = (make_song(n, weight=1) for n in 'abc')
    cycle = ShuffleCycle()
    cycle.mark_played(a)  # e.g. double-clicked
    first = cycle.choose([a, b, c], a, random.random)
    second = cycle.choose([a, b, c], first, random.random)
    assert {first, second} == {b, c}  # a's only slot is used up for this cycle


def test_cycle_edge_cases(make_song):
    a, b = make_song('a', weight=2), make_song('b', weight=0)
    z1, z2 = make_song('z1', weight=0), make_song('z2', weight=0)
    cycle = ShuffleCycle()
    assert cycle.choose([], None) is None  # e.g. the filter shows nothing
    assert pick_next(LoopMode.SHUFFLE, [], None, manual=False, cycle=cycle) is None
    # Only the playing song has any weight: it plays again rather than recursing forever.
    assert all(cycle.choose([a], a) is a for _ in range(5))
    assert all(cycle.choose([a, b], a) is a for _ in range(5))
    # Every weight is 0: plain uniform shuffle that still avoids the playing song.
    assert all(cycle.choose([z1, z2], z1, random.Random(i).random) is z2 for i in range(50))
    assert cycle.choose([z1], z1) is z1


def test_weight_changes_mid_cycle(make_song):
    a, b = make_song('a', weight=3), make_song('b', weight=1)
    cycle = ShuffleCycle()
    for _ in range(3):
        cycle.mark_played(a)
    a.weight = 1  # lowered below what it already played: no negative slots
    assert cycle.choose([a, b], None, first_slot()) is b
    a.weight = 5  # raised: the extra slots become available in the same cycle
    assert cycle.choose([a, b], b, first_slot()) is a and cycle.plays(a) == 4


def test_heavy_weights_stay_cheap(make_song):
    import time
    songs = [make_song(f's{i}', weight=999) for i in range(2000)]  # the weight spin box maximum
    cycle = ShuffleCycle()
    start = time.perf_counter()
    for _ in range(20):
        cycle.choose(songs, None)
    assert (time.perf_counter() - start) / 20 < 0.02  # no list of ~2 million slots per pick


def test_pick_next_counts_each_cycle_pick_once(make_song):
    a, b = make_song('a', weight=2), make_song('b', weight=1)
    cycle = ShuffleCycle()
    picks = [pick_next(LoopMode.SHUFFLE, [a, b], None, manual=False, rng=first_slot(), cycle=cycle)]
    picks.append(pick_next(LoopMode.SHUFFLE, [a, b], picks[-1], manual=True, rng=first_slot(), cycle=cycle))
    picks.append(pick_next(LoopMode.SHUFFLE, [a, b], picks[-1], manual=False, rng=first_slot(), cycle=cycle))
    assert picks == [a, b, a] and (cycle.plays(a), cycle.plays(b)) == (2, 1)
    # Outside shuffle mode the cycle isn't consulted, so nothing is counted.
    pick_next(LoopMode.LIST, [a, b], a, manual=False, cycle=cycle)
    assert (cycle.plays(a), cycle.plays(b)) == (2, 1)
