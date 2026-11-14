from shellac.core.history import History


def test_back_and_forward():
    h = History()
    for s in 'abc':
        h.push(s)
    assert h.back() == 'b' and h.back() == 'a' and h.back() is None
    assert h.forward() == 'b' and h.current == 'b'
    h.push('d')  # choosing a new song drops the forward history
    assert h.forward() is None
    assert h.back() == 'b' and h.back() == 'a'


def test_repeated_song_is_recorded_once():
    h = History()
    h.push('a')
    h.push('a')
    assert len(h) == 1


def test_remove_keeps_cursor_and_collapses_repeats():
    h = History()
    for s in 'abacd':
        h.push(s)
    h.back()  # cursor on 'c'
    h.remove(['b'])
    assert h.current == 'c'
    assert h.back() == 'a' and h.back() is None  # a, b, a collapsed to a single a


def test_remove_current_falls_back_to_previous():
    h = History()
    for s in 'abc':
        h.push(s)
    h.remove(['c'])
    assert h.current == 'b'
    h.remove(['a', 'b'])
    assert h.current is None and len(h) == 0
