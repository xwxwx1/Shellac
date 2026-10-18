"""Choosing what plays next, and reordering selections."""
from __future__ import annotations

import random
from enum import IntEnum


class LoopMode(IntEnum):
    # Values match the `loopmode` setting written by earlier versions.
    REPEAT_ONE = 0
    LIST = 1
    SHUFFLE = 2
    STOP = 3

    def cycled(self) -> LoopMode:
        return LoopMode((self + 1) % len(LoopMode))

    @property
    def icon_name(self) -> str:
        return {LoopMode.REPEAT_ONE: 'repeat', LoopMode.LIST: 'list',
                LoopMode.SHUFFLE: 'shuffle', LoopMode.STOP: 'none'}[self]

    @property
    def label(self) -> str:
        return {LoopMode.REPEAT_ONE: 'Repeat one', LoopMode.LIST: 'Play in order',
                LoopMode.SHUFFLE: 'Weighted shuffle', LoopMode.STOP: 'Stop after song'}[self]


def weighted_choice(songs, exclude=None, rng=random.random):
    """Pick a song with probability proportional to its weight, avoiding `exclude` if possible."""
    candidates = [s for s in songs if s is not exclude] or list(songs)
    if not candidates:
        return None
    weights = [max(s.weight, 0) for s in candidates]
    total = sum(weights)
    if total == 0:
        return candidates[int(rng() * len(candidates)) % len(candidates)]
    target = rng() * total
    for song, weight in zip(candidates, weights):
        if target < weight:
            return song
        target -= weight
    # Floating-point leftovers: fall back to the last song that can actually be chosen.
    return next(s for s, w in zip(reversed(candidates), reversed(weights)) if w > 0)


class ShuffleCycle:
    """Weighted shuffle that plays every eligible song once before any repeats.

    Weight still decides the order (heavier songs tend to come earlier in each cycle); songs with
    weight 0 are never picked unless nothing else has any weight.
    """

    def __init__(self):
        self._played = set()

    def mark_played(self, song):
        if song is not None:
            self._played.add(id(song))

    def reset(self):
        self._played.clear()

    def choose(self, songs, current, rng=random.random):
        eligible = [s for s in songs if s.weight > 0] or list(songs)
        pool = [s for s in eligible if id(s) not in self._played and s is not current]
        if not pool:  # everything has played: start a new cycle
            self._played.clear()
            pool = [s for s in eligible if s is not current] or eligible
        song = weighted_choice(pool, None, rng)
        self.mark_played(song)
        return song


def next_in_list(songs, current):
    """The song after `current`, wrapping around; the first song if `current` isn't listed."""
    if not songs:
        return None
    try:
        row = next(i for i, s in enumerate(songs) if s is current)
    except StopIteration:
        return songs[0]
    return songs[(row + 1) % len(songs)]


def pick_next(mode: LoopMode, songs, current, manual: bool, rng=random.random, cycle: ShuffleCycle | None = None):
    """What to play after `current` among the visible `songs`.

    manual: the user pressed Next. That always advances (shuffled in shuffle mode, otherwise in
    order), while the end of a track follows the loop mode: repeat, advance, shuffle, or stop (None).
    cycle: if given, shuffle avoids repeats until every song has played.
    """
    def shuffled():
        return cycle.choose(songs, current, rng) if cycle is not None else weighted_choice(songs, current, rng)

    if manual or mode == LoopMode.LIST:
        return shuffled() if mode == LoopMode.SHUFFLE else next_in_list(songs, current)
    if mode == LoopMode.REPEAT_ONE:
        return current if current is not None else next_in_list(songs, None)
    if mode == LoopMode.SHUFFLE:
        return shuffled()
    return None


def shifted(order, selected, delta: int):
    """Move each selected item one step up (delta=-1) or down (+1); blocked items stay put."""
    selected = {id(s) for s in selected}
    result = list(order)
    indices = range(1, len(result)) if delta < 0 else range(len(result) - 2, -1, -1)
    for i in indices:
        j = i + delta
        if id(result[i]) in selected and id(result[j]) not in selected:
            result[i], result[j] = result[j], result[i]
    return result


def moved_to_edge(order, selected, top: bool):
    """Move the selected items to the top or bottom, keeping their relative order."""
    selected = {id(s) for s in selected}
    chosen = [s for s in order if id(s) in selected]
    rest = [s for s in order if id(s) not in selected]
    return chosen + rest if top else rest + chosen
