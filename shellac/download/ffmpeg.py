"""Locating and running ffmpeg."""
from __future__ import annotations

import functools
import shutil
import subprocess
import sys

# Output format -> (file extension, encoder arguments).
FORMATS = {
    'mp3': ('mp3', ['-c:a', 'libmp3lame', '-q:a', '2']),
    'flac': ('flac', ['-c:a', 'flac']),
    'wav': ('wav', ['-c:a', 'pcm_s16le']),
    'ogg': ('ogg', ['-c:a', 'libvorbis', '-q:a', '5']),
    'opus': ('opus', ['-c:a', 'libopus', '-b:a', '160k']),
    # AAC goes in an .m4a container: raw .aac streams carry no duration or tags.
    'm4a': ('m4a', ['-c:a', 'aac', '-b:a', '192k']),
    'alac': ('m4a', ['-c:a', 'alac']),
    'wma': ('wma', ['-c:a', 'wmav2', '-b:a', '192k']),
}

# Keep ffmpeg from flashing a console window when Shellac runs without one.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0


@functools.cache
def ffmpeg_exe() -> str:
    """ffmpeg on PATH if installed, otherwise the binary bundled with imageio-ffmpeg."""
    found = shutil.which('ffmpeg')
    if found:
        return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def conversion_command(source: str, target: str, fmt: str, start: float | None = None,
                       end: float | None = None, extra_args=()) -> list[str]:
    cmd = [ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y']
    if start is not None:
        cmd += ['-ss', f'{start:.3f}']
    if end is not None:
        cmd += ['-to', f'{end:.3f}']
    cmd += ['-i', source, '-vn', '-map_metadata', '0', *FORMATS[fmt][1], *extra_args, target]
    return cmd


def popen(cmd: list[str]) -> subprocess.Popen:
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            creationflags=_NO_WINDOW)
