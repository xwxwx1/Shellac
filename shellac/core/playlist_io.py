"""Reading and writing .slp playlist files.

Current files are UTF-8 JSON. Files from earlier versions (one ``path::...;name::...;tags::...;
weight::...`` line per song) are still read.
"""
from __future__ import annotations

import json
import locale
import os
from dataclasses import dataclass

from .song import parse_tags

FORMAT_ID = 'shellac-playlist'
VERSION = 1


class PlaylistFormatError(ValueError):
    pass


@dataclass
class PlaylistEntry:
    path: str
    name: str | None = None
    tags: tuple[str, ...] = ()
    weight: int = 1


def save(path: str, songs) -> None:
    data = {
        'format': FORMAT_ID,
        'version': VERSION,
        'songs': [{'path': s.path, 'name': s.name, 'tags': list(s.tags), 'weight': s.weight}
                  for s in songs],
    }
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # never leave a half-written playlist behind


def _read_text(path: str) -> str:
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        # Legacy files were written in the system's locale encoding (e.g. GBK).
        return raw.decode(locale.getpreferredencoding(False), errors='replace')


def _resolve(entry_path: str, base_dir: str) -> str:
    entry_path = os.path.expanduser(entry_path)
    return entry_path if os.path.isabs(entry_path) else os.path.join(base_dir, entry_path)


def _int(value, default=1) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def load(path: str) -> list[PlaylistEntry]:
    text = _read_text(path)
    base_dir = os.path.dirname(os.path.abspath(path))
    if text.lstrip().startswith('{'):
        return _load_json(text, base_dir)
    return _load_legacy(text, base_dir)


def _load_json(text: str, base_dir: str) -> list[PlaylistEntry]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise PlaylistFormatError(f'Not a valid playlist: {e}') from None
    if not isinstance(data, dict) or data.get('format') != FORMAT_ID:
        raise PlaylistFormatError('Not a Shellac playlist')
    entries = []
    for item in data.get('songs', []):
        if not isinstance(item, dict) or not item.get('path'):
            continue
        tags = item.get('tags') or []
        entries.append(PlaylistEntry(
            _resolve(str(item['path']), base_dir),
            str(item['name']) if item.get('name') else None,
            tuple(str(t) for t in tags if str(t).strip()),
            _int(item.get('weight')),
        ))
    return entries


def _load_legacy(text: str, base_dir: str) -> list[PlaylistEntry]:
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = {}
        for part in line.split(';'):
            if '::' in part:
                key, value = part.split('::', 1)
                fields[key] = value
        if not fields.get('path'):
            raise PlaylistFormatError(f'Unrecognised playlist line: {line[:80]!r}')
        entries.append(PlaylistEntry(
            _resolve(fields['path'], base_dir),
            fields.get('name') or None,
            tuple(parse_tags(fields.get('tags', ''))),
            _int(fields.get('weight')),
        ))
    return entries
