Shellac
=======

A music player built around tags and a weighted shuffle, featuring management tools for downloading, indexing and playing
a local music library. Like a shelf of shellac discs, it remains yours even without subscription, T&Cs, or connectivity
(my high-school Wi-Fi being admittedly the motivation behind development).

Originally a one-file amalgamation I wrote in high school, it is now refactored and updated.

Interaction design and iconography courtesy of Martin (Zhenxiao) Tian,
my former classmate and long-time friend, now studying at ArtCenter College of Design.

Installation
---------------

Requires Python 3.10 or newer. From this directory (Only tested on Windows, but it is built atop platform-agnostic PyQt6):

    python -m venv .venv
    .venv\Scripts\activate
    pip install -e .


Usage
--------------

    shellac [files, folders or .slp playlists to open]

or equivalently `python -m shellac`. Shellac can be started from any directory.

Playlists are designed in the pattern of file explorers (but with ordering). Drag audio files, 
folders or .slp playlists onto the window to add them, or between rows to insert them there. 
Drag rows to reorder. Double-click a song to play it or Ctrl+double-click to edit
it. Name, Tags and Weight can also be edited in place (F2, or clicking a selected cell). Songs added
without tags take the file's artist as their first tag (this can be turned off in Settings).
The old version took the innermost folder because that was how I was organising my files, but it's
abandoned for a more sensible approach.

Playlists (.slp) are saved as UTF-8 JSON and always contain the whole playlist, whatever filter
is active. Playlists were slightly expanded in the refactor, but those saved by Shellac 1.x can still be loaded.
They are fairly self-explanatory and you can edit them manually or with a JSON script, but note that the parser
I wrote here is rather crude and may throw enigmatic errors if you mess it up.

Loop modes (L): repeat one, play in order, weighted shuffle, stop after the song. In shuffle, a
song's weight is its relative chance of being picked (0 = never); with Play › Shuffle Without Repeats,
shuffle runs in cycles where each song plays as many times as its weight (a weight-3 song plays 3 times
per cycle, never twice in a row). Next (\]) plays the next song to play (or next in playlist 
if you're on repeat); Previous (\[) backtracks through your previously played songs, where the retraced path
can be walked back through with Next.

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
the panel, can be cancelled, and failed ones can be retried. Note that as yt-dlp has poor support
for the site Bilibili, it is handled separately. As media hosting websites often change their format,
unfortunately this may not be reliable - try updating yt-dlp as a first step for other sites, at least.

Cookies can come from a browser or from a cookies.txt file (Netscape). Shellac does not store your
cookies, and it only remembers them through the path you provide.

ffmpeg on your PATH is used (for processing the downloads) if present; otherwise the copy 
bundled with imageio-ffmpeg is.

Shellac remembers the playlist, the song and position, volume, filter, search, queue and window
layout between runs. On Windows, media keys work even when Shellac
is in the background, and a tray icon offers play controls. All of these can be changed under
File › Settings.


Shortcuts
--------------

    Space               Play / pause            Shift+Up / Down       Move selection
    \] or Alt+N         Next song               Alt+Shift+Up / Down   Move to top / bottom
    \[ or Alt+B         Previous song           Alt+E                 Edit selected song
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

The configuration file, config.txt, is stored in your user config directory:
- Windows: %APPDATA%\Shellac\config.txt
- macOS:   ~/Library/Application Support/Shellac/config.txt
- Linux:   ~/.config/Shellac/config.txt 
(latter 2 by convention, but untested)

Of these options, one might find it useful to alter:
- the song directory (songdir) where downloaded songs are saved and file dialogs open,
- the download directory (downloaddir) for temporary download files and kept originals,
- and the option "folders" which specifies extra folders in the file dialog sidebar for quick access: one can add paths separated with ';'.
- Various toggles (mostly opt-outs for things where I wasn't really sure about adding)

I would advise that you edit them through Settings (Ctrl+,).


Known Problems and Future Plans
-----------------------

If you'd like to improve Shellac, please do so! As for now, I am mostly preoccupied with coursework, so these would have to be for the future:

- Wonky selection logic when mixing keyboard and mouse use
- Cluttery UI and thin margins on some dialog boxes
- Adding tags and changing weights are still inconvenient to do in bulk: I am planning on using the leftmost column for a more sophisticated selection mechanism then having bulk editing on that, and perhaps also adding per-tag management dialogs
- Grouping songs together: often people upload them in parts, and I believe an extra layer of granularity could help with layered structures like albums of songs and piece of movements where streaming as a whole and in parts both make sense
