# Arena Watchfolder

![Arena Watchfolder](banner.jpg)

**Keep your Resolume Arena clips in sync with folders on disk — automatically.**

Arena Watchfolder bridges the gap between your file system and Resolume Arena. Map a folder to a layer, and every video or image in that folder becomes a clip in Arena. Add a file, it appears. Remove a file, it disappears. Your effects, speed settings, cue points, and blend modes are preserved across every sync.

## Why use this?

If you use Resolume Arena for live visuals, you know the pain: manually loading clips one by one, losing all your effect tweaks when you reload media, and having no easy way to switch between different media sets for different gigs.

Arena Watchfolder solves this:

- **Gig prep made easy** — Organize media into folders per event, map each to a layer, and switch between them with one click. All your clip tweaks come back automatically.
- **Live media updates** — Drop a new video into your folder mid-show and it appears in Arena within seconds. Remove a file and the clip disappears.
- **Multi-layer setups** — Map different folders to different layers: backgrounds on layer 1, overlays on layer 2, text on layer 3. Sync them all at once.
- **Clip memory** — Snapshot every clip setting (effects, speed, cue points, blend modes) and restore them later, even after switching compositions or restarting Arena.
- **Safety locks** — Prevent accidental syncs when the wrong composition or deck is loaded.
- **Collect from Arena** — Pull an existing Arena layer into a folder with one click, including all files and settings.

## Quick Start

> **Not familiar with Python?** Paste these instructions into any AI assistant (ChatGPT, Claude, Copilot) and ask it to walk you through the setup. You can also paste any error messages and it'll help fix them.

### Requirements

- **Python 3.10+** — [download here](https://www.python.org/downloads/) if you don't have it
- **Resolume Arena 7.x+** with the web server enabled (Preferences > Webserver)

### Install

**1. Download the project**

```bash
git clone https://github.com/tijnisfijn/Arena_Watchfolder.git
cd Arena_Watchfolder
```

Or click the green **Code** button on GitHub and choose **Download ZIP**, then extract it.

**2. Create a virtual environment and install dependencies**

macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows:
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**3. Run it**

```bash
python watchfolder.py --ui
```

The web UI opens at `http://127.0.0.1:5000`. If port 5000 is taken (common on macOS due to AirPlay), use `--ui-port 5050`.

> **Desktop app mode** (native window instead of browser tab):
> ```bash
> pip install pywebview pystray Pillow
> python watchfolder.py --desktop
> ```

### Your first sync

1. Make sure Arena is running with the web server enabled (Preferences > Webserver)
2. Start the app: `python watchfolder.py --ui`
3. Click **Connect** — it should find Arena on `127.0.0.1:8080`
4. Create a set (e.g. "My First Set") using the **New** button
5. Click **Add Folder Mapping** and pick a folder with video files
6. Set the layer number (which Arena layer to sync to)
7. Click **Sync Now** — your files appear as clips in Arena
8. Tweak the clips in Arena (add effects, change speed, etc.)
9. Click **Save Settings** to snapshot your work
10. Next time you sync, click **Restore Settings** to bring it all back

For the full user manual — covering every panel, feature, workflow, and troubleshooting — see **[Docs/USER_MANUAL.md](Docs/USER_MANUAL.md)**.

## CLI Usage

```bash
# One-shot sync
python watchfolder.py --folder ~/Videos/MySet --layer 2

# Watch mode (continuous)
python watchfolder.py --folder ~/Videos/MySet --layer 2 --watch

# Custom Arena host/port
python watchfolder.py --folder ~/Videos/MySet --layer 3 --host 192.168.1.100 --port 8080

# Dry run (preview without changing Arena)
python watchfolder.py --folder ~/Videos/MySet --layer 1 --dry-run
```

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

## Platform support

| Platform | Status |
|----------|--------|
| **macOS** | Tested and working |
| **Windows** | Should work — help wanted for testing |
| **Linux** | Should work — help wanted for testing |

The core sync logic is cross-platform (Python + REST API). If you try it on Windows or Linux, please open an issue with your experience — even "it works" is valuable feedback!

## License

MIT
