from importlib.resources import files

_ROOT = files(__package__)


def asset(name):
    """Absolute path to a bundled file in shellac/assets, independent of the working directory."""
    return str(_ROOT / 'assets' / name)


def style(name):
    return str(_ROOT / 'styles' / name)
