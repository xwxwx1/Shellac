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

Drag audio files, folders or .slp playlists onto the window to add them, or between rows to
insert them there. Drag rows to reorder. Double-click a song to play it; Ctrl+double-click edits
it. Name, Tags and Weight can also be edited in place (F2, or click a selected cell). Songs added
without tags take the file's artist as their first tag (this can be turned off in Settings).

Loop modes (L): repeat one, play in order, weighted shuffle, stop after the song. In shuffle, a
song's weight is its relative chance of being picked (0 = never); Play › Shuffle Without Repeats
plays everything once before repeating. Next always moves on, even in repeat-one mode; Previous
walks back through what you played.

Up Next: right-click songs › Play Next or Add to Up Next. Queued songs play before the loop mode
picks anything; the Up Next panel reorders or removes them.

Finding songs: the search box matches names, tags and albums; the Tags panel shows every tag
with its count, and ticked tags must all be present. Filters (Ctrl+F) combine a regular
expression on the song name with tag rules, typed as text (e.g. "Miles Davis" AND NOT live OR
jazz) or built with the buttons. Click a column header to sort; a third click (or View ›
Playlist Order) returns to the playlist order, which is what Move Up/Down and dragging change.
Row numbers always refer to the song's position in the whole playlist.

Missing files are shown in grey italics and skipped during playback. Right-click › Locate File…
points a song at its new location; File › Remove Missing Songs cleans up.

Downloads (Ctrl+Alt+D opens the panel, next to Up Next) fetch audio from bilibili, YouTube and
the other sites yt-dlp supports, optionally trim it, and convert it into your song folder. Leave
Name blank to use the video's title; with no tags, the uploader becomes the artist tag. Look up
checks a link (and your cookies) before downloading. Running downloads show their progress in
the panel, can be cancelled, and failed ones can be retried.

bilibili links (bilibili.com/video/BV…, av…, b23.tv short links, ?p= for multi-part videos)
use bilibili's own API rather than yt-dlp, because bilibili often shows yt-dlp a captcha page.
Without an account you get the standard audio streams, up to 192 kbps; the 480p limit only
affects video, which Shellac discards. Cookies from a logged-in browser add Hi-Res lossless
audio (with a bilibili VIP membership) and members-only videos; Look up shows "logged in as …"
when they work.

Cookies can come from a browser or from a cookies.txt file (Netscape format, as exported by
browser extensions such as "Get cookies.txt LOCALLY"). Firefox works directly. Chrome, Edge and
other Chromium browsers on Windows now encrypt their cookies so other programs cannot read them,
so with those, export a cookies.txt instead. Shellac remembers only which source you chose,
never the cookies themselves.

ffmpeg on your PATH is used if present; otherwise the copy bundled with imageio-ffmpeg is.

Shellac remembers the playlist, the song and position, volume, filter, search, queue and window
layout between runs. Only one window runs at a time: opening files with Shellac while it is
already running adds them to the existing window. On Windows, media keys work even when Shellac
is in the background, and a tray icon offers play controls. All of these can be changed under
File › Settings.


Shortcuts
--------------

    Space               Play / pause            Shift+Up / Down       Move selection
    ] or Alt+N          Next song               Alt+Shift+Up / Down   Move to top / bottom
    [ or Alt+B          Previous song           Alt+E                 Edit selected song
    L or Alt+L          Change loop mode        F2                    Edit cell in place
    Alt+M               Mute                    Delete                Remove selected
    Ctrl+Enter          Play next               Ctrl+K                Search
    Alt+Q               Add to Up Next          Ctrl+F                Edit filter
    Ctrl+J              Show playing song       Ctrl+Alt+R            Clear filter, search, tags
    Alt+A               Add songs               Alt+P                 Select by name/number
    Alt+Shift+O         Add folder              Esc                   Deselect
    Alt+O / Alt+S       Load / save playlist    Ctrl+,                Settings
    Media keys          Play/pause, next, previous, stop


Development
--------------

    pip install -e ".[dev]"
    pytest
    ruff check shellac tests

Set SHELLAC_NETWORK_TESTS=1 to also run a live bilibili download test (optionally choosing the
video with SHELLAC_BILIBILI_URL).

To time filtering, searching and sorting on a large, densely tagged playlist:

    python benchmarks/bench_library.py --songs 2000

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

Everything else is easiest to change in File › Settings. The session (playlist, position, queue,
layout) is kept next to config.txt in session.json.


Playlists
-----------------------

Playlists (.slp) are saved as UTF-8 JSON and always contain the whole playlist, whatever filter
is active. Playlists saved by Shellac 1.x can still be loaded.
