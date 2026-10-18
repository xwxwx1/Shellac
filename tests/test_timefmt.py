import pytest

from shellac.core.timefmt import format_time, parse_time


@pytest.mark.parametrize('seconds, text', [
    (0, '00:00'), (5.4, '00:05'), (65, '01:05'), (3599.6, '1:00:00'), (3725, '1:02:05'),
    (None, '--:--'), (-1, '--:--'), (float('nan'), '--:--'),
])
def test_format_time(seconds, text):
    assert format_time(seconds) == text


@pytest.mark.parametrize('text, seconds', [
    ('', None), ('  ', None), ('0', 0), ('0:00', 0), ('1:05', 65), ('1:02:05', 3725),
    ('90', 90), ('1:05.5', 65.5), ('120:00', 7200),
])
def test_parse_time(text, seconds):
    assert parse_time(text) == seconds


@pytest.mark.parametrize('text', ['a', '1:', ':5', '1:60', '1:2:3:4', '1:60:00', '-1', '1:-5'])
def test_parse_time_rejects(text):
    with pytest.raises(ValueError):
        parse_time(text)
