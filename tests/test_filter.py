import re

import pytest

from shellac.core.filter import Filter, TagTerm, parse_rules


def test_empty_filter_passes_everything(make_song):
    f = Filter()
    assert f.is_empty and f.check(make_song('x'))


def test_rules_are_or_of_ands(make_song):
    f = Filter(rules=[[TagTerm('rock'), TagTerm('live', required=False)], [TagTerm('jazz')]])
    assert f.check(make_song('a', ['rock']))
    assert not f.check(make_song('b', ['rock', 'live']))
    assert f.check(make_song('c', ['jazz', 'live']))
    assert not f.check(make_song('d', ['pop']))


def test_empty_rules_are_ignored(make_song):
    f = Filter(rules=[[], [TagTerm('rock')]])
    assert f.rules == ((TagTerm('rock'),),)
    assert not f.check(make_song('x'))


def test_regex_and_strictness(make_song):
    song = make_song('Hello World', ['pop'])
    rock = [[TagTerm('rock')]]
    assert Filter(regex='World').check(song)
    assert not Filter(regex='^World').check(song)
    assert not Filter(regex='World', rules=rock, strict=True).check(song)
    assert Filter(regex='World', rules=rock, strict=False).check(song)


def test_invalid_regex_raises():
    with pytest.raises(re.error):
        Filter(regex='(')


def test_describe():
    f = Filter('a', [[TagTerm('x'), TagTerm('y', False)], [TagTerm('z')]])
    assert f.describe_rules() == '"x" AND NOT "y" OR "z"'
    assert f.describe() == '/a/ AND "x" AND NOT "y" OR "z"'


@pytest.mark.parametrize('text, expected', [
    ('', ()),
    ('rock', ((TagTerm('rock'),),)),
    ('rock AND NOT live OR jazz', ((TagTerm('rock'), TagTerm('live', False)), (TagTerm('jazz'),))),
    ('"Miles Davis" & !"live set" | jazz', ((TagTerm('Miles Davis'), TagTerm('live set', False)),
                                            (TagTerm('jazz'),))),
    ('rock and not live', ((TagTerm('rock'), TagTerm('live', False)),)),
    (r'"say \"hi\""', ((TagTerm('say "hi"'),),)),
    ('"and"', ((TagTerm('and'),),)),
])
def test_parse_rules(text, expected):
    assert parse_rules(text) == expected


@pytest.mark.parametrize('text', ['rock jazz', 'AND rock', 'rock OR', 'NOT', 'NOT NOT a', 'a NOT b',
                                  '(a OR b)', '"unclosed'])
def test_parse_rules_rejects(text):
    with pytest.raises(ValueError):
        parse_rules(text)


def test_describe_parses_back():
    f = Filter(rules=[[TagTerm('a "b"'), TagTerm('or', False)], [TagTerm(r'c\d')]])
    assert parse_rules(f.describe_rules()) == f.rules


def test_dict_roundtrip():
    f = Filter('x+', [[TagTerm('a'), TagTerm('b', False)]], strict=False)
    assert Filter.from_dict(f.to_dict()) == f
    assert Filter.from_dict({'regex': '('}).is_empty
    assert Filter.from_dict(None).is_empty
