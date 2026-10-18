import re

import pytest

from shellac.core.filter import Filter, TagTerm


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
