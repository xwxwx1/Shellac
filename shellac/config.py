import os
import shutil
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


def read_text_lines(path):
    return _read_lines(path)
