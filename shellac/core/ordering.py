"""Choosing what plays next, and reordering selections."""
from __future__ import annotations

import random
import weakref
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


def _draw(candidates, weights, rng):
    """One of `candidates`, with probability proportional to its weight (weights >= 0, total > 0)."""
    target = rng() * sum(weights)
    for song, weight in zip(candidates, weights):
        if target < weight:
            return song
        target -= weight
    # Floating-point leftovers: fall back to the last song that can actually be chosen.
    return next(s for s, w in zip(reversed(candidates), reversed(weights)) if w > 0)


def weighted_choice(songs, exclude=None, rng=random.random):
    """Pick a song with probability proportional to its weight, avoiding `exclude` if possible."""
    candidates = [s for s in songs if s is not exclude] or list(songs)
    if not candidates:
        return None
    weights = [max(s.weight, 0) for s in candidates]
    if sum(weights) == 0:
        return unweighted_choice(candidates, None, rng)
    return _draw(candidates, weights, rng)


def unweighted_choice(songs, exclude=None, rng=random.random):
    """Pick a song with uniform probability, avoiding `exclude` if possible; None if there are none."""
    candidates = [s for s in songs if s is not exclude] or list(songs)
    if not candidates:
        return None
    return candidates[int(rng() * len(candidates)) % len(candidates)]


class ShuffleCycle:
    """Weighted shuffle in cycles: a song with weight 3 gets 3 slots per cycle, and each pick takes
    one of the slots still left, uniformly at random.

    - A song is never picked twice in a row while another song has slots left. If only the playing
      song has slots left, a new cycle starts instead (its leftover slots are dropped).
    - Weight 0 means never, unless every song has weight 0: then picks are plain uniform.
    - Manual plays count too: mark_played() uses up one of the song's slots.
    """

    def __init__(self):
        # Keyed by the Song itself (weakly), so a removed song's count can't pass to a new one.
        self._played = weakref.WeakKeyDictionary()

    def plays(self, song) -> int:
        """How many slots `song` has used this cycle."""
        return self._played.get(song, 0)

    def mark_played(self, song):
        if song is not None:
            self._played[song] = self._played.get(song, 0) + 1

    def reset(self):
        self._played.clear()

    def _slots_left(self, songs, current):
        return [0 if s is current else max(s.weight - self._played.get(s, 0), 0) for s in songs]

    def choose(self, songs, current, rng=random.random):
        """Pick the next song and use up one of its slots. None if `songs` is empty."""
        songs = list(songs)
        if not songs:
            return None
        left = self._slots_left(songs, current)
        if not any(left):  # this cycle is used up: start the next one
            self._played.clear()
            left = self._slots_left(songs, current)
        if any(left):
            # Proportional to slots left == uniform over the remaining slots, without listing them.
            song = _draw(songs, left, rng)
        elif any(s.weight > 0 for s in songs):
            song = current  # the playing song is the only one with any weight
        else:
            song = unweighted_choice(songs, current, rng)  # every weight is 0
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
    cycle: if given, shuffle plays each song `weight` times per cycle (see ShuffleCycle). It uses up a slot
    of whatever it picks, so callers must not mark that pick as played again.
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
