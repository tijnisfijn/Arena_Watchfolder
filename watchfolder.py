#!/usr/bin/env python3
"""
Resolume Arena Watch Folder Sync
================================
Syncs a local folder of media files to a specific layer in Resolume Arena.

Usage:
    # One-shot sync (default)
    python watchfolder.py --folder "/path/to/media" --layer 3

    # Continuous watch mode
    python watchfolder.py --folder "/path/to/media" --layer 3 --watch

    # Custom Arena host/port
    python watchfolder.py --folder "/path/to/media" --layer 3 --host 192.168.1.10 --port 8080

Requirements:
    - Python 3.7+
    - requests library:  pip install requests
    - (optional) watchdog library for --watch mode:  pip install watchdog

Works on macOS and Windows.
"""

import argparse
import json
import os
import platform
import queue
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library is required. Install it with:\n  pip install requests")
    sys.exit(1)

try:
    from flask import Flask, request as flask_request, jsonify, Response, render_template
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MEDIA_EXTENSIONS = {
    # Video
    ".mov", ".mp4", ".avi", ".wmv", ".mkv", ".webm", ".m4v", ".flv",
    ".mpg", ".mpeg", ".3gp", ".ogv", ".ts", ".mxf",
    # Image / still
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".tga",
    ".webp", ".exr", ".hdr", ".psd",
    # Resolume-specific
    ".dxv", ".hap",
}

POLL_INTERVAL = 2  # seconds between polls in --watch mode


# ---------------------------------------------------------------------------
# Log manager (feeds both CLI stdout and web UI via SSE)
# ---------------------------------------------------------------------------

class LogManager:
    """Thread-safe log buffer with SSE streaming support."""

    def __init__(self):
        self._messages = []
        self._subscribers = []
        self._lock = threading.Lock()

    def log(self, message: str):
        entry = {"time": datetime.now().isoformat(), "text": message}
        with self._lock:
            self._messages.append(entry)
            if len(self._messages) > 500:
                self._messages = self._messages[-500:]
            for q in self._subscribers:
                q.put(entry)

    def subscribe(self) -> queue.Queue:
        q = queue.Queue()
        with self._lock:
            for msg in self._messages:
                q.put(msg)
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)


log_manager = LogManager()


def log(message: str):
    """Print to console AND buffer for web UI."""
    print(message)
    log_manager.log(message)


class ArenaConnectionError(Exception):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def path_to_file_uri(filepath: str) -> str:
    """Convert a local file path to a file:/// URI that Resolume understands.

    Handles both macOS (/Users/...) and Windows (C:\\Users\\...) paths,
    and correctly URL-encodes special characters (spaces, brackets, etc.).
    """
    p = Path(filepath).resolve()
    # pathlib on Windows gives backslashes; we need forward slashes
    posix = p.as_posix()  # e.g. C:/Users/...  or  /Users/...

    # On Windows, Path.as_posix() gives "C:/Users/..." — we need "/C:/Users/..."
    if platform.system() == "Windows" and not posix.startswith("/"):
        posix = "/" + posix

    # URL-encode each path component (but keep the slashes)
    parts = posix.split("/")
    encoded_parts = [urllib.parse.quote(part, safe="") for part in parts]
    encoded_path = "/".join(encoded_parts)

    return f"file://{encoded_path}"


def scan_folder(folder: str) -> list[str]:
    """Return sorted list of absolute paths to media files in *folder*."""
    folder_path = Path(folder).resolve()
    if not folder_path.is_dir():
        raise ValueError(f"Folder does not exist: {folder_path}")

    files = []
    for entry in sorted(folder_path.iterdir()):
        if entry.is_file() and entry.suffix.lower() in MEDIA_EXTENSIONS:
            files.append(str(entry))
    return files


# ---------------------------------------------------------------------------
# Arena REST API wrapper
# ---------------------------------------------------------------------------

class ArenaAPI:
    """Thin wrapper around the Resolume Arena REST API."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self.base = f"http://{host}:{port}/api/v1"
        self._check_connection()

    def _check_connection(self):
        try:
            r = requests.get(f"{self.base}/product", timeout=5)
            r.raise_for_status()
            info = r.json()
            name = info.get("name", "Unknown")
            version = f"{info.get('major', '?')}.{info.get('minor', '?')}.{info.get('micro', '?')}"
            log(f"  Connected to {name} {version}")
        except requests.ConnectionError:
            raise ArenaConnectionError(
                f"Cannot connect to Arena at {self.base}. "
                "Make sure Arena is running and the webserver is enabled in Preferences."
            )
        except Exception as e:
            raise ArenaConnectionError(f"Unexpected error connecting to Arena: {e}")

    def get_composition_info(self) -> dict:
        r = requests.get(f"{self.base}/composition", timeout=10)
        r.raise_for_status()
        return r.json()

    def get_column_count(self) -> int:
        """Get the current number of columns from the composition."""
        info = self.get_composition_info()
        # The composition JSON has a "columns" array — its length is the count
        columns = info.get("columns", [])
        return len(columns) if isinstance(columns, list) else 0

    def grow_columns(self, needed: int):
        """Ensure the composition has at least *needed* columns."""
        r = requests.post(
            f"{self.base}/composition/grow-to",
            json={"column_count": needed},
            timeout=10,
        )
        r.raise_for_status()

    def clear_layer_clips(self, layer: int):
        """Remove ALL clip content from a layer (wipes the slots)."""
        r = requests.post(f"{self.base}/composition/layers/{layer}/clearclips", timeout=10)
        if r.status_code == 404:
            raise ValueError(f"Layer {layer} does not exist in the composition.")
        r.raise_for_status()

    def batch_open_clips(self, layer: int, file_paths: list[str]):
        """Load a list of files into consecutive clip slots on the given layer.

        Uses the batch /composition/clips/open endpoint for efficiency.
        """
        payload = []
        for i, fpath in enumerate(file_paths, start=1):
            uri = path_to_file_uri(fpath)
            payload.append({
                "target": f"/composition/layers/{layer}/clips/{i}",
                "source": uri,
            })

        r = requests.post(
            f"{self.base}/composition/clips/open",
            json=payload,
            timeout=60,  # loading many large files can take a while
        )
        if r.status_code == 404:
            log("ERROR: One or more clip slots or files were not found.")
            log(f"       Response: {r.text}")
        r.raise_for_status()

    def get_layer_name(self, layer: int) -> str:
        try:
            r = requests.get(f"{self.base}/composition/layers/{layer}", timeout=10)
            r.raise_for_status()
            data = r.json()
            name_param = data.get("name", {})
            return name_param.get("value", f"Layer {layer}")
        except Exception:
            return f"Layer {layer}"


# ---------------------------------------------------------------------------
# Core sync logic
# ---------------------------------------------------------------------------

def sync_folder_to_layer(api: ArenaAPI, folder: str, layer: int, dry_run: bool = False) -> list[str]:
    """Perform one sync cycle: scan folder → clear layer → load clips.

    Returns the list of files that were synced.
    """
    files = scan_folder(folder)

    if not files:
        log("  No media files found in folder.")
        return []

    log(f"  Found {len(files)} media file(s):")
    for f in files:
        log(f"    • {Path(f).name}")

    if dry_run:
        log("  [DRY RUN] — no changes made.")
        return files

    # Step 1: Ensure enough columns
    current_cols = api.get_column_count()
    if len(files) > current_cols:
        log(f"  Expanding columns: {current_cols} → {len(files)}")
        api.grow_columns(len(files))
    else:
        log(f"  Columns OK ({current_cols} available, {len(files)} needed)")

    # Step 2: Clear the target layer
    layer_name = api.get_layer_name(layer)
    log(f"  Clearing clips on {layer_name} (index {layer})...")
    api.clear_layer_clips(layer)

    # Step 3: Load files into clip slots
    log(f"  Loading {len(files)} clip(s) into layer {layer}...")
    api.batch_open_clips(layer, files)
    log("  Sync complete!")

    return files


# ---------------------------------------------------------------------------
# Watch mode (continuous)
# ---------------------------------------------------------------------------

def watch_folder(api: ArenaAPI, folder: str, layer: int, stop_flag=None):
    """Continuously monitor the folder and re-sync when changes are detected.

    If *stop_flag* is a callable returning True, the loop exits gracefully
    (used by the web UI). CLI mode relies on KeyboardInterrupt instead.
    """
    log(f"\n  WATCH MODE — monitoring '{folder}' every {POLL_INTERVAL}s")
    if not stop_flag:
        log("  Press Ctrl+C to stop.\n")

    last_snapshot = None

    def _should_stop():
        return stop_flag and stop_flag()

    try:
        # Try using watchdog for efficient filesystem events
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class Handler(FileSystemEventHandler):
            def __init__(self):
                self.changed = False

            def on_any_event(self, event):
                # Only react to media files
                if event.is_directory:
                    return
                ext = Path(event.src_path).suffix.lower()
                if ext in MEDIA_EXTENSIONS:
                    self.changed = True

        handler = Handler()
        observer = Observer()
        observer.schedule(handler, folder, recursive=False)
        observer.start()
        log("  Using watchdog for filesystem events (efficient mode)")

        # Do initial sync
        last_snapshot = set(scan_folder(folder))
        sync_folder_to_layer(api, folder, layer)

        try:
            while not _should_stop():
                time.sleep(POLL_INTERVAL)
                if handler.changed:
                    handler.changed = False
                    current = set(scan_folder(folder))
                    if current != last_snapshot:
                        added = current - last_snapshot
                        removed = last_snapshot - current
                        if added:
                            log(f"\n  + {len(added)} file(s) added")
                        if removed:
                            log(f"\n  - {len(removed)} file(s) removed")
                        log("  Re-syncing...")
                        sync_folder_to_layer(api, folder, layer)
                        last_snapshot = current
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()
            observer.join()
            log("\n  Watch stopped.")

    except ImportError:
        # Fallback: simple polling
        log("  watchdog not installed — using polling fallback")
        log("  (Install 'watchdog' for more efficient watching: pip install watchdog)\n")

        # Do initial sync
        last_snapshot = set(scan_folder(folder))
        sync_folder_to_layer(api, folder, layer)

        try:
            while not _should_stop():
                time.sleep(POLL_INTERVAL)
                current = set(scan_folder(folder))
                if current != last_snapshot:
                    added = current - last_snapshot
                    removed = last_snapshot - current
                    if added:
                        log(f"\n  + {len(added)} file(s) added")
                    if removed:
                        log(f"\n  - {len(removed)} file(s) removed")
                    log("  Re-syncing...")
                    sync_folder_to_layer(api, folder, layer)
                    last_snapshot = current
        except KeyboardInterrupt:
            log("\n  Watch stopped.")


# ---------------------------------------------------------------------------
# Web UI (Flask)
# ---------------------------------------------------------------------------

def create_web_app():
    """Create and return the Flask application for the web UI."""
    app = Flask(__name__)

    # Shared state for the web UI
    _state = {
        "api": None,
        "watching": False,
        "watch_thread": None,
        "folder": "",
        "layer": 1,
        "host": "127.0.0.1",
        "port": 8080,
    }

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/connect", methods=["POST"])
    def connect():
        data = flask_request.json
        host = data.get("host", "127.0.0.1")
        port = int(data.get("port", 8080))
        try:
            _state["api"] = ArenaAPI(host=host, port=port)
            _state["host"] = host
            _state["port"] = port
            return jsonify({"ok": True})
        except ArenaConnectionError as e:
            _state["api"] = None
            log(f"  ERROR: {e}")
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route("/api/scan", methods=["POST"])
    def scan():
        data = flask_request.json
        folder = data.get("folder", "")
        try:
            files = scan_folder(folder)
            return jsonify({"ok": True, "files": [Path(f).name for f in files], "count": len(files)})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route("/api/sync", methods=["POST"])
    def sync():
        data = flask_request.json
        folder = data.get("folder", "")
        layer = int(data.get("layer", 1))
        if not _state["api"]:
            return jsonify({"ok": False, "error": "Not connected to Arena"}), 400
        try:
            files = sync_folder_to_layer(_state["api"], folder, layer)
            return jsonify({"ok": True, "files": [Path(f).name for f in files]})
        except (ValueError, ArenaConnectionError) as e:
            log(f"  ERROR: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500
        except Exception as e:
            log(f"  ERROR: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/watch/start", methods=["POST"])
    def watch_start():
        data = flask_request.json
        folder = data.get("folder", "")
        layer = int(data.get("layer", 1))
        if not _state["api"]:
            return jsonify({"ok": False, "error": "Not connected to Arena"}), 400
        if _state["watching"]:
            return jsonify({"ok": False, "error": "Already watching"}), 400

        _state["watching"] = True
        _state["folder"] = folder
        _state["layer"] = layer

        def run_watch():
            try:
                watch_folder(_state["api"], folder, layer,
                             stop_flag=lambda: not _state["watching"])
            except Exception as e:
                log(f"  Watch error: {e}")
            finally:
                _state["watching"] = False

        t = threading.Thread(target=run_watch, daemon=True)
        t.start()
        _state["watch_thread"] = t
        return jsonify({"ok": True})

    @app.route("/api/watch/stop", methods=["POST"])
    def watch_stop():
        _state["watching"] = False
        log("  Stopping watch mode...")
        return jsonify({"ok": True})

    @app.route("/api/status")
    def status():
        return jsonify({
            "connected": _state["api"] is not None,
            "watching": _state["watching"],
            "folder": _state["folder"],
            "layer": _state["layer"],
        })

    @app.route("/api/shutdown", methods=["POST"])
    def shutdown():
        """Shut down the Flask server gracefully."""
        log("  Server shutdown requested from web UI.")
        # Stop watch mode if running
        _state["watching"] = False
        # Schedule shutdown after response is sent
        def do_shutdown():
            time.sleep(0.5)
            os._exit(0)
        threading.Thread(target=do_shutdown, daemon=True).start()
        return jsonify({"ok": True})

    @app.route("/api/logs")
    def logs_stream():
        """SSE endpoint — streams log messages to the browser."""
        def generate():
            q = log_manager.subscribe()
            try:
                while True:
                    try:
                        entry = q.get(timeout=30)
                        yield f"data: {json.dumps(entry)}\n\n"
                    except queue.Empty:
                        yield ": keepalive\n\n"
            except GeneratorExit:
                log_manager.unsubscribe(q)

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no"})

    return app


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Resolume Arena Watch Folder — sync a folder of media to a layer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s --folder ~/Videos/SetA --layer 2
  %(prog)s --folder "C:\\Users\\VJ\\Clips" --layer 1 --watch
  %(prog)s --folder /media/show --layer 3 --host 192.168.1.100 --port 8080 --watch
  %(prog)s --ui
        """,
    )
    parser.add_argument(
        "--folder", "-f",
        default=None,
        help="Path to the folder containing media files",
    )
    parser.add_argument(
        "--layer", "-l",
        type=int,
        default=None,
        help="Layer index to sync to (1-based)",
    )
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Keep running and auto-sync when folder contents change",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Arena webserver host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8080,
        help="Arena webserver port (default: 8080)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan folder and show what would happen, but don't change Arena",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Launch web UI instead of CLI mode (requires Flask: pip install flask)",
    )
    parser.add_argument(
        "--ui-port",
        type=int,
        default=5000,
        help="Port for the web UI (default: 5000)",
    )

    args = parser.parse_args()

    # --- Web UI mode ---
    if args.ui:
        if not HAS_FLASK:
            print("ERROR: Flask is required for --ui mode. Install it with:\n  pip install flask")
            sys.exit(1)
        app = create_web_app()
        print()
        print("╔══════════════════════════════════════════════╗")
        print("║   Resolume Arena — Watch Folder Sync (UI)    ║")
        print("╚══════════════════════════════════════════════╝")
        print()
        print(f"  Web UI → http://127.0.0.1:{args.ui_port}")
        print()
        app.run(host="0.0.0.0", port=args.ui_port, debug=False, threaded=True)
        return

    # --- CLI mode (original behavior) ---
    if not args.folder:
        parser.error("--folder is required (unless using --ui)")
    if args.layer is None:
        parser.error("--layer is required (unless using --ui)")

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   Resolume Arena — Watch Folder Sync         ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print(f"  Folder : {Path(args.folder).resolve()}")
    print(f"  Layer  : {args.layer}")
    print(f"  Mode   : {'WATCH (continuous)' if args.watch else 'ONE-SHOT'}")
    print(f"  Arena  : {args.host}:{args.port}")
    print()

    if args.dry_run:
        print("  *** DRY RUN MODE — no changes will be made ***\n")
        try:
            files = scan_folder(args.folder)
        except ValueError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        print(f"  Found {len(files)} media file(s):")
        for f in files:
            print(f"    • {Path(f).name}")
        return

    try:
        api = ArenaAPI(host=args.host, port=args.port)
    except ArenaConnectionError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    try:
        if args.watch:
            watch_folder(api, args.folder, args.layer)
        else:
            sync_folder_to_layer(api, args.folder, args.layer)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print()


if __name__ == "__main__":
    main()
