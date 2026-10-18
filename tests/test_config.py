from pathlib import Path

import pytest

from shellac import config


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_DIR', tmp_path / 'cfg')
    monkeypatch.setattr(config, 'CONFIG_PATH', tmp_path / 'cfg' / 'config.txt')
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_first_run_uses_defaults(isolated):
    cfg = config.load_config()
    assert cfg['songdir'] == (isolated / 'data' / 'songs').resolve().as_posix() + '/'
    assert Path(cfg['songdir']).is_dir()
    assert config.DownloadSettings.parse(cfg['downloadconfig']) == config.DownloadSettings()


def test_legacy_config_is_migrated(isolated):
    (isolated / 'config.txt').write_text(
        'songdir:./songs/\nloopmode:1\n'
        'downloadconfig:url:;tags:x;ftype:flac;yargs:--no-caption;fiargs:;foargs:-ar 44100;weight:3;deletevid:False\n',
        encoding='utf-8')
    cfg = config.load_config()
    assert cfg['songdir'] == (isolated / 'songs').resolve().as_posix() + '/'
    assert config.loop_mode(cfg) == 1
    settings = config.DownloadSettings.parse(cfg['downloadconfig'])
    assert settings == config.DownloadSettings(tags='x', format='flac', ffmpeg_args='-ar 44100',
                                               weight=3, keep_source=True)


def test_edit_and_roundtrip(isolated):
    config.load_config()
    s = config.DownloadSettings(tags='a;b:c', ytdlp_args='--cookies "x;y"')
    config.edit_config('downloadconfig', s.dump())
    config.edit_config('folders', 'C:/a; ;D:/b')
    cfg = config.load_config()
    assert config.DownloadSettings.parse(cfg['downloadconfig']) == s
    assert config.sidebar_folders(cfg) == ['C:/a', 'D:/b']
