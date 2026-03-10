Arena Watchfolder
=================

Keep your Resolume Arena clips in sync with folders on disk — automatically.

Map a folder to a layer, and every video or image in that folder becomes a clip
in Arena. Add a file, it appears. Remove a file, it disappears. Your effects,
speed settings, cue points, and blend modes are preserved across every sync.


REQUIREMENTS
------------
Resolume Arena 7.x+ with the web server enabled (Preferences > Webserver).


INSTALL
-------
macOS:
  1. Drag "Arena Watchfolder.app" to your Applications folder
  2. Double-click to launch
  3. If macOS blocks it: right-click > Open > Open

Windows:
  1. Run "Arena Watchfolder.exe"
  2. If SmartScreen appears: click "More info" > "Run anyway"


YOUR FIRST SYNC
---------------
  1. Make sure Arena is running with the web server enabled
  2. Open Arena Watchfolder
  3. Click Connect — it should find Arena on 127.0.0.1:8080
  4. Create a set (e.g. "My First Set") using the New button
  5. Click Add Folder Mapping and pick a folder with video files
  6. Set the layer number (which Arena layer to sync to)
  7. Click Sync Now — your files appear as clips in Arena
  8. Tweak the clips in Arena (add effects, change speed, etc.)
  9. Click Save Settings to snapshot your work
 10. Next time you sync, click Restore Settings to bring it all back


INCLUDED DOCUMENTATION
----------------------
  User Manual.pdf     Full user manual with screenshots
  CLI Reference.md    Command-line interface for scripting and LLM control
  CHANGES.txt         Version history
  LICENSE.txt         MIT License


MORE INFO
---------
GitHub: https://github.com/tijnisfijn/Arena_Watchfolder
