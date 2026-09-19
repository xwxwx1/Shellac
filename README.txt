Installation
---------------

Requires Python 3.10 or newer. From this directory:

    python -m venv .venv
    .venv\Scripts\activate        (Windows; use `source .venv/bin/activate` on macOS/Linux)
    pip install -e .


Usage
--------------

    shellac

or equivalently `python -m shellac`. Shellac can be started from any directory.

To build a standalone Windows executable (output in dist/Shellac/Shellac.exe):

    pip install -e ".[dev]"
    pyinstaller packaging/shellac.spec


Configuration
-----------------------

The configuration file, config.txt, lives in your user config directory:
- Windows: %APPDATA%\Shellac\config.txt
- macOS:   ~/Library/Application Support/Shellac/config.txt
- Linux:   ~/.config/Shellac/config.txt

It is created on first launch. If a config.txt from an older version is found in the directory
Shellac is launched from, it is migrated automatically. Relative directories are resolved
against the Shellac data directory (the same folder as the config on Windows and macOS).

Of these options, one might find it useful to alter:
- the song directory (songdir) where songs are automatically stored and looked for,
- the download directory (downloaddir) storing temporary download files,
- and the option "folders" which specifies the folders appearing in the file dialog within the program: one can add paths separated with ';'.

It is not recommended to alter other options in the configuration file.

Note: the `keyboard` dependency needs root on Linux for modifier-key shortcuts (shift-click, ctrl-double-click).
This will be replaced in a later version.
