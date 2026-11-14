"""What Shellac remembers between runs: the playlist, what was playing, volume, filter, queue, layout."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields

from .playlist_io import PlaylistEntry

VERSION = 1


@dataclass
class Session:
    songs: list[dict] = field(default_factory=list)  # {path, name, tags, weight}
    current: str | None = None  # path of the song that was loaded
    position: float = 0.0
    volume: int = 100
    muted: bool = False
    filter: dict | None = None
    search: str = ''
    tags: list[str] = field(default_factory=list)  # tags selected in the tag browser
    queue: list[str] = field(default_factory=list)  # paths
    sort_column: int = -1
    sort_order: int = 0
    window_geometry: str = ''  # base64 from QWidget.saveGeometry()
    window_state: str = ''  # base64 from QMainWindow.saveState()
    header_state: str = ''

    @staticmethod
    def song_dict(song) -> dict:
        return {'path': song.path, 'name': song.name, 'tags': list(song.tags), 'weight': song.weight}

    def entries(self) -> list[PlaylistEntry]:
        result = []
        for item in self.songs:
            if isinstance(item, dict) and item.get('path'):
                weight = item.get('weight', 1)
                result.append(PlaylistEntry(str(item['path']), item.get('name') or None,
                                            tuple(str(t) for t in item.get('tags') or ()),
                                            weight if isinstance(weight, int) and weight >= 0 else 1))
        return result

    def save(self, path) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f'{path}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'version': VERSION, **asdict(self)}, f, ensure_ascii=False)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path) -> Session:
        """The saved session, or an empty one if there is none or it can't be read."""
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        defaults = cls()
        values = {}
        for f in fields(cls):
            value = data.get(f.name, getattr(defaults, f.name))
            default = getattr(defaults, f.name)
            # Keep only values of the expected type; a hand-edited file shouldn't crash startup.
            if default is None or isinstance(value, type(default)) or (
                    isinstance(default, float) and isinstance(value, int)):
                values[f.name] = value
        return cls(**values)
