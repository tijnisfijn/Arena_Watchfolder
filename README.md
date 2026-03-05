# Arena Watchfolder

![Arena Watchfolder](banner.jpg)

Sync local folders of media files to layers in [Resolume Arena](https://resolume.com/) — automatically.

Drop videos and images into a folder, and they appear as clips in Arena. Add or remove files, and the layer updates to match. Your clip effects, speed settings, cue points, and blend modes are preserved across syncs.

## What can you do with it?

Here are some real-world examples:

- **Gig prep made easy** — Organize your media into folders per event ("Thursday Night", "Friday Night"), map each folder to a layer in Arena, and switch between them with one click. All your clip tweaks come back automatically.
- **Live media updates** — Drop a new video into your mapped folder mid-show and it appears in Arena within seconds (watch mode). Remove a file and the clip disappears from the layer.
- **Effect presets across syncs** — Spend time dialing in Blur, Color Balance, speed, and cue points on your clips. Save a snapshot. Next time you sync that folder, restore the snapshot and every effect parameter is back exactly where you left it.
- **Multi-layer setups** — Map different folders to different layers in a single set: backgrounds on layer 1, overlays on layer 2, text on layer 3. Sync them all at once.
- **Quick A/B comparison** — Create two sets with slightly different media or folder structures, switch between them to compare how different clips look in your composition.
- **Collaborative workflows** — Share a folder on Dropbox or a network drive, and everyone on the team can add media that syncs to Arena automatically.

## Features

- **Smart sync** — only adds/removes changed clips; existing effects and settings are never touched
- **Sets & profiles** — named configurations (e.g. "Thursday Night", "Friday Night") with their own folder-to-layer mappings
- **Clip memory** — snapshot and restore all clip settings including effects with full parameter values, transport, cue points, and more
- **WebSocket + REST** — effects are restored with precise parameter-by-ID updates via WebSocket, with REST as a reliable fallback
- **Multi-layer mapping** — sync multiple folders to different layers in a single set
- **Editable mappings** — change the folder path or layer number of any mapping after creating it
- **Watch mode** — continuously monitor folders and re-sync on file changes
- **Web UI** — browser-based interface with real-time log streaming and built-in help
- **Desktop app** — native window via pywebview (optional)
- **Batch loading** — loads multiple clips in a single API call for faster sync
- **Auto-expand** — grows the composition columns if the folder has more files than slots
- **Config persistence** — sets, mappings, and snapshots saved to disk across restarts
- **Tooltips & help** — hover over any button for a quick explanation, or open the built-in help panel for a full guide

### What gets saved and restored

When you snapshot a layer, the following clip properties are captured and can be restored:

| Category | Properties |
|----------|-----------|
| **Effects** | All video effects (Blur, Color Balance, etc.) with full parameter values |
| **Transform** | Position, scale, rotation, anchor point |
| **Transport** | Speed, direction, play mode (autopilot), beat loop, duration |
| **Cue points** | In/out points on the timeline |
| **Video** | Opacity, resize mode, color channels (R/G/B/A) |
| **Blend & trigger** | Trigger style, transport type, target, fader start, beat snap |
| **Transition** | Transition type and duration |
| **Dashboard** | Dashboard knob assignments |

> **Note:** Automation/keyframes and individual cue point markers (colored diamonds) are Arena UI features not exposed by the REST API — these cannot be saved or restored.

### Supported formats

**Video:** `.mov` `.mp4` `.avi` `.wmv` `.mkv` `.webm` `.m4v` `.flv` `.mpg` `.mpeg` `.3gp` `.ogv` `.ts` `.mxf` `.dxv` `.hap`
**Image:** `.png` `.jpg` `.jpeg` `.gif` `.bmp` `.tiff` `.tif` `.tga` `.webp` `.exr` `.hdr` `.psd`

## Quick Start

> **Not familiar with Python or the terminal?** No worries — paste these instructions into any AI assistant (like ChatGPT, Claude, or Copilot) and ask it to walk you through the setup step by step. It'll get you up and running in no time. You can also paste any error messages you encounter and the AI will help you fix them.

### Requirements

- **Python 3.10+** — [Download here](https://www.python.org/downloads/) if you don't have it
- **Resolume Arena 7.x** with the webserver enabled (Preferences > Webserver)

### Installation

**1. Download the project**

```bash
git clone https://github.com/tijnisfijn/Arena_Watchfolder.git
cd Arena_Watchfolder
```

Or click the green **Code** button on GitHub and select **Download ZIP**, then extract it.

**2. Set up the environment**

```bash
python3 -m venv .venv
source .venv/bin/activate    # macOS / Linux
# .venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

**3. Run it**

```bash
# Web UI (recommended)
python watchfolder.py --ui

# Or as a desktop app (native window)
pip install pywebview pystray Pillow
python watchfolder.py --desktop
```

The web UI opens at `http://127.0.0.1:5000`. If port 5000 is taken (common on macOS due to AirPlay), use `--ui-port 5050`.

> **Tip:** If anything goes wrong during installation, copy the error message and paste it into an AI assistant — it can usually diagnose and fix the problem in seconds.

### Step-by-step: Your first sync

1. Make sure Resolume Arena is running with the webserver enabled (Preferences > Webserver)
2. Start the Watchfolder app (`python watchfolder.py --ui`)
3. Click **Connect** in the top bar — it should find Arena on `127.0.0.1:8080`
4. Create a new set (e.g. "My First Set") using the **New** button
5. Click **Add Folder Mapping** and pick a folder with some video files
6. Set the layer number (which Arena layer to sync to)
7. Click **Sync Now** — your files appear as clips in Arena!
8. Make some changes to the clips in Arena (add effects, change speed, etc.)
9. Click **Save Settings** to snapshot everything
10. Next time you sync, click **Restore Settings** to bring it all back

## Usage

### Web UI

```bash
python watchfolder.py --ui --ui-port 5050
```

Open `http://127.0.0.1:5050` in your browser. From there you can:

1. **Connect** to Arena (set host/port if not default)
2. **Create sets** — e.g. "Thursday Night", "Friday Night"
3. **Add mappings** — assign folders to layers within each set
4. **Edit mappings** — click the pencil icon to change folder path or layer number
5. **Sync / Watch** — one-shot sync or continuous watch per mapping
6. **Snapshot / Restore** — save and recall clip settings (effects, speed, blend modes, cue points)
7. **Switch sets** — current settings are auto-saved, new set is synced and restored

Log output streams in real time at the bottom of the page. Hover over any button for a tooltip explaining what it does, or click the **?** button for the full built-in help guide.

### Desktop App

```bash
pip install pywebview pystray Pillow
python watchfolder.py --desktop
```

Opens the same UI in a native window instead of a browser tab. On **Windows/Linux**, closing the window minimizes to the system tray. On **macOS**, use the Quit button in the UI to exit (system tray requires the main thread which is already used by the native window).

### CLI

**One-shot sync:**

```bash
python watchfolder.py --folder ~/Videos/MySet --layer 2
```

**Watch mode (continuous):**

```bash
python watchfolder.py --folder ~/Videos/MySet --layer 2 --watch
```

**Custom Arena host/port:**

```bash
python watchfolder.py --folder ~/Videos/MySet --layer 3 --host 192.168.1.100 --port 8080
```

**Dry run (preview only):**

```bash
python watchfolder.py --folder ~/Videos/MySet --layer 1 --dry-run
```

### All options

| Flag | Description |
|------|-------------|
| `--folder`, `-f` | Path to folder containing media files |
| `--layer`, `-l` | Arena layer index (1-based) |
| `--watch`, `-w` | Keep running and re-sync on changes |
| `--host` | Arena webserver host (default: `127.0.0.1`) |
| `--port`, `-p` | Arena webserver port (default: `8080`) |
| `--dry-run` | Show what would happen without changing Arena |
| `--ui` | Launch web UI instead of CLI |
| `--ui-port` | Web UI port (default: `5000`) |
| `--desktop` | Launch as desktop app with native window |

## How It Works

### Smart sync

Instead of clearing all clips and reloading from scratch, smart sync:

1. Reads the current clips from Arena (what's loaded, where)
2. Scans the local folder for supported media files
3. Diffs the two: new files, removed files, unchanged files
4. Clears only removed clips
5. Loads only new files into available slots

**Unchanged clips are never touched** — all effects, speed settings, blend modes, and other tweaks survive a sync.

### Sets & clip memory

A **set** is a named profile with one or more folder-to-layer mappings. When you switch sets:

1. Current clip settings are **snapshotted** (saved per layer)
2. New set's folders are **synced** to their layers
3. Previously saved settings are **restored** from the new set's snapshots

This means you can use different media folders for different nights, and when you switch back, all your clip tweaks are exactly where you left them.

### Effect restoration

Effect settings are the hardest part to restore reliably. Arena assigns new parameter IDs every time an effect is added, so saved IDs become useless. This app uses a hybrid approach:

1. **REST API** adds missing effects synchronously (guaranteed to be present when the call returns)
2. **REST API** re-reads the clip to get fresh parameter IDs
3. **WebSocket** sets each parameter individually by ID, matched to saved values by structural key path (e.g. `params/softness`, `params/amount`)

If WebSocket is unavailable, the app falls back to REST-only restoration (effect parameter blobs via PUT).

### Watch mode

In watch mode, the app monitors folders using [watchdog](https://github.com/gorakhargosh/watchdog) (with a polling fallback on network drives) and runs a smart sync whenever files are added or removed. When clips return to the layer after being removed and re-added, their previous settings are automatically restored.

## Architecture

```
watchfolder.py      Main app — Flask web server, ArenaAPI REST client, sync logic, CLI
restore.py          Clip settings restore logic (WebSocket + REST hybrid)
arena_ws.py         Synchronous WebSocket client for Arena
config.py           Persistent configuration (JSON file)
desktop.py          Desktop app wrapper (pywebview + optional pystray)
templates/
  index.html        Web UI (single-page app, dark theme, built-in help)
```

### Module dependencies

```
watchfolder.py ─── imports from ──→ restore.py, config.py
                                         │
restore.py ──── imports from ──→ arena_ws.py (optional)
                                         │
arena_ws.py ─── standalone (json, websocket-client)
desktop.py ──── imports from ──→ watchfolder.py (create_web_app)
```

No circular imports. `restore.py` and `arena_ws.py` receive dependencies as parameters, never import from `watchfolder.py`.

## Platform Support

| Platform | Status |
|----------|--------|
| **macOS** | Tested and working |
| **Windows** | Not yet tested — help wanted! |
| **Linux** | Not yet tested — help wanted! |

### Help wanted: Windows & Linux testing

This app has been developed and tested on **macOS only**. I'm actively looking for people who run Resolume Arena on **Windows** or **Linux** to help test and contribute.

The core sync logic should work cross-platform since it's all Python + REST API calls, but there may be platform-specific issues with:

- **File paths** — Windows uses backslashes, and path handling may need tweaks
- **Desktop app** — pywebview and pystray behave differently across platforms
- **File watching** — watchdog's native backend varies by OS
- **Port conflicts** — different default services may occupy ports 5000/8080

**How you can help:**

- **Just try it** — install, run it, and let me know if it works. Even "it works on Windows 11" is valuable feedback!
- **Report issues** — if something breaks, open a GitHub issue with the error message and your OS version
- **Submit fixes** — pull requests with platform-specific fixes are very welcome
- **Use AI to help** — if you're not a Python developer, that's fine! You can use AI tools (ChatGPT, Claude, Copilot, etc.) to help diagnose issues and write fixes. Just paste the error message and the relevant code into an AI assistant and it can usually figure out what needs to change.

All contributions are welcome, whether you write code by hand or use AI-assisted development.

## Troubleshooting

**Can't connect to Arena?**
- Make sure Arena's webserver is enabled: Preferences > Webserver > Enable
- Check the host and port match (default: `127.0.0.1:8080`)
- If Arena is on another machine, use `--host <ip>` with the correct IP address

**Port 5000 already in use?**
- On macOS, AirPlay Receiver uses port 5000 by default
- Use `--ui-port 5050` (or any other free port)

**Effects not restoring correctly?**
- Make sure you saved a snapshot *after* adding effects in Arena
- The WebSocket connection gives better results than REST-only — check the log for "WebSocket connected"

**Files not syncing in watch mode?**
- Some network drives don't support native file events — the app falls back to polling automatically
- Large files may take a moment to become available after copying

> **Still stuck?** Copy the error from the log and paste it into an AI assistant (ChatGPT, Claude, etc.) along with a brief description of what you were trying to do. It can usually pinpoint the problem and suggest a fix.

## Dependencies

**Required** (installed via `pip install -r requirements.txt`):

| Package | Purpose |
|---------|---------|
| `requests` | HTTP client for Arena REST API |
| `flask` | Web server for UI and desktop modes |
| `watchdog` | File system monitoring for watch mode |
| `websocket-client` | WebSocket for real-time parameter control |

**Optional** (for desktop app mode):

| Package | Purpose |
|---------|---------|
| `pywebview` | Native window rendering |
| `pystray` | System tray icon (Windows/Linux) |
| `Pillow` | Tray icon generation |

Install optional deps with: `pip install pywebview pystray Pillow`

## License

MIT
