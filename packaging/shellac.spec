# Build with:  pyinstaller packaging/shellac.spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
pkg = root / 'shellac'

a = Analysis(
    [str(Path(SPECPATH) / 'launcher.py')],
    pathex=[str(root)],
    datas=[
        (str(pkg / 'assets'), 'shellac/assets'),
        (str(pkg / 'styles'), 'shellac/styles'),
        (str(pkg / 'default_config.txt'), 'shellac'),
        *collect_data_files('qt_material'),
    ],
    hiddenimports=['you_get.extractors'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='Shellac',
    icon=str(pkg / 'assets' / 'Shellac.ico'),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name='Shellac')
