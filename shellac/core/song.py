"""The Song record and helpers for audio files on disk."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

AUDIO_EXTENSIONS = ('mp3', 'flac', 'wav', 'ogg', 'opus', 'm4a', 'aac', 'wma')


def normalize_path(path: str) -> str:
    """Absolute path with forward slashes, the form Shellac stores everywhere."""
    return os.path.abspath(os.path.expanduser(path)).replace('\\', '/')


def path_key(path: str) -> str:
    """Identity of a file: two paths with the same key are the same song."""
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def is_audio_file(path: str) -> bool:
    return os.path.splitext(path)[1][1:].lower() in AUDIO_EXTENSIONS


def parse_tags(text: str) -> list[str]:
    """Split comma-separated tags, dropping blanks and duplicates but keeping order."""
    tags = []
    for tag in text.split(','):
        tag = tag.strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


# eq=False: songs compare by identity, so `in` and list.remove never confuse two entries.
@dataclass(eq=False)
class Song:
    path: str
    name: str
    tags: list[str] = field(default_factory=list)
    weight: int = 1
    duration: float | None = None

    def __post_init__(self):
        self.path = normalize_path(self.path)

    @property
    def key(self) -> str:
        return path_key(self.path)

    @property
    def artist(self) -> str:
        """By convention the first tag is the artist."""
        return self.tags[0] if self.tags else '/'

    @property
    def exists(self) -> bool:
        return os.path.isfile(self.path)


def read_metadata(path: str) -> tuple[str | None, float | None]:
    """(title, duration in seconds) from the file's tags; (None, None) if unreadable."""
    import tinytag

    try:
        tag = tinytag.TinyTag.get(path)
    except Exception:  # noqa: BLE001 - tinytag raises many error types for missing/corrupt files
        return None, None
    return (tag.title or None), tag.duration


def default_name(path: str, title: str | None = None) -> str:
    return title or os.path.splitext(os.path.basename(path))[0]


def song_from_file(path: str, name: str | None = None, tags=(), weight: int = 1) -> Song:
    """Build a Song, reading duration (and a default name) from the file. Safe off the GUI thread."""
    title, duration = read_metadata(path)
    return Song(path, name or default_name(path, title), list(tags), weight, duration)
