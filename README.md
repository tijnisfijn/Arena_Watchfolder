# Arena Watchfolder

Sync a local folder of media files to a layer in [Resolume Arena](https://resolume.com/) — automatically.

Drop videos and images into a folder, and they appear as clips in Arena. Add or remove files, and the layer updates to match. Use the **CLI** for scripting or the **Web UI** for a visual workflow.

## Features

- **One-shot sync** — scan a folder, load all media into a layer
- **Watch mode** — continuously monitor a folder and re-sync on changes
- **Web UI** — browser-based interface with real-time log streaming
- **Batch loading** — loads multiple clips in a single API call
- **Auto-expand** — grows the composition columns if needed
- **Cross-platform** — works on macOS and Windows

### Supported formats

**Video:** `.mov` `.mp4` `.avi` `.wmv` `.mkv` `.webm` `.m4v` `.flv` `.mpg` `.mpeg` `.3gp` `.ogv` `.ts` `.mxf`
**Image:** `.png` `.jpg` `.jpeg` `.gif` `.bmp` `.tiff` `.tif` `.tga` `.webp` `.exr` `.hdr` `.psd`
**Resolume:** `.dxv` `.hap`

## Requirements

- Python 3.7+
- [Resolume Arena](https://resolume.com/) with the webserver enabled (Preferences > Webserver)

## Installation

```bash
git clone https://github.com/tijnisfijn/Arena_Watchfolder.git
cd Arena_Watchfolder
python3 -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

## Usage

### Web UI

```bash
python watchfolder.py --ui --ui-port 5050
```

Open `http://127.0.0.1:5050` in your browser. From there you can:

1. Connect to Arena (set host/port)
2. Enter a folder path and target layer
3. Hit **Sync Now** or **Start Watch**

Log output streams in real time.

> **Note:** Port 5000 is often taken by AirPlay on macOS. Use `--ui-port 5050` or another free port.

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

## How it works

1. Scans the folder for media files (sorted alphabetically)
2. Ensures Arena has enough columns for all files
3. Clears existing clips on the target layer
4. Batch-loads all files into consecutive clip slots via Arena's REST API

In **watch mode**, it monitors the folder using [watchdog](https://github.com/gorakhargosh/watchdog) (with a polling fallback) and re-syncs whenever files are added or removed.

## License

MIT
