# Arena Watchfolder

![Arena Watchfolder](banner.jpg)

Sync local folders of media files to layers in [Resolume Arena](https://resolume.com/) — automatically.

Drop videos and images into a folder, and they appear as clips in Arena. Add or remove files, and the layer updates to match. Your clip effects, speed settings, cue points, and blend modes are preserved across syncs.

## Features

- **Smart sync** — only adds/removes changed clips; existing effects and settings are never touched
- **Sets & profiles** — named configurations (e.g. "Thursday Night", "Friday Night") with their own folder-to-layer mappings
- **Clip memory** — snapshot and restore all clip settings including effects with full parameter values, transport, cue points, and more
- **WebSocket + REST** — effects are restored with precise parameter-by-ID updates via WebSocket, with REST as a reliable fallback
- **Multi-layer mapping** — sync multiple folders to different layers in a single set
- **Watch mode** — continuously monitor folders and re-sync on file changes
- **Web UI** — browser-based interface with real-time log streaming
- **Desktop app** — native window via pywebview (optional)
- **Batch loading** — loads multiple clips in a single API call for faster sync
- **Auto-expand** — grows the composition columns if the folder has more files than slots
- **Config persistence** — sets, mappings, and snapshots saved to disk across restarts

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

> **Not familiar with Python or the terminal?** No worries — paste these instructions into any AI/LLM (like ChatGPT or Claude) and ask it to walk you through the setup step by step. It'll get you up and running in no time.

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

## Usage

### Web UI

```bash
python watchfolder.py --ui --ui-port 5050
```

Open `http://127.0.0.1:5050` in your browser. From there you can:

1. **Connect** to Arena (set host/port if not default)
2. **Create sets** — e.g. "Thursday Night", "Friday Night"
3. **Add mappings** — assign folders to layers within each set
4. **Sync / Watch** — one-shot sync or continuous watch per mapping
5. **Snapshot / Restore** — save and recall clip settings (effects, speed, blend modes, cue points)
6. **Switch sets** — current settings are auto-saved, new set is synced and restored

Log output streams in real time at the bottom of the page.

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
  index.html        Web UI (single-page app, dark theme)
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
| **Windows** | Not yet tested |
| **Linux** | Not yet tested |

### Help wanted: Windows & Linux testing

This app has been developed and tested on macOS only. If you're running Resolume Arena on **Windows** or **Linux** and would like to help test (or contribute), that would be greatly appreciated! Whether you use AI-assisted development or write code by hand, all contributions are welcome.

To get involved:
- Open an issue on GitHub if something doesn't work on your platform
- Submit a pull request with fixes or improvements
- Or just let me know it works — that's helpful too!

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
