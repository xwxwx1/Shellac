"""Formatting and parsing of track times."""
from __future__ import annotations

import math


def format_time(seconds: float | None) -> str:
    """Format seconds as ``mm:ss``, or ``h:mm:ss`` for an hour or more."""
    if seconds is None or seconds < 0 or math.isnan(seconds):
        return '--:--'
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f'{hours}:{minutes:02}:{secs:02}'
    return f'{minutes:02}:{secs:02}'


def parse_time(text: str) -> float | None:
    """Parse ``ss``, ``m:ss`` or ``h:mm:ss`` (seconds may have decimals).

    Blank text means "not given" and returns None; anything malformed raises ValueError.
    """
    text = text.strip()
    if not text:
        return None
    parts = text.split(':')
    if len(parts) > 3 or any(not p.strip() for p in parts):
        raise ValueError(f'Invalid time: {text!r}')
    try:
        seconds = float(parts[-1])
        higher = [int(p) for p in parts[:-1]]
    except ValueError:
        raise ValueError(f'Invalid time: {text!r}') from None
    if seconds < 0 or any(h < 0 for h in higher):
        raise ValueError(f'Invalid time: {text!r}')
    # Below the leading unit, minutes and seconds must stay under 60.
    if higher and seconds >= 60 or len(higher) == 2 and higher[1] >= 60:
        raise ValueError(f'Invalid time: {text!r}')
    total = seconds
    for factor, value in zip((60, 3600), reversed(higher)):
        total += factor * value
    return total
