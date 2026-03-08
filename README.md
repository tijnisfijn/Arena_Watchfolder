# Arena Watchfolder

![Arena Watchfolder](banner.jpg)

**Keep your Resolume Arena clips in sync with folders on disk — automatically.**

Arena Watchfolder bridges the gap between your file system and Resolume Arena. Map a folder to a layer, and every video or image in that folder becomes a clip in Arena. Add a file, it appears. Remove a file, it disappears. Your effects, speed settings, cue points, and blend modes are preserved across every sync.

## Download

Grab the latest release — no Python or terminal needed:

**➜ [Download Arena Watchfolder](https://github.com/tijnisfijn/Arena_Watchfolder/releases/latest)**

| Platform | Status |
|----------|--------|
| **macOS** | ✅ Available now |
| **Windows** | 🔜 Coming soon |

### Install

1. Download the `.zip` from the link above
2. Unzip it and drag **Arena Watchfolder.app** to your Applications folder (or anywhere you like)
3. Double-click to launch — if macOS blocks it, right-click → **Open** → **Open**

> **Requirement:** Resolume Arena must be running with the web server enabled (Preferences → Webserver).

### Your first sync

1. Make sure Arena is running with the web server enabled (Preferences → Webserver)
2. Open Arena Watchfolder
3. Click **Connect** — it should find Arena on `127.0.0.1:8080`
4. Create a set (e.g. "My First Set") using the **New** button
5. Click **Add Folder Mapping** and pick a folder with video files
6. Set the layer number (which Arena layer to sync to)
7. Click **Sync Now** — your files appear as clips in Arena
8. Tweak the clips in Arena (add effects, change speed, etc.)
9. Click **Save Settings** to snapshot your work
10. Next time you sync, click **Restore Settings** to bring it all back

For the full user manual — covering every panel, feature, workflow, and troubleshooting — see **[Docs/USER_MANUAL.md](Docs/USER_MANUAL.md)**.

---

## Running from source

For developers and contributors who want to run from the repo directly.

> **Not familiar with Python?** Paste these instructions into any AI assistant (ChatGPT, Claude, Copilot) and ask it to walk you through the setup.

### Requirements

- **Python 3.10+** — [download here](https://www.python.org/downloads/)
- **Resolume Arena 7.x+** with the web server enabled (Preferences → Webserver)

### Setup

```bash
git clone https://github.com/tijnisfijn/Arena_Watchfolder.git
cd Arena_Watchfolder
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python watchfolder.py --ui
```

The web UI opens at `http://127.0.0.1:5000`. Use `--ui-port 5050` if port 5000 is taken.

> **Desktop app mode** (native window instead of browser tab):
> ```bash
> pip install pywebview pystray Pillow
> python watchfolder.py --desktop
> ```

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

## License

MIT
