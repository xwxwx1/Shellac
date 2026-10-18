import json
import os
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from platformdirs import user_config_path, user_data_path

from .resources import _ROOT

APP_NAME = 'Shellac'
CONFIG_DIR = user_config_path(APP_NAME, appauthor=False, roaming=True)
DATA_DIR = user_data_path(APP_NAME, appauthor=False, roaming=True)
CONFIG_PATH = CONFIG_DIR / 'config.txt'

# Keys whose values are directories; relative values ("./songs/") resolve against DATA_DIR.
_DIR_KEYS = ('songdir', 'downloaddir')


def _read_lines(path):
    """Read a text file as UTF-8, falling back to the system encoding for files written by older versions."""
    try:
        return Path(path).read_text(encoding='utf-8').splitlines()
    except UnicodeDecodeError:
        return Path(path).read_text().splitlines()


def _parse(lines):
    config = {}
    for line in lines:
        if ':' in line:
            key, value = line.split(':', 1)
            config[key] = value
    return config


def _write(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(''.join(f'{k}:{v}\n' for k, v in config.items()), encoding='utf-8')


def _absolutize(value, base):
    if not value:
        return value
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve().as_posix().rstrip('/') + '/'


def ensure_config():
    """Create the user config on first run, migrating a legacy ./config.txt if one is found."""
    if CONFIG_PATH.exists():
        return
    legacy = Path.cwd() / 'config.txt'
    if legacy.exists():
        config = _parse(_read_lines(legacy))
        # Legacy relative paths meant "relative to where Shellac was launched"; pin them there.
        for key in _DIR_KEYS:
            config[key] = _absolutize(config.get(key, ''), Path.cwd())
        _write(config)
    else:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(_ROOT / 'default_config.txt'), CONFIG_PATH)


def load_config():
    ensure_config()
    # Defaults fill in keys missing from older or hand-edited configs.
    defaults = _parse(_read_lines(_ROOT / 'default_config.txt'))
    config = {**defaults, **_parse(_read_lines(CONFIG_PATH))}
    for key in _DIR_KEYS:
        config[key] = _absolutize(config[key] or defaults[key], DATA_DIR)
        os.makedirs(config[key], exist_ok=True)
    return config


def edit_config(key, value):
    config = _parse(_read_lines(CONFIG_PATH))
    config[key] = value
    _write(config)


def sidebar_folders(config):
    """Extra folders for the file dialog sidebar, from the ';'-separated `folders` setting."""
    return [f for f in (p.strip() for p in config.get('folders', '').split(';')) if f]


def session_path():
    return CONFIG_DIR / 'session.json'


def flag(config, key):
    """A True/False setting."""
    return str(config.get(key, '')).strip().lower() in ('true', '1', 'yes', 'on')


def loop_mode(config):
    try:
        return int(config.get('loopmode', 2)) % 4
    except ValueError:
        return 2


@dataclass
class DownloadSettings:
    """Remembered defaults for the download dialog."""
    tags: str = ''
    format: str = 'mp3'
    ytdlp_args: str = ''
    ffmpeg_args: str = ''
    weight: int = 1
    keep_source: bool = False

    @classmethod
    def parse(cls, value):
        value = (value or '').strip()
        if value.startswith('{'):
            try:
                data = json.loads(value)
            except json.JSONDecodeError:
                return cls()
            known = {f.name for f in fields(cls)}
            settings = cls(**{k: v for k, v in data.items() if k in known})
        else:
            settings = cls._parse_legacy(value)
        try:
            settings.weight = max(int(settings.weight), 0)
        except (TypeError, ValueError):
            settings.weight = 1
        return settings

    @classmethod
    def _parse_legacy(cls, value):
        # Pre-2.0 format: "url:;tags:;ftype:mp3;yargs:...;fiargs:;foargs:;weight:1;deletevid:True".
        # yargs were you-get options, which yt-dlp doesn't understand, so they are dropped.
        old = dict(part.split(':', 1) for part in value.split(';') if ':' in part)
        return cls(
            tags=old.get('tags', ''),
            format={'aac': 'm4a'}.get(old.get('ftype'), old.get('ftype') or 'mp3'),
            ffmpeg_args=old.get('foargs', ''),
            weight=old.get('weight', 1),
            keep_source=old.get('deletevid', 'True') != 'True',
        )

    def dump(self):
        return json.dumps(asdict(self), ensure_ascii=False)
