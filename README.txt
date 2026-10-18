Shellac
=======

A music player built around tags and weighted shuffle.


Installation
---------------

Requires Python 3.10 or newer. From this directory:

    python -m venv .venv
    .venv\Scripts\activate        (Windows; use `source .venv/bin/activate` on macOS/Linux)
    pip install -e .


Usage
--------------

    shellac [files, folders or .slp playlists to open]

or equivalently `python -m shellac`. Shellac can be started from any directory.

Drag audio files, folders or .slp playlists onto the window to add them. Double-click a song to
play it; Ctrl+double-click edits it. Ctrl- and Shift-click select several songs.

Loop modes (L): repeat one, play in order, weighted shuffle, stop after the song. In shuffle, a
song's weight is its relative chance of being picked (0 = never). Next always moves on, even in
repeat-one mode; Previous walks back through what you played.

Filters (Ctrl+F) combine a regular expression on the song name with tag rules: a song passes if
it matches any rule, and a rule matches when all of its tags match (a negated tag must be absent).
Row numbers always refer to the song's position in the whole playlist.

Download from Internet (Ctrl+Alt+D) fetches audio from any site yt-dlp supports, optionally
trims it, and converts it into your song folder. ffmpeg on your PATH is used if present;
otherwise the copy bundled with imageio-ffmpeg is.


Shortcuts
--------------

    Space               Play / pause            Shift+Up / Down       Move selection
    ] or Alt+N          Next song               Alt+Shift+Up / Down   Move to top / bottom
    [ or Alt+B          Previous song           Alt+E                 Edit selected song
    L or Alt+L          Change loop mode        Delete                Remove selected
    Alt+M               Mute                    Ctrl+F                Edit filter
    Alt+A               Add songs               Ctrl+Alt+R            Clear filter
    Alt+Shift+O         Add folder              Alt+P                 Select by name/number
    Alt+O / Alt+S       Load / save playlist    Esc                   Deselect


Development
--------------

    pip install -e ".[dev]"
    pytest
    ruff check shellac tests

To build a standalone Windows executable (output in dist/Shellac/Shellac.exe):

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
- the song directory (songdir) where downloaded songs are saved and file dialogs open,
- the download directory (downloaddir) for temporary download files and kept originals,
- and the option "folders" which specifies extra folders in the file dialog sidebar: one can add paths separated with ';'.

It is not recommended to alter other options in the configuration file.


Playlists
-----------------------

Playlists (.slp) are saved as UTF-8 JSON and always contain the whole playlist, whatever filter
is active. Playlists saved by Shellac 1.x can still be loaded.
