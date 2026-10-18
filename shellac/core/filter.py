"""Playlist filters: a regex on the song name combined with tag rules.

Tag rules are in disjunctive normal form: a song passes if it satisfies *any* rule, and it
satisfies a rule if it matches *all* of that rule's terms. A term either requires a tag or
(negated) forbids it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TagTerm:
    tag: str
    required: bool = True

    def matches(self, tags) -> bool:
        return (self.tag in tags) == self.required

    def __str__(self):
        return ('' if self.required else 'NOT ') + f'"{self.tag}"'


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
