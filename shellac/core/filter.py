"""Playlist filters: a regex on the song name combined with tag rules.

Tag rules are in disjunctive normal form: a song passes if it satisfies *any* rule, and it
satisfies a rule if it matches *all* of that rule's terms. A term either requires a tag or
(negated) forbids it.

Rules can also be written as text, e.g. ``"Miles Davis" AND NOT live OR jazz``: AND binds
tighter than OR, NOT negates one tag, and tags containing spaces or keywords are quoted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_KEYWORDS = {'and': 'AND', '&': 'AND', 'or': 'OR', '|': 'OR', 'not': 'NOT', '!': 'NOT'}
_TOKEN = re.compile(r'\s*(?:"((?:[^"\\]|\\.)*)"|([&|!()])|([^\s"&|!()]+))')


def _quote(tag: str) -> str:
    return '"' + tag.replace('\\', '\\\\').replace('"', '\\"') + '"'


@dataclass(frozen=True)
class TagTerm:
    tag: str
    required: bool = True

    def matches(self, tags) -> bool:
        return (self.tag in tags) == self.required

    def __str__(self):
        return ('' if self.required else 'NOT ') + _quote(self.tag)


def _tokens(text: str):
    """Yield ('TAG', name) or ('AND'|'OR'|'NOT', None)."""
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise ValueError(f'Unexpected character at position {pos + 1}: {text[pos:pos + 10]!r}')
        quoted, symbol, word = match.groups()
        pos = match.end()
        if quoted is not None:
            yield 'TAG', re.sub(r'\\(.)', r'\1', quoted)
        elif symbol and symbol in '()':
            raise ValueError('Parentheses are not supported; write the rule as alternatives joined by OR')
        else:
            keyword = _KEYWORDS.get((symbol or word).lower())
            if keyword:
                yield keyword, None
            else:
                yield 'TAG', word


def parse_rules(text: str) -> tuple[tuple[TagTerm, ...], ...]:
    """Parse a tag query into rules. Raises ValueError with a readable message."""
    rules, terms = [], []
    negate = False
    expect_term = True
    for kind, value in _tokens(text):
        if kind == 'TAG':
            if not expect_term:
                raise ValueError(f'Missing AND/OR before "{value}" (quote tags that contain spaces)')
            terms.append(TagTerm(value, required=not negate))
            negate, expect_term = False, False
        elif kind == 'NOT':
            if not expect_term or negate:
                raise ValueError('NOT must come right before a tag')
            negate = True
        else:  # AND / OR
            if expect_term:
                raise ValueError(f'{kind} must come between two tags')
            if kind == 'OR':
                rules.append(tuple(terms))
                terms = []
            expect_term = True
    if negate or (expect_term and (terms or rules)):
        raise ValueError('The query ends unexpectedly')
    if terms:
        rules.append(tuple(terms))
    return tuple(rules)


@dataclass(frozen=True)
class Filter:
    regex: str = ''
    rules: tuple[tuple[TagTerm, ...], ...] = ()
    # strict: a song must pass both the regex and the tag rules; otherwise either is enough.
    strict: bool = True
    _pattern: re.Pattern | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        # Empty rules match nothing meaningful, so they are dropped rather than matching everything.
        object.__setattr__(self, 'rules', tuple(tuple(r) for r in self.rules if r))
        # Raises re.error for an invalid pattern; callers validate user input before building.
        object.__setattr__(self, '_pattern', re.compile(self.regex) if self.regex else None)

    @property
    def is_empty(self) -> bool:
        return self._pattern is None and not self.rules

    def check(self, song) -> bool:
        has_regex = self._pattern is not None
        has_tags = bool(self.rules)
        if not has_regex and not has_tags:
            return True
        regex_ok = has_regex and self._pattern.search(song.name) is not None
        tags_ok = has_tags and any(all(t.matches(song.tags) for t in rule) for rule in self.rules)
        if not has_regex:
            return tags_ok
        if not has_tags:
            return regex_ok
        return (regex_ok and tags_ok) if self.strict else (regex_ok or tags_ok)

    def describe_rules(self) -> str:
        return ' OR '.join(' AND '.join(str(t) for t in rule) for rule in self.rules)

    def describe(self) -> str:
        parts = []
        if self._pattern is not None:
            parts.append(f'/{self.regex}/')
        if self.rules:
            parts.append(self.describe_rules())
        return (' AND ' if self.strict else ' OR ').join(parts)

    def to_dict(self) -> dict:
        return {'regex': self.regex, 'strict': self.strict,
                'rules': [[[t.tag, t.required] for t in rule] for rule in self.rules]}

    @classmethod
    def from_dict(cls, data) -> Filter:
        """Inverse of to_dict; anything malformed gives an empty filter."""
        try:
            rules = [[TagTerm(str(tag), bool(required)) for tag, required in rule] for rule in data['rules']]
            return cls(str(data.get('regex', '')), rules, bool(data.get('strict', True)))
        except (KeyError, TypeError, ValueError, re.error):
            return cls()
