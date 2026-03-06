#!/usr/bin/env python3
"""
Resolume Arena Watch Folder Sync
================================
Syncs local folders of media files to layers in Resolume Arena.

Usage:
    # One-shot sync (default)
    python watchfolder.py --folder "/path/to/media" --layer 3

    # Continuous watch mode
    python watchfolder.py --folder "/path/to/media" --layer 3 --watch

    # Web UI
    python watchfolder.py --ui

    # Desktop app (native window + system tray)
    python watchfolder.py --desktop

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
import shutil
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
    """Convert a local file path to a file:/// URI that Resolume understands."""
    p = Path(filepath).resolve()
    posix = p.as_posix()

    if platform.system() == "Windows" and not posix.startswith("/"):
        posix = "/" + posix

    parts = posix.split("/")
    encoded_parts = [urllib.parse.quote(part, safe="") for part in parts]
    encoded_path = "/".join(encoded_parts)

    return f"file://{encoded_path}"


def normalize_path(p):
    """Normalize a file path for comparison (handles file:// URIs and OS paths)."""
    if p is None:
        return None
    if p.startswith("file://"):
        p = urllib.parse.unquote(urllib.parse.urlparse(p).path)
    return str(Path(p).resolve())


def _sanitize_dirname(name: str) -> str:
    """Sanitize a string for use as a directory name."""
    for ch in r'<>:"/\|?*':
        name = name.replace(ch, "_")
    return name.strip(". ") or "Untitled"


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
        self.host = host
        self.port = port
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

    def get_composition_name(self) -> str:
        """Return the name of the currently loaded composition."""
        info = self.get_composition_info()
        return info.get("name", {}).get("value", "")

    def get_column_count(self) -> int:
        """Get the current number of columns from the composition."""
        info = self.get_composition_info()
        columns = info.get("columns", [])
        return len(columns) if isinstance(columns, list) else 0

    def get_layer_count(self) -> int:
        """Get the number of layers in the composition."""
        info = self.get_composition_info()
        layers = info.get("layers", [])
        return len(layers) if isinstance(layers, list) else 0

    def grow_columns(self, needed: int):
        """Ensure the composition has at least *needed* columns.

        Tries the grow-to endpoint first. If that fails, falls back to
        adding individual columns via the column create endpoint.
        """
        current = self.get_column_count()
        if current >= needed:
            return

        # Try grow-to endpoint
        try:
            r = requests.post(
                f"{self.base}/composition/grow-to",
                json={"column_count": needed},
                timeout=10,
            )
            r.raise_for_status()
        except Exception:
            pass  # fall through to verification

        # Verify it worked
        after = self.get_column_count()
        if after >= needed:
            return

        # Fallback: add columns one at a time
        for _ in range(needed - after):
            try:
                r = requests.post(
                    f"{self.base}/composition/columns",
                    timeout=10,
                )
                r.raise_for_status()
            except Exception:
                break  # can't add more

        final = self.get_column_count()
        if final < needed:
            log(f"  WARNING: Could only grow to {final} columns (needed {needed})")

    def get_layer_clips(self, layer: int) -> list[dict]:
        """Get all clips on a layer with their slot index, file path, and full data.

        Returns list of dicts:
            [{"slot": 1, "path": "/path/to/file.mov", "data": {full clip JSON}}, ...]
        Empty slots have path=None and data=None.
        """
        r = requests.get(f"{self.base}/composition/layers/{layer}", timeout=10)
        if r.status_code == 404:
            raise ValueError(f"Layer {layer} does not exist in the composition.")
        r.raise_for_status()
        layer_data = r.json()

        clips = []
        for i, clip in enumerate(layer_data.get("clips", []), start=1):
            connected = clip.get("connected", {}).get("value", "Empty")
            if connected == "Empty":
                clips.append({"slot": i, "path": None, "data": None})
            else:
                video = clip.get("video") or {}
                fileinfo = video.get("fileinfo") or {}
                file_path = fileinfo.get("path")
                clips.append({"slot": i, "path": file_path, "data": clip})
        return clips

    def clear_clip(self, layer: int, clip: int):
        """Clear a single clip slot on a layer."""
        r = requests.post(
            f"{self.base}/composition/layers/{layer}/clips/{clip}/clear",
            timeout=10,
        )
        r.raise_for_status()

    def clear_layer_clips(self, layer: int):
        """Remove ALL clip content from a layer (wipes the slots)."""
        r = requests.post(f"{self.base}/composition/layers/{layer}/clearclips", timeout=10)
        if r.status_code == 404:
            raise ValueError(f"Layer {layer} does not exist in the composition.")
        r.raise_for_status()

    def open_clip(self, layer: int, clip: int, file_path: str):
        """Load a file into a specific clip slot on a layer."""
        uri = path_to_file_uri(file_path)
        r = requests.post(
            f"{self.base}/composition/layers/{layer}/clips/{clip}/open",
            data=uri,
            headers={"Content-Type": "text/plain"},
            timeout=30,
        )
        r.raise_for_status()

    def open_clip_source(self, layer: int, clip: int, source_name: str):
        """Load a generated source into a specific clip slot on a layer."""
        uri = f"source:///video/{urllib.parse.quote(source_name)}"
        r = requests.post(
            f"{self.base}/composition/layers/{layer}/clips/{clip}/open",
            data=uri,
            headers={"Content-Type": "text/plain"},
            timeout=30,
        )
        r.raise_for_status()

    def batch_open_clips(self, layer: int, slot_file_pairs: list[tuple[int, str]]):
        """Load files into specific clip slots using the batch endpoint.

        slot_file_pairs: list of (slot_number, file_path) tuples.
        """
        if not slot_file_pairs:
            return
        payload = []
        for slot, fpath in slot_file_pairs:
            uri = path_to_file_uri(fpath)
            payload.append({
                "target": f"/composition/layers/{layer}/clips/{slot}",
                "source": uri,
            })

        r = requests.post(
            f"{self.base}/composition/clips/open",
            json=payload,
            timeout=60,
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
            name = name_param.get("value", f"Layer {layer}")
            # Arena uses "Layer #" for unnamed layers — replace # with number
            if name == "Layer #":
                name = f"Layer {layer}"
            return name
        except Exception:
            return f"Layer {layer}"

    def set_layer_name(self, layer: int, name: str):
        """Rename a layer in Arena."""
        r = requests.put(
            f"{self.base}/composition/layers/{layer}",
            json={"name": {"value": name}},
            timeout=10,
        )
        r.raise_for_status()

    def get_clip_data(self, layer: int, clip: int) -> dict:
        """Get full clip data for a specific slot."""
        r = requests.get(
            f"{self.base}/composition/layers/{layer}/clips/{clip}",
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def update_clip(self, layer: int, clip: int, data: dict):
        """Update clip properties (for restoring settings from snapshot)."""
        r = requests.put(
            f"{self.base}/composition/layers/{layer}/clips/{clip}",
            json=data,
            timeout=30,
        )
        r.raise_for_status()

    def add_clip_effect(self, layer: int, clip: int, effect_name: str):
        """Add a video effect to a clip by display name.

        Uses the Arena effect URI format: effect:///video/{name}
        """
        encoded_name = urllib.parse.quote(effect_name, safe="")
        uri = f"effect:///video/{encoded_name}"
        r = requests.post(
            f"{self.base}/composition/layers/{layer}/clips/{clip}/effects/video/add",
            data=uri,
            headers={"Content-Type": "text/plain"},
            timeout=10,
        )
        r.raise_for_status()

    # --- Deck management ---

    def get_decks(self) -> list[dict]:
        """Return list of decks: [{name, id, index, selected}, ...]."""
        info = self.get_composition_info()
        decks = info.get("decks", [])
        result = []
        for i, deck in enumerate(decks):
            result.append({
                "name": deck.get("name", {}).get("value", f"Deck {i + 1}"),
                "id": deck.get("id"),
                "index": i + 1,  # 1-based for API calls
                "selected": deck.get("selected", {}).get("value", False),
            })
        return result

    def get_selected_deck(self) -> str | None:
        """Return the name of the currently selected deck, or None."""
        for deck in self.get_decks():
            if deck["selected"]:
                return deck["name"]
        return None

    def select_deck(self, index: int):
        """Select a deck by 1-based index."""
        r = requests.post(
            f"{self.base}/composition/decks/{index}/select",
            timeout=10,
        )
        r.raise_for_status()


# ---------------------------------------------------------------------------
# Layer Snapshots — save/restore full layer state
# ---------------------------------------------------------------------------

def _extract_clip_name(clip_data: dict) -> str:
    """Extract the display name from a clip's JSON data."""
    name = clip_data.get("name")
    if isinstance(name, str):
        return name
    if isinstance(name, dict):
        return name.get("value", "")
    return ""


def snapshot_layer(api: ArenaAPI, layer: int) -> list[dict]:
    """Capture the full state of all clips on a layer.

    Returns a list of dicts, one per slot:
        [{"slot": 1, "filename": "logo.mov", "path": "/full/path/logo.mov", "data": {clip JSON}}, ...]
    Empty slots are included with filename=None.
    Generated sources (no file path but connected) are stored with source_name.
    """
    clips = api.get_layer_clips(layer)
    snapshot = []
    for clip in clips:
        if clip["path"]:
            snapshot.append({
                "slot": clip["slot"],
                "filename": Path(clip["path"]).name,
                "path": clip["path"],
                "data": clip["data"],
            })
        elif clip["data"]:
            # Generated source — no file but has clip data
            source_name = _extract_clip_name(clip["data"])
            snapshot.append({
                "slot": clip["slot"],
                "filename": None,
                "source_name": source_name or "Unknown Source",
                "path": None,
                "data": clip["data"],
            })
        else:
            snapshot.append({
                "slot": clip["slot"],
                "filename": None,
                "path": None,
                "data": None,
            })
    return snapshot


def merge_snapshots(old_snap: list[dict] | None, new_snap: list[dict]) -> list[dict]:
    """Merge new snapshot with old, preserving settings for clips no longer on the layer.

    When a clip is removed from a layer, its settings are kept as "remembered"
    entries so they can be restored if the clip returns later.
    Handles both file-based clips (keyed by filename) and generated sources
    (keyed by source_name + slot).
    """
    if not old_snap:
        return new_snap

    # Filenames present in the new (current) snapshot
    new_filenames = {e["filename"] for e in new_snap if e.get("filename")}

    # Source entries present in the new snapshot (keyed by source_name + slot)
    new_sources = {
        (e.get("source_name"), e.get("slot"))
        for e in new_snap if e.get("source_name")
    }

    # Start with the new snapshot
    merged = list(new_snap)

    # Preserve old entries for clips that are no longer on the layer
    for entry in old_snap:
        fname = entry.get("filename")
        sname = entry.get("source_name")
        if fname and fname not in new_filenames and entry.get("data"):
            merged.append({
                "slot": None,
                "filename": fname,
                "path": entry.get("path", ""),
                "data": entry["data"],
                "remembered": True,
            })
        elif sname and (sname, entry.get("slot")) not in new_sources and entry.get("data"):
            merged.append({
                "slot": entry.get("slot"),
                "filename": None,
                "source_name": sname,
                "path": None,
                "data": entry["data"],
                "remembered": True,
            })

    return merged


# ---------------------------------------------------------------------------
# Combined snapshot file I/O
# ---------------------------------------------------------------------------

SNAPSHOT_FILENAME = "watchfolder_snapshot.json"


def load_combined_snapshot(snapshot_folder: str) -> dict:
    """Load the combined snapshot file from the configured folder.

    Returns the full structure or an empty dict if not found / invalid.
    """
    if not snapshot_folder:
        return {}
    p = Path(snapshot_folder) / SNAPSHOT_FILENAME
    if not p.is_file():
        return {}
    try:
        with open(p, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == 1:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_combined_snapshot(snapshot_folder: str, layer: int, folder_path: str,
                           merged_snapshot: list[dict],
                           composition_name: str = ""):
    """Update a single layer's data in the combined snapshot file.

    Reads the existing file, updates the specified layer, writes back.
    Only entries with data are written (empty slots are skipped).
    """
    if not snapshot_folder:
        return
    dest = Path(snapshot_folder)
    if not dest.is_dir():
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

    filepath = dest / SNAPSHOT_FILENAME

    # Read existing
    combined = load_combined_snapshot(snapshot_folder)
    if not combined:
        combined = {"version": 1, "layers": {}}

    # Update metadata
    combined["composition"] = composition_name
    combined["timestamp"] = datetime.now().isoformat(timespec="seconds")

    # Update this layer (only entries with data)
    clips = [e for e in merged_snapshot if e.get("filename") and e.get("data")]
    combined.setdefault("layers", {})[str(layer)] = {
        "folder": folder_path,
        "clips": clips,
    }

    # Write
    try:
        with open(filepath, "w") as f:
            json.dump(combined, f, indent=2)
    except OSError:
        pass


def get_cross_layer_entries(snapshot_folder: str, exclude_layer: int) -> list[dict]:
    """Load snapshot entries from ALL other layers in the combined file.

    Used for cross-layer restore when a clip moves between folders.
    """
    combined = load_combined_snapshot(snapshot_folder)
    entries = []
    for lyr, data in combined.get("layers", {}).items():
        if str(lyr) != str(exclude_layer):
            entries.extend(data.get("clips", []))
    return entries


def merge_with_combined(config_snap: list[dict] | None,
                        snapshot_folder: str,
                        layer: int) -> list[dict] | None:
    """Merge config snapshot with combined file data.

    Config entries take priority. Combined file supplements with
    entries for filenames not already in the config snapshot.
    """
    if not snapshot_folder:
        return config_snap

    combined = load_combined_snapshot(snapshot_folder)
    layer_data = combined.get("layers", {}).get(str(layer))
    if not layer_data:
        return config_snap

    combined_clips = layer_data.get("clips", [])
    if not combined_clips:
        return config_snap

    if not config_snap:
        return combined_clips

    # Config filenames take priority
    config_filenames = {e["filename"] for e in config_snap if e.get("filename")}
    merged = list(config_snap)
    for entry in combined_clips:
        if entry.get("filename") and entry["filename"] not in config_filenames:
            merged.append(entry)
    return merged


def restore_snapshot(api: ArenaAPI, layer: int, snapshot: list[dict],
                     only_filenames: set[str] | None = None,
                     include_remembered: bool = False):
    """Restore clip settings from a snapshot to the current layer state.

    Delegates to restore.py which handles both WebSocket-based (preferred)
    and REST-based (fallback) effect restoration.

    Args:
        only_filenames: When provided, only restore clips whose filename
                        is in this set.  Other clips are left untouched.
        include_remembered: When True, also restore generated sources marked
                        as remembered (used during force sync).
    """
    from restore import restore_snapshot as _restore

    # Try to set up a WebSocket connection for precise parameter-by-ID restore
    ws = None
    try:
        from arena_ws import ArenaWebSocket
        ws = ArenaWebSocket(host=api.host, port=api.port, logger=log)
        if not ws.connect():
            ws = None
    except Exception:
        ws = None

    try:
        _restore(api, layer, snapshot, ws=ws, logger=log,
                 only_filenames=only_filenames,
                 include_remembered=include_remembered)
    finally:
        if ws:
            ws.close()


# ---------------------------------------------------------------------------
# Core sync logic — SMART SYNC (incremental, preserves effects)
# ---------------------------------------------------------------------------

def rename_layer_to_folder(api: ArenaAPI, folder: str, layer: int):
    """Rename an Arena layer to match the mapped folder name."""
    folder_name = Path(folder).name
    if folder_name:
        try:
            api.set_layer_name(layer, folder_name)
            log(f"  Renamed layer {layer} to '{folder_name}'")
        except Exception as exc:
            log(f"  Warning: could not rename layer {layer}: {exc}")


def collect_layer_to_folder(api: ArenaAPI, layer: int, dest_folder: str) -> dict:
    """Copy all clip files from an Arena layer into a local folder.

    Returns {copied: [filenames], skipped: int, sources: int, errors: []}.
    Skips generated sources (no file path). Handles filename collisions.
    """
    clips = api.get_layer_clips(layer)
    dest = Path(dest_folder)
    dest.mkdir(parents=True, exist_ok=True)

    copied = []
    skipped = 0
    sources = 0
    errors = []
    seen_names = {}

    for clip in clips:
        src_path = clip["path"]
        if not src_path:
            if clip.get("data"):
                # Generated source — no file but has clip data
                name = _extract_clip_name(clip["data"]) or "unknown source"
                log(f"    Source (no file): {name}")
                sources += 1
            else:
                skipped += 1
            continue

        src_path = normalize_path(src_path)
        src = Path(src_path)

        if not src.is_file():
            errors.append(f"Source not found: {src}")
            continue

        base = src.stem
        ext = src.suffix
        name = src.name
        if name in seen_names:
            seen_names[name] += 1
            name = f"{base}_{seen_names[name]}{ext}"
        else:
            seen_names[name] = 1

        dst = dest / name
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            copied.append(name)
            log(f"    Already present: {name}")
            continue

        try:
            shutil.copy2(str(src), str(dst))
            copied.append(name)
            log(f"    Copied: {name}")
        except OSError as e:
            errors.append(f"Failed to copy {src.name}: {e}")
            log(f"    ERROR copying {src.name}: {e}")

    return {"copied": copied, "skipped": skipped, "sources": sources, "errors": errors}


def sync_folder_to_layer(api: ArenaAPI, folder: str, layer: int,
                         dry_run: bool = False, force_full: bool = False,
                         snapshot: list[dict] | None = None) -> dict:
    """Incremental sync: only add/remove changed clips, preserving effects.

    If force_full=True, falls back to the destructive clear-all-and-reload.
    Returns dict: {files, added, removed, returning}.
    'returning' lists filenames of newly-added clips that have saved snapshot data.
    """
    files = scan_folder(folder)

    if not files:
        log("  No media files found in folder.")
        return {"files": [], "added": [], "removed": [], "returning": []}

    log(f"  Found {len(files)} media file(s)")

    if dry_run:
        for f in files:
            log(f"    . {Path(f).name}")
        log("  [DRY RUN] -- no changes made.")
        return {"files": files, "added": [], "removed": [], "returning": []}

    # Ensure enough columns
    current_cols = api.get_column_count()
    if len(files) > current_cols:
        log(f"  Expanding columns: {current_cols} -> {len(files)}")
        api.grow_columns(len(files))

    # --- Force full (destructive) sync ---
    if force_full:
        layer_name = api.get_layer_name(layer)
        log(f"  Full re-sync: clearing all clips on {layer_name}...")
        api.clear_layer_clips(layer)
        pairs = [(i, f) for i, f in enumerate(files, start=1)]
        log(f"  Loading {len(files)} clip(s)...")
        api.batch_open_clips(layer, pairs)
        log("  Sync complete!")
        return {"files": files, "added": [f for _, f in pairs], "removed": [], "returning": []}

    # --- Smart (incremental) sync ---
    arena_clips = api.get_layer_clips(layer)

    # Build maps: normalized_path -> slot for current Arena state
    arena_by_path = {}
    for clip in arena_clips:
        np = normalize_path(clip["path"])
        if np:
            arena_by_path[np] = clip["slot"]

    # Build desired state: normalized_path -> desired slot (alphabetical)
    desired_by_path = {}
    for i, f in enumerate(files, start=1):
        desired_by_path[normalize_path(f)] = i

    arena_paths = set(arena_by_path.keys())
    desired_paths = set(desired_by_path.keys())

    to_remove = arena_paths - desired_paths
    to_add = desired_paths - arena_paths
    unchanged = arena_paths & desired_paths

    if not to_remove and not to_add:
        log("  Already in sync -- nothing to do.")
        return {"files": files, "added": [], "removed": [], "returning": []}

    log(f"  Smart sync: +{len(to_add)} new, -{len(to_remove)} removed, {len(unchanged)} unchanged")

    # Log unchanged clips and their slot positions for debugging
    if unchanged:
        unchanged_slots = sorted([arena_by_path[p] for p in unchanged])
        log(f"  Unchanged clip slots: {unchanged_slots}")

    # Clear removed clips
    for path in to_remove:
        slot = arena_by_path[path]
        log(f"    - Clearing slot {slot}: {Path(path).name}")
        api.clear_clip(layer, slot)

    # Find available slots for new files
    freed_slots = sorted([arena_by_path[p] for p in to_remove])
    empty_slots = sorted([c["slot"] for c in arena_clips if c["path"] is None])
    available_slots = sorted(set(freed_slots + empty_slots))

    log(f"  Slot info: {len(arena_clips)} total, freed={freed_slots}, empty={empty_slots}, available={available_slots}")

    # If we don't have enough available slots, ensure we have enough columns
    if len(to_add) > len(available_slots):
        needed_extra = len(to_add) - len(available_slots)
        total_needed = len(arena_clips) + needed_extra
        log(f"  Need {needed_extra} more slot(s), ensuring {total_needed} columns")
        api.grow_columns(total_needed)
        # Re-read to get updated slot count
        arena_clips_after = api.get_layer_clips(layer)
        new_empty = sorted([c["slot"] for c in arena_clips_after
                           if c["path"] is None and c["slot"] not in available_slots])
        available_slots = sorted(set(available_slots + new_empty))
        log(f"  After grow: {len(arena_clips_after)} slots, available now={available_slots}")

    # Assign new files to available slots
    new_files_sorted = sorted(to_add)
    load_pairs = []
    for i, fpath in enumerate(new_files_sorted):
        if i < len(available_slots):
            slot = available_slots[i]
        else:
            slot = len(arena_clips) + 1 + (i - len(available_slots))
            log(f"  WARNING: Using overflow slot {slot} (may not exist)")
        log(f"    + Loading slot {slot}: {Path(fpath).name}")
        load_pairs.append((slot, fpath))

    if load_pairs:
        try:
            api.batch_open_clips(layer, load_pairs)
        except Exception as exc:
            log(f"  WARNING: Batch load failed ({exc}), trying individual loads...")
            for slot, fpath in load_pairs:
                try:
                    api.open_clip(layer, slot, fpath)
                except Exception as exc2:
                    log(f"    ERROR: Could not load slot {slot}: {exc2}")

    # Verify clips were actually loaded
    if load_pairs:
        time.sleep(0.5)  # give Arena a moment to process
        verify_clips = api.get_layer_clips(layer)
        loaded_slots = {c["slot"] for c in verify_clips if c["path"] is not None}
        expected_slots = {slot for slot, _ in load_pairs}
        missing = expected_slots - loaded_slots
        if missing:
            log(f"  WARNING: {len(missing)} clip(s) failed to load in slots: {sorted(missing)}")
            # Try loading missing clips individually
            for slot, fpath in load_pairs:
                if slot in missing:
                    log(f"    Retrying slot {slot}: {Path(fpath).name}")
                    try:
                        api.open_clip(layer, slot, fpath)
                    except Exception as exc:
                        log(f"    ERROR: Retry failed for slot {slot}: {exc}")

    # Detect returning clips (new files that have saved snapshot settings)
    returning = []
    if snapshot and to_add:
        snap_filenames = {e["filename"] for e in snapshot if e.get("filename")}
        for path in sorted(to_add):
            fname = Path(path).name
            if fname in snap_filenames:
                returning.append(fname)
        if returning:
            log(f"  {len(returning)} returning clip(s) with saved settings detected")

    log("  Sync complete!")
    return {
        "files": files,
        "added": [p for _, p in load_pairs],
        "removed": [Path(p).name for p in to_remove],
        "returning": returning,
    }


# ---------------------------------------------------------------------------
# Watch mode (continuous)
# ---------------------------------------------------------------------------

def watch_folder(api: ArenaAPI, folder: str, layer: int, stop_flag=None,
                 snapshot_getter=None, snapshot_saver=None,
                 rename_layer=False, composition_checker=None,
                 cross_layer_getter=None):
    """Continuously monitor the folder and re-sync when changes are detected.

    snapshot_getter:      optional callable returning the current snapshot for auto-restore.
    snapshot_saver:       optional callable(snap) to persist a new snapshot after sync.
    rename_layer:         if True, rename the layer to the folder name after each sync.
    composition_checker:  optional callable() -> (ok, error_msg). When ok is False,
                          the sync iteration is skipped (paused) until ok returns True.
    cross_layer_getter:   optional callable() -> list[dict]. Returns snapshot entries
                          from OTHER layers (for cross-layer restore of moved clips).
    """
    log(f"\n  WATCH MODE -- monitoring '{folder}' every {POLL_INTERVAL}s")
    if not stop_flag:
        log("  Press Ctrl+C to stop.\n")

    last_snapshot = None
    _lock_warned = False  # only warn once about composition mismatch

    def _should_stop():
        return stop_flag and stop_flag()

    def _composition_ok():
        """Check composition lock. Returns True if sync is allowed."""
        nonlocal _lock_warned
        if not composition_checker:
            return True
        ok, err = composition_checker()
        if not ok:
            if not _lock_warned:
                log(f"  PAUSED: {err}")
                _lock_warned = True
            return False
        if _lock_warned:
            log("  Lock check passed — resuming watch")
            _lock_warned = False
        return True

    def _sync_and_auto_restore():
        """Save settings → sync → recreate duplicates → restore → cross-layer → save."""
        from collections import Counter

        # 1) Save current settings before sync (merge to keep removed clips)
        if snapshot_saver:
            try:
                old_snap = snapshot_getter() if snapshot_getter else None
                pre_snap = snapshot_layer(api, layer)
                snapshot_saver(merge_snapshots(old_snap, pre_snap))
                clip_count = sum(1 for e in pre_snap if e["filename"])
                log(f"  Auto-saved settings before sync ({clip_count} clips)")
            except Exception:
                pass

        # 2) Sync (with snapshot for returning-clip detection)
        snap = snapshot_getter() if snapshot_getter else None
        result = sync_folder_to_layer(api, folder, layer, snapshot=snap)

        # Rename layer to folder name if option is enabled
        if rename_layer:
            rename_layer_to_folder(api, folder, layer)

        # 2b) Recreate duplicate clips from snapshot
        #     If the snapshot had N copies of a file but sync only created 1,
        #     open extra copies in their original slots.
        if snap:
            # Count instances in snapshot (only entries with slot + data)
            snap_counts = Counter(
                e["filename"] for e in snap
                if e.get("filename") and e.get("data") and e.get("slot") is not None
            )
            # Count instances currently on layer
            current_clips = api.get_layer_clips(layer)
            layer_counts = Counter(
                Path(c["path"]).name for c in current_clips if c["path"]
            )
            for filename, snap_count in snap_counts.items():
                layer_count = layer_counts.get(filename, 0)
                extras = snap_count - layer_count
                if extras <= 0:
                    continue
                # Find source file path from current layer
                source_path = next(
                    (c["path"] for c in current_clips
                     if c["path"] and Path(c["path"]).name == filename),
                    None,
                )
                if not source_path:
                    continue
                # Get original slot positions from snapshot
                original_slots = [
                    e["slot"] for e in snap
                    if e.get("filename") == filename and e.get("slot") is not None
                ]
                # Exclude slots already occupied by this file
                occupied_slots = {
                    c["slot"] for c in current_clips
                    if c["path"] and Path(c["path"]).name == filename
                }
                preferred_slots = [s for s in original_slots if s not in occupied_slots]

                # Grow columns if needed
                max_slot = max(original_slots) if original_slots else 0
                total_needed = max(max_slot, len(current_clips) + extras)
                api.grow_columns(total_needed)

                # Open extra copies
                for i in range(extras):
                    if preferred_slots:
                        slot = preferred_slots.pop(0)
                    else:
                        # Find next empty slot
                        refreshed = api.get_layer_clips(layer)
                        occupied = {c["slot"] for c in refreshed if c["path"]}
                        slot = next(
                            (c["slot"] for c in refreshed if c["slot"] not in occupied),
                            len(refreshed) + 1,
                        )
                    try:
                        api.open_clip(layer, slot, source_path)
                    except Exception as exc:
                        log(f"    Warning: could not recreate duplicate in slot {slot}: {exc}")
                log(f"  Recreated {extras} duplicate(s) of {filename}")

        # 3) Auto-restore returning clips (only the ones that were re-added)
        #    Re-read snap in case duplicates were added above
        snap = snapshot_getter() if snapshot_getter else snap
        if result.get("returning") and snap:
            returning = set(result["returning"])
            log(f"  Auto-restoring settings for {len(returning)} returning clip(s)...")
            restore_snapshot(api, layer, snap, only_filenames=returning)

        # 3b) Cross-layer restore for transferred clips
        #     Files that are newly added but NOT returning = moved from another layer
        if cross_layer_getter and result.get("added"):
            added_names = {Path(p).name for p in result["added"]}
            returning_names = set(result.get("returning", []))
            transferred = added_names - returning_names
            if transferred:
                cross_entries = cross_layer_getter()
                if cross_entries:
                    # Filter to only entries for transferred filenames
                    relevant = [e for e in cross_entries
                                if e.get("filename") in transferred and e.get("data")]
                    if relevant:
                        log(f"  Cross-layer restore: {len(transferred)} transferred clip(s)...")
                        restore_snapshot(api, layer, relevant,
                                         only_filenames=transferred)

        # 4) Save settings after sync (merge to keep removed clips)
        if snapshot_saver:
            try:
                current_snap = snapshot_getter() if snapshot_getter else None
                post_snap = snapshot_layer(api, layer)
                snapshot_saver(merge_snapshots(current_snap, post_snap))
                log(f"  Auto-saved settings after sync")
            except Exception:
                pass

        return result

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class Handler(FileSystemEventHandler):
            def __init__(self):
                self.changed = False

            def on_any_event(self, event):
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

        last_snapshot = set(scan_folder(folder))
        if _composition_ok():
            _sync_and_auto_restore()

        try:
            while not _should_stop():
                time.sleep(POLL_INTERVAL)
                if handler.changed:
                    handler.changed = False
                    current = set(scan_folder(folder))
                    if current != last_snapshot:
                        if not _composition_ok():
                            continue  # pause — don't update last_snapshot
                        added = current - last_snapshot
                        removed = last_snapshot - current
                        if added:
                            log(f"\n  + {len(added)} file(s) added")
                        if removed:
                            log(f"\n  - {len(removed)} file(s) removed")
                        log("  Re-syncing...")
                        _sync_and_auto_restore()
                        last_snapshot = current
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()
            observer.join()
            log("\n  Watch stopped.")

    except ImportError:
        log("  watchdog not installed -- using polling fallback")
        log("  (Install 'watchdog' for more efficient watching: pip install watchdog)\n")

        last_snapshot = set(scan_folder(folder))
        if _composition_ok():
            _sync_and_auto_restore()

        try:
            while not _should_stop():
                time.sleep(POLL_INTERVAL)
                current = set(scan_folder(folder))
                if current != last_snapshot:
                    if not _composition_ok():
                        continue  # pause — don't update last_snapshot
                    added = current - last_snapshot
                    removed = last_snapshot - current
                    if added:
                        log(f"\n  + {len(added)} file(s) added")
                    if removed:
                        log(f"\n  - {len(removed)} file(s) removed")
                    log("  Re-syncing...")
                    _sync_and_auto_restore()
                    last_snapshot = current
        except KeyboardInterrupt:
            log("\n  Watch stopped.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_avc_files(folder: str) -> list:
    """List .avc composition names (without extension) in *folder*.

    Attempt 1 — direct ``Path.iterdir()`` (works everywhere unless blocked).
    Attempt 2 — platform-specific subprocess fallback:
        macOS:   ``osascript 'do shell script "ls …"'`` (bypasses TCC)
        Windows: ``dir /b …`` via subprocess
    """
    if not folder:
        return []

    # --- Attempt 1: direct listing (cross-platform) ---
    try:
        p = Path(folder)
        if p.is_dir():
            names = []
            for f in sorted(p.iterdir()):
                if f.suffix.lower() == ".avc" and not f.name.startswith("."):
                    names.append(f.stem)
            if names:
                return names
    except (PermissionError, OSError):
        pass  # TCC or other OS restriction — try fallback

    # --- Attempt 2: platform-specific subprocess fallback ---
    import subprocess

    if platform.system() == "Darwin":
        # macOS: osascript bypasses TCC restrictions on ~/Documents
        try:
            escaped = folder.replace("\\", "\\\\").replace('"', '\\"')
            script = f'do shell script "ls \\"{escaped}\\""'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                names = []
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line.lower().endswith(".avc") and not line.startswith("."):
                        names.append(line[:-4])
                return sorted(names)
        except Exception:
            pass

    elif platform.system() == "Windows":
        # Windows: dir /b lists filenames in a directory
        try:
            result = subprocess.run(
                ["cmd", "/c", "dir", "/b", folder],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                names = []
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line.lower().endswith(".avc"):
                        names.append(line[:-4])
                return sorted(names)
        except Exception:
            pass

    return []


# ---------------------------------------------------------------------------
# Web UI (Flask)
# ---------------------------------------------------------------------------

def create_web_app(desktop_mode=False):
    """Create and return the Flask application for the web UI."""
    from config import load_config, save_config

    app = Flask(__name__)

    saved = load_config()

    # Shared state — now supports sets with multiple mappings
    _state = {
        "api": None,
        "host": saved.get("host", "127.0.0.1"),
        "port": saved.get("port", 8080),
        "sets": [],
        "active_set_id": saved.get("active_set_id", "1"),
        "next_id": 1,
        "desktop_mode": desktop_mode,
        "options": saved.get("options", {"rename_layers": False}),
        "locked_composition": saved.get("locked_composition"),
        "locked_deck": saved.get("locked_deck"),
    }

    # Restore sets from config
    for s in saved.get("sets", []):
        set_entry = {
            "id": s["id"],
            "name": s["name"],
            "mappings": [],
            "snapshots": s.get("snapshots", {}),
        }
        for m in s.get("mappings", []):
            set_entry["mappings"].append({
                "id": m["id"],
                "folder": m["folder"],
                "layer": m["layer"],
                "watching": False,
                "watch_thread": None,
            })
            _state["next_id"] = max(_state["next_id"], int(m["id"]) + 1)
        _state["next_id"] = max(_state["next_id"], int(s["id"]) + 1)
        _state["sets"].append(set_entry)

    # Create a default set if none exist
    if not _state["sets"]:
        _state["sets"].append({
            "id": "1",
            "name": "Default",
            "mappings": [],
            "snapshots": {},
        })
        _state["next_id"] = 2

    # Auto-connect to Arena on startup using saved host/port
    try:
        _state["api"] = ArenaAPI(
            host=_state["host"], port=_state["port"],
        )
        log(f"  Auto-connected to Arena at {_state['host']}:{_state['port']}")
    except Exception:
        _state["api"] = None
        log("  Arena not reachable — connect manually")

    def _next_id():
        nid = str(_state["next_id"])
        _state["next_id"] += 1
        return nid

    def _find_set(set_id):
        return next((s for s in _state["sets"] if s["id"] == set_id), None)

    def _active_set():
        return _find_set(_state["active_set_id"])

    def _find_mapping(set_entry, mapping_id):
        return next((m for m in set_entry["mappings"] if m["id"] == mapping_id), None)

    def _serialize_set(s):
        return {
            "id": s["id"],
            "name": s["name"],
            "mappings": [
                {"id": m["id"], "folder": m["folder"], "layer": m["layer"], "watching": m["watching"]}
                for m in s["mappings"]
            ],
            "has_snapshots": bool(s.get("snapshots")),
        }

    def _save():
        save_config({
            "host": _state["host"],
            "port": _state["port"],
            "active_set_id": _state["active_set_id"],
            "options": _state["options"],
            "locked_composition": _state.get("locked_composition"),
            "locked_deck": _state.get("locked_deck"),
            "sets": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "mappings": [
                        {"id": m["id"], "folder": m["folder"], "layer": m["layer"]}
                        for m in s["mappings"]
                    ],
                    "snapshots": s.get("snapshots", {}),
                }
                for s in _state["sets"]
            ],
        })

    # --- Composition lock guard ---

    def _check_composition_lock():
        """Check if the composition lock allows syncing.

        Returns (ok, error_msg).  ok=True means proceed.
        """
        if not _state["options"].get("composition_lock"):
            return True, None
        locked = _state.get("locked_composition")
        if not locked:
            return True, None
        if not _state["api"]:
            return False, "Cannot verify composition: not connected to Arena"
        try:
            current = _state["api"].get_composition_name()
        except Exception as e:
            return False, f"Cannot verify composition: {e}"
        if current != locked:
            return False, f"Composition mismatch: expected '{locked}', Arena has '{current}'"
        return True, None

    def _check_deck_lock():
        """Check if the deck lock allows syncing.

        Returns (ok, error_msg).  ok=True means proceed.
        """
        locked_deck = _state.get("locked_deck")
        if not locked_deck:
            return True, None  # no deck locked — always OK
        if not _state["api"]:
            return False, "Cannot verify deck: not connected to Arena"
        try:
            current = _state["api"].get_selected_deck()
        except Exception as e:
            return False, f"Cannot verify deck: {e}"
        if current != locked_deck:
            return False, f"Deck mismatch: expected '{locked_deck}', Arena has '{current}'"
        return True, None

    def _check_all_locks():
        """Check both composition lock and deck lock.

        Returns (ok, error_msg).  ok=True means proceed.
        """
        ok, err = _check_composition_lock()
        if not ok:
            return ok, err
        ok, err = _check_deck_lock()
        if not ok:
            return ok, err
        return True, None

    # --- Routes ---

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/mode")
    def mode():
        return jsonify({"desktop": _state["desktop_mode"]})

    @app.route("/api/browse")
    def browse_folders():
        """List directories at a given path for the folder browser."""
        req_path = flask_request.args.get("path", "")
        if not req_path:
            req_path = str(Path.home())
        p = Path(req_path).resolve()
        if not p.is_dir():
            return jsonify({"ok": False, "error": "Not a directory"}), 400
        dirs = []
        permission_error = False
        try:
            for entry in sorted(p.iterdir()):
                if entry.is_dir() and not entry.name.startswith("."):
                    dirs.append(entry.name)
        except PermissionError:
            permission_error = True
        # Count media files in this folder
        media_count = 0
        try:
            for entry in p.iterdir():
                if entry.is_file() and entry.suffix.lower() in MEDIA_EXTENSIONS:
                    media_count += 1
        except PermissionError:
            permission_error = True
        return jsonify({
            "ok": True,
            "path": str(p),
            "parent": str(p.parent) if p != p.parent else None,
            "dirs": dirs,
            "media_count": media_count,
            "permission_error": permission_error,
        })

    @app.route("/api/options", methods=["GET"])
    def get_options():
        return jsonify(_state["options"])

    @app.route("/api/options", methods=["PUT"])
    def set_options():
        data = flask_request.get_json(silent=True) or {}
        _state["options"].update(data)
        _save()
        return jsonify({"ok": True})

    @app.route("/api/composition-lock", methods=["GET"])
    def get_composition_lock():
        return jsonify({
            "enabled": _state["options"].get("composition_lock", False),
            "locked_composition": _state.get("locked_composition"),
            "compositions_folder": _state["options"].get("compositions_folder", ""),
            "snapshot_folder": _state["options"].get("snapshot_folder", ""),
        })

    @app.route("/api/composition-lock", methods=["PUT"])
    def set_composition_lock():
        data = flask_request.get_json(silent=True) or {}
        enabled = data.get("enabled", False)
        _state["options"]["composition_lock"] = enabled
        if enabled:
            comp_name = data.get("composition")
            if comp_name:
                _state["locked_composition"] = comp_name
                log(f"  Composition lock enabled: '{comp_name}'")
            elif _state["api"]:
                # Auto-detect current composition name
                try:
                    name = _state["api"].get_composition_name()
                    _state["locked_composition"] = name
                    log(f"  Composition lock enabled: '{name}'")
                except Exception:
                    _state["locked_composition"] = None
        else:
            _state["locked_composition"] = None
            log("  Composition lock disabled")
        _save()
        return jsonify({
            "ok": True,
            "locked_composition": _state.get("locked_composition"),
        })

    @app.route("/api/decks", methods=["GET"])
    def list_decks():
        """Return the list of decks in the current composition."""
        if not _state["api"]:
            return jsonify({"ok": True, "decks": [], "locked_deck": _state.get("locked_deck")})
        try:
            decks = _state["api"].get_decks()
        except Exception:
            decks = []

        # Auto-clear deck lock if the locked deck no longer exists
        locked = _state.get("locked_deck")
        if locked and decks:
            deck_names = {d["name"] for d in decks}
            if locked not in deck_names:
                log(f"  Deck lock auto-cleared: '{locked}' not in current composition")
                _state["locked_deck"] = None
                _save()

        return jsonify({
            "ok": True,
            "decks": decks,
            "locked_deck": _state.get("locked_deck"),
        })

    @app.route("/api/deck-lock", methods=["PUT"])
    def set_deck_lock():
        data = flask_request.get_json(silent=True) or {}
        deck_name = data.get("deck")  # None or "" to clear
        if deck_name:
            _state["locked_deck"] = deck_name
            log(f"  Deck lock set: '{deck_name}'")
        else:
            _state["locked_deck"] = None
            log("  Deck lock cleared")
        _save()
        return jsonify({
            "ok": True,
            "locked_deck": _state.get("locked_deck"),
        })

    @app.route("/api/compositions", methods=["GET"])
    def list_compositions():
        """Return the current Arena composition name (and folder scan if possible)."""
        # 1) Get the currently loaded composition name from Arena
        current_name = None
        if _state["api"]:
            try:
                current_name = _state["api"].get_composition_name()
            except Exception:
                pass

        # 2) Try to scan the compositions folder for .avc files
        folder = _state["options"].get("compositions_folder", "")
        if not folder:
            from config import default_compositions_folder
            folder = default_compositions_folder()
            _state["options"]["compositions_folder"] = folder
            _save()
        files = _list_avc_files(folder)

        return jsonify({
            "ok": True,
            "compositions": files,
            "current": current_name,
            "folder": folder,
        })

    @app.route("/api/compositions-folder", methods=["PUT"])
    def set_compositions_folder():
        data = flask_request.get_json(silent=True) or {}
        folder = data.get("folder", "")
        _state["options"]["compositions_folder"] = folder
        _save()
        return jsonify({"ok": True})

    @app.route("/api/snapshot-folder", methods=["PUT"])
    def set_snapshot_folder():
        data = flask_request.get_json(silent=True) or {}
        folder = data.get("folder", "")
        _state["options"]["snapshot_folder"] = folder
        _save()
        return jsonify({"ok": True})

    @app.route("/api/connect", methods=["POST"])
    def connect():
        data = flask_request.get_json(silent=True) or {}
        host = data.get("host", "127.0.0.1")
        port = int(data.get("port", 8080))
        try:
            _state["api"] = ArenaAPI(host=host, port=port)
            _state["host"] = host
            _state["port"] = port
            _save()
            # Warn if composition/deck doesn't match lock
            ok, err = _check_all_locks()
            if not ok:
                log(f"  WARNING: {err}")
                return jsonify({"ok": True, "warning": err})
            return jsonify({"ok": True})
        except ArenaConnectionError as e:
            _state["api"] = None
            log(f"  ERROR: {e}")
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route("/api/status")
    def status():
        active = _active_set()
        return jsonify({
            "connected": _state["api"] is not None,
            "host": _state["host"],
            "port": _state["port"],
            "active_set_id": _state["active_set_id"],
            "sets": [_serialize_set(s) for s in _state["sets"]],
        })

    # --- Sets CRUD ---

    @app.route("/api/sets", methods=["POST"])
    def create_set():
        data = flask_request.get_json(silent=True) or {}
        new_set = {
            "id": _next_id(),
            "name": data.get("name", "New Set"),
            "mappings": [],
            "snapshots": {},
        }
        _state["sets"].append(new_set)
        # Auto-activate the new set (no lock check — it's empty)
        if data.get("activate"):
            _state["active_set_id"] = new_set["id"]
        _save()
        return jsonify({"ok": True, "set": _serialize_set(new_set)})

    @app.route("/api/sets/<set_id>", methods=["PUT"])
    def update_set(set_id):
        s = _find_set(set_id)
        if not s:
            return jsonify({"ok": False, "error": "Set not found"}), 404
        data = flask_request.get_json(silent=True) or {}
        if "name" in data:
            s["name"] = data["name"]
        _save()
        return jsonify({"ok": True, "set": _serialize_set(s)})

    @app.route("/api/sets/<set_id>", methods=["DELETE"])
    def delete_set(set_id):
        s = _find_set(set_id)
        if not s:
            return jsonify({"ok": False, "error": "Set not found"}), 404
        # Stop all watchers in this set
        for m in s["mappings"]:
            m["watching"] = False
        _state["sets"].remove(s)
        # If we deleted the active set, switch to first available
        if _state["active_set_id"] == set_id and _state["sets"]:
            _state["active_set_id"] = _state["sets"][0]["id"]
        _save()
        return jsonify({"ok": True})

    @app.route("/api/sets/<set_id>/activate", methods=["POST"])
    def activate_set(set_id):
        new_set = _find_set(set_id)
        if not new_set:
            return jsonify({"ok": False, "error": "Set not found"}), 404
        if not _state["api"]:
            return jsonify({"ok": False, "error": "Not connected to Arena"}), 400
        ok, err = _check_all_locks()
        if not ok:
            return jsonify({"ok": False, "error": err}), 409

        old_set = _active_set()

        # Stop all watchers in old set
        if old_set:
            for m in old_set["mappings"]:
                m["watching"] = False

        # Snapshot current layer states into old set
        sf = _state["options"].get("snapshot_folder", "")
        if old_set and _state["api"]:
            log(f"  Saving snapshots for '{old_set['name']}'...")
            for m in old_set["mappings"]:
                try:
                    snap = snapshot_layer(_state["api"], m["layer"])
                    old_set["snapshots"][str(m["layer"])] = snap
                    log(f"    Layer {m['layer']}: {sum(1 for s in snap if s['filename'])} clips saved")
                    if sf:
                        comp = _state.get("locked_composition", "")
                        save_combined_snapshot(sf, m["layer"], m["folder"],
                                              snap, comp)
                except Exception as e:
                    log(f"    Warning: could not snapshot layer {m['layer']}: {e}")

        # Switch to new set
        _state["active_set_id"] = set_id
        log(f"\n  Switching to set '{new_set['name']}'")

        # Sync all mappings in the new set
        for m in new_set["mappings"]:
            if m["folder"]:
                try:
                    log(f"  Syncing layer {m['layer']} <- {m['folder']}")
                    sync_folder_to_layer(_state["api"], m["folder"], m["layer"])

                    # Rename layer to folder name if option is enabled
                    if _state["options"].get("rename_layers"):
                        rename_layer_to_folder(_state["api"], m["folder"], m["layer"])

                    # Restore snapshot if available (merge with combined file)
                    layer_snap = merge_with_combined(
                        new_set["snapshots"].get(str(m["layer"])),
                        sf, m["layer"]
                    )
                    if layer_snap:
                        log(f"  Restoring settings for layer {m['layer']}...")
                        restore_snapshot(_state["api"], m["layer"], layer_snap)
                except Exception as e:
                    log(f"  ERROR syncing layer {m['layer']}: {e}")

        _save()
        log("  Set switch complete!")
        return jsonify({"ok": True})

    # --- Mappings CRUD (within active set) ---

    @app.route("/api/mappings", methods=["POST"])
    def add_mapping():
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        data = flask_request.get_json(silent=True) or {}
        mapping = {
            "id": _next_id(),
            "folder": data.get("folder", ""),
            "layer": int(data.get("layer", 1)),
            "watching": False,
            "watch_thread": None,
        }
        s["mappings"].append(mapping)
        _save()
        return jsonify({"ok": True, "mapping": {
            "id": mapping["id"], "folder": mapping["folder"],
            "layer": mapping["layer"], "watching": False,
        }})

    @app.route("/api/mappings/<mapping_id>", methods=["PUT"])
    def update_mapping(mapping_id):
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        m = _find_mapping(s, mapping_id)
        if not m:
            return jsonify({"ok": False, "error": "Mapping not found"}), 404
        data = flask_request.get_json(silent=True) or {}
        if "folder" in data:
            m["folder"] = data["folder"]
        if "layer" in data:
            old_layer = m["layer"]
            new_layer = int(data["layer"])
            if old_layer != new_layer:
                # Migrate snapshot to new layer key
                old_key = str(old_layer)
                new_key = str(new_layer)
                old_snap = s["snapshots"].get(old_key, [])
                new_snap = s["snapshots"].get(new_key, [])
                old_has_data = any(
                    e.get("filename") or e.get("source_name")
                    for e in old_snap
                )
                new_has_data = any(
                    e.get("filename") or e.get("source_name")
                    for e in new_snap
                )
                if old_has_data and not new_has_data:
                    s["snapshots"][new_key] = s["snapshots"].pop(old_key)
                    log(f"  Migrated snapshot from layer {old_layer} to {new_layer}")
                m["layer"] = new_layer
            else:
                m["layer"] = new_layer
        _save()
        return jsonify({"ok": True})

    @app.route("/api/mappings/<mapping_id>", methods=["DELETE"])
    def delete_mapping(mapping_id):
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        m = _find_mapping(s, mapping_id)
        if not m:
            return jsonify({"ok": False, "error": "Mapping not found"}), 404
        m["watching"] = False
        s["mappings"].remove(m)
        _save()
        return jsonify({"ok": True})

    @app.route("/api/mappings/<mapping_id>/sync", methods=["POST"])
    def sync_mapping(mapping_id):
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        m = _find_mapping(s, mapping_id)
        if not m:
            return jsonify({"ok": False, "error": "Mapping not found"}), 404
        if not _state["api"]:
            return jsonify({"ok": False, "error": "Not connected to Arena"}), 400
        ok, err = _check_all_locks()
        if not ok:
            return jsonify({"ok": False, "error": err}), 409
        data = flask_request.get_json(silent=True) or {}
        force = data.get("force", False)
        layer_key = str(m["layer"])
        try:
            old_snap = s["snapshots"].get(layer_key)
            sf = _state["options"].get("snapshot_folder", "")

            # For force sync, preserve the original snapshot for source
            # restoration BEFORE the pre-sync snapshot can overwrite
            # custom source settings with defaults.
            if force:
                layer_snap = merge_with_combined(old_snap, sf, m["layer"])

            # 1) Save current settings BEFORE sync (merge to keep removed clips)
            try:
                pre_snap = snapshot_layer(_state["api"], m["layer"])
                s["snapshots"][layer_key] = merge_snapshots(old_snap, pre_snap)
                clip_count = sum(1 for e in pre_snap if e["filename"])
                log(f"  Auto-saved settings before sync ({clip_count} clips)")
            except Exception:
                pass  # don't block sync if snapshot fails

            # For non-force sync, build layer_snap after merge
            if not force:
                layer_snap = merge_with_combined(
                    s["snapshots"].get(layer_key), sf, m["layer"]
                )

            # 2) Sync
            result = sync_folder_to_layer(
                _state["api"], m["folder"], m["layer"],
                force_full=force, snapshot=layer_snap,
            )

            # 2b) After force sync, re-create generated sources from snapshot
            #     Include remembered sources — they become remembered after merge
            #     since they're never in the folder, but we still want them restored.
            if force and layer_snap:
                source_entries = [
                    e for e in layer_snap
                    if e.get("source_name") and e.get("data") and e.get("slot")
                ]
                if source_entries:
                    log(f"  Restoring {len(source_entries)} generated source(s)...")
                    restore_snapshot(
                        _state["api"], m["layer"], layer_snap,
                        include_remembered=True,
                    )

            # Rename layer to folder name if option is enabled
            if _state["options"].get("rename_layers"):
                rename_layer_to_folder(_state["api"], m["folder"], m["layer"])

            returning = result.get("returning", [])

            if returning:
                # Returning clips detected — DON'T save yet!
                # The remembered settings are still in the snapshot.
                # Let the user choose: Restore or Keep Fresh.
                _save()
                return jsonify({"ok": True, "returning": returning})

            # 3) No returning clips — save settings after sync
            try:
                post_snap = snapshot_layer(_state["api"], m["layer"])
                s["snapshots"][layer_key] = merge_snapshots(
                    s["snapshots"].get(layer_key), post_snap,
                )
                log(f"  Auto-saved settings after sync")
            except Exception:
                pass

            _save()
            sf = _state["options"].get("snapshot_folder", "")
            if sf and s["snapshots"].get(layer_key):
                comp = _state.get("locked_composition", "")
                save_combined_snapshot(sf, m["layer"], m["folder"],
                                      s["snapshots"][layer_key], comp)
            return jsonify({"ok": True, "returning": []})
        except Exception as e:
            log(f"  ERROR: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/mappings/<mapping_id>/watch/start", methods=["POST"])
    def watch_start(mapping_id):
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        m = _find_mapping(s, mapping_id)
        if not m:
            return jsonify({"ok": False, "error": "Mapping not found"}), 404
        if not _state["api"]:
            return jsonify({"ok": False, "error": "Not connected to Arena"}), 400
        if m["watching"]:
            return jsonify({"ok": False, "error": "Already watching"}), 400
        ok, err = _check_all_locks()
        if not ok:
            return jsonify({"ok": False, "error": err}), 409

        m["watching"] = True

        layer_key = str(m["layer"])

        def _save_snap(snap):
            s["snapshots"][layer_key] = snap
            _save()
            # Also write to combined snapshot file
            sf = _state["options"].get("snapshot_folder", "")
            if sf:
                comp = _state.get("locked_composition", "")
                save_combined_snapshot(sf, m["layer"], m["folder"], snap, comp)

        def _get_snap():
            sf = _state["options"].get("snapshot_folder", "")
            return merge_with_combined(
                s["snapshots"].get(layer_key), sf, m["layer"]
            )

        def _get_cross_layer():
            sf = _state["options"].get("snapshot_folder", "")
            if not sf:
                return []
            return get_cross_layer_entries(sf, exclude_layer=m["layer"])

        def run_watch():
            try:
                watch_folder(
                    _state["api"], m["folder"], m["layer"],
                    stop_flag=lambda: not m["watching"],
                    snapshot_getter=_get_snap,
                    snapshot_saver=_save_snap,
                    rename_layer=_state["options"].get("rename_layers", False),
                    composition_checker=_check_all_locks,
                    cross_layer_getter=_get_cross_layer,
                )
            except Exception as e:
                log(f"  Watch error on layer {m['layer']}: {e}")
            finally:
                m["watching"] = False

        t = threading.Thread(target=run_watch, daemon=True)
        t.start()
        m["watch_thread"] = t
        return jsonify({"ok": True})

    @app.route("/api/mappings/<mapping_id>/watch/stop", methods=["POST"])
    def watch_stop(mapping_id):
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        m = _find_mapping(s, mapping_id)
        if not m:
            return jsonify({"ok": False, "error": "Mapping not found"}), 404
        m["watching"] = False
        log(f"  Stopping watch on layer {m['layer']}...")
        return jsonify({"ok": True})

    @app.route("/api/snapshot", methods=["POST"])
    def snapshot_all():
        """Manually snapshot ALL mappings at once to keep everything in sync."""
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        if not _state["api"]:
            return jsonify({"ok": False, "error": "Not connected to Arena"}), 400
        sf = _state["options"].get("snapshot_folder", "")
        comp = _state.get("locked_composition", "")
        total_clips = 0
        layers_saved = 0
        errors = []
        for m in s.get("mappings", []):
            try:
                layer_key = str(m["layer"])
                old_snap = s["snapshots"].get(layer_key)
                new_snap = snapshot_layer(_state["api"], m["layer"])
                s["snapshots"][layer_key] = merge_snapshots(old_snap, new_snap)
                clip_count = sum(1 for e in new_snap if e["filename"])
                total_clips += clip_count
                layers_saved += 1
                log(f"  Layer {m['layer']}: snapshot saved ({clip_count} clips)")
                if sf:
                    save_combined_snapshot(sf, m["layer"], m["folder"],
                                          s["snapshots"][layer_key], comp)
            except Exception as e:
                errors.append(f"Layer {m['layer']}: {e}")
                log(f"  ERROR snapshotting layer {m['layer']}: {e}")
        _save()
        if errors:
            return jsonify({"ok": True, "clips": total_clips,
                            "layers": layers_saved, "errors": errors})
        return jsonify({"ok": True, "clips": total_clips,
                        "layers": layers_saved})

    @app.route("/api/mappings/<mapping_id>/snapshot", methods=["POST"])
    def snapshot_mapping(mapping_id):
        """Manually snapshot a single layer."""
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        m = _find_mapping(s, mapping_id)
        if not m:
            return jsonify({"ok": False, "error": "Mapping not found"}), 404
        if not _state["api"]:
            return jsonify({"ok": False, "error": "Not connected to Arena"}), 400
        try:
            layer_key = str(m["layer"])
            old_snap = s["snapshots"].get(layer_key)
            new_snap = snapshot_layer(_state["api"], m["layer"])
            s["snapshots"][layer_key] = merge_snapshots(old_snap, new_snap)
            clip_count = sum(1 for e in new_snap if e["filename"])
            log(f"  Layer {m['layer']}: snapshot saved ({clip_count} clips)")
            _save()
            # Also write to combined snapshot file
            sf = _state["options"].get("snapshot_folder", "")
            if sf:
                comp = _state.get("locked_composition", "")
                save_combined_snapshot(sf, m["layer"], m["folder"],
                                      s["snapshots"][layer_key], comp)
            return jsonify({"ok": True, "clips": clip_count})
        except Exception as e:
            log(f"  ERROR: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/mappings/<mapping_id>/restore", methods=["POST"])
    def restore_mapping(mapping_id):
        """Restore a layer from its snapshot.

        Accepts optional JSON body:
            {"only": ["file1.mov", "file2.mov"]}
        to restrict restoration to specific clips (e.g. returning clips).
        Without "only", restores all clips on the layer.
        """
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        m = _find_mapping(s, mapping_id)
        if not m:
            return jsonify({"ok": False, "error": "Mapping not found"}), 404
        if not _state["api"]:
            return jsonify({"ok": False, "error": "Not connected to Arena"}), 400

        layer_key = str(m["layer"])
        sf = _state["options"].get("snapshot_folder", "")
        layer_snap = merge_with_combined(
            s["snapshots"].get(layer_key), sf, m["layer"]
        )
        if not layer_snap:
            return jsonify({"ok": False, "error": "No snapshot for this layer"}), 404
        try:
            data = flask_request.get_json(silent=True) or {}
            only = data.get("only")
            only_filenames = set(only) if only else None
            if only_filenames:
                log(f"  Restoring settings for {len(only_filenames)} returning clip(s) on layer {m['layer']}...")
            else:
                log(f"  Restoring settings for layer {m['layer']}...")
            restore_snapshot(_state["api"], m["layer"], layer_snap,
                             only_filenames=only_filenames)

            # Save after restore to capture the restored state
            try:
                post_snap = snapshot_layer(_state["api"], m["layer"])
                s["snapshots"][layer_key] = merge_snapshots(
                    s["snapshots"].get(layer_key), post_snap,
                )
                _save()
                if sf and s["snapshots"].get(layer_key):
                    comp = _state.get("locked_composition", "")
                    save_combined_snapshot(sf, m["layer"], m["folder"],
                                          s["snapshots"][layer_key], comp)
                log(f"  Settings saved after restore")
            except Exception:
                pass

            return jsonify({"ok": True})
        except Exception as e:
            log(f"  ERROR: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/mappings/<mapping_id>/keep-fresh", methods=["POST"])
    def keep_fresh(mapping_id):
        """User chose 'Keep Fresh' for returning clips — save current (fresh) state."""
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        m = _find_mapping(s, mapping_id)
        if not m:
            return jsonify({"ok": False, "error": "Mapping not found"}), 404
        if not _state["api"]:
            return jsonify({"ok": False, "error": "Not connected to Arena"}), 400
        try:
            layer_key = str(m["layer"])
            post_snap = snapshot_layer(_state["api"], m["layer"])
            s["snapshots"][layer_key] = merge_snapshots(
                s["snapshots"].get(layer_key), post_snap,
            )
            log(f"  Keeping fresh settings for returning clips")
            _save()
            sf = _state["options"].get("snapshot_folder", "")
            if sf and s["snapshots"].get(layer_key):
                comp = _state.get("locked_composition", "")
                save_combined_snapshot(sf, m["layer"], m["folder"],
                                      s["snapshots"][layer_key], comp)
            return jsonify({"ok": True})
        except Exception as e:
            log(f"  ERROR: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/collect-all", methods=["POST"])
    def collect_all():
        """Collect files from ALL Arena layers into auto-created folder structure.

        Scans every layer in the composition. Layers with clips get a folder
        and a mapping. Empty layers are skipped.

        Body: {"destination": "/path/to/root/folder"}
        Creates: <destination>/<composition>/<deck>/<layer_name>/
        """
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        if not _state["api"]:
            return jsonify({"ok": False, "error": "Not connected to Arena"}), 400

        data = flask_request.get_json(silent=True) or {}
        destination = data.get("destination", "").strip()
        if not destination:
            return jsonify({"ok": False, "error": "No destination folder specified"}), 400

        dest_root = Path(destination)
        try:
            dest_root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return jsonify({"ok": False, "error": f"Cannot create destination: {e}"}), 400

        api = _state["api"]
        comp_name = _sanitize_dirname(api.get_composition_name() or "Composition")
        deck_name = _sanitize_dirname(api.get_selected_deck() or "Deck 1")
        sf = _state["options"].get("snapshot_folder", "")
        comp = _state.get("locked_composition", "")
        num_layers = api.get_layer_count()

        results = []
        used_names = {}

        # Build lookup of existing mappings by layer number
        existing = {m["layer"]: m for m in s.get("mappings", [])}

        log(f"Collecting from {num_layers} Arena layers...")

        for layer in range(1, num_layers + 1):
            # Check if this layer has any loaded clips
            try:
                clips = api.get_layer_clips(layer)
            except Exception as e:
                log(f"  Skipping layer {layer}: {e}")
                continue
            loaded = [c for c in clips if c["path"]]
            if not loaded:
                log(f"  Layer {layer}: empty, skipping")
                continue

            layer_name = _sanitize_dirname(api.get_layer_name(layer))
            # Append counter if this name was already used
            if layer_name in used_names:
                used_names[layer_name] += 1
                layer_name = f"{layer_name} ({used_names[layer_name]})"
            else:
                used_names[layer_name] = 1

            layer_folder = dest_root / comp_name / deck_name / layer_name
            log(f"  Layer {layer} ({layer_name}): {len(loaded)} clips -> {layer_folder}")

            try:
                result = collect_layer_to_folder(api, layer, str(layer_folder))
                results.append({
                    "layer": layer, "layer_name": layer_name,
                    "folder": str(layer_folder),
                    "copied": len(result["copied"]),
                    "skipped": result["skipped"],
                    "errors": result["errors"],
                })
                # Save snapshot for this layer
                layer_key = str(layer)
                old_snap = s["snapshots"].get(layer_key)
                new_snap = snapshot_layer(api, layer)
                s["snapshots"][layer_key] = merge_snapshots(old_snap, new_snap)
                if sf:
                    save_combined_snapshot(sf, layer, str(layer_folder),
                                          s["snapshots"][layer_key], comp)
                # Create or update mapping for this layer
                if layer in existing:
                    existing[layer]["folder"] = str(layer_folder)
                else:
                    new_m = {"id": _next_id(), "folder": str(layer_folder),
                             "layer": layer}
                    s["mappings"].append(new_m)
                    existing[layer] = new_m
            except Exception as e:
                log(f"  ERROR collecting layer {layer}: {e}")
                results.append({"layer": layer, "layer_name": layer_name,
                                "folder": str(layer_folder),
                                "copied": 0, "skipped": 0, "errors": [str(e)]})

        # Write combined snapshot file into the collect destination folder
        collect_snap_dir = str(dest_root / comp_name / deck_name)
        for r in results:
            layer_num = r["layer"]
            layer_key = str(layer_num)
            snap_data = s["snapshots"].get(layer_key)
            if snap_data:
                m = existing.get(layer_num)
                folder_path = m["folder"] if m else r.get("folder", "")
                save_combined_snapshot(collect_snap_dir, layer_num, folder_path,
                                      snap_data, comp)

        _save()
        total = sum(r["copied"] for r in results)
        total_err = sum(len(r["errors"]) for r in results)
        log(f"Collect complete: {total} files copied, {total_err} errors")
        return jsonify({"ok": True, "results": results,
                        "total_copied": total})

    @app.route("/api/mappings/<mapping_id>/collect", methods=["POST"])
    def collect_mapping(mapping_id):
        """Collect files from a single Arena layer into the mapping's folder."""
        s = _active_set()
        if not s:
            return jsonify({"ok": False, "error": "No active set"}), 400
        m = _find_mapping(s, mapping_id)
        if not m:
            return jsonify({"ok": False, "error": "Mapping not found"}), 404
        if not _state["api"]:
            return jsonify({"ok": False, "error": "Not connected to Arena"}), 400
        if not m["folder"]:
            return jsonify({"ok": False, "error": "No folder path set"}), 400
        try:
            log(f"Collecting layer {m['layer']} -> {m['folder']}")
            result = collect_layer_to_folder(_state["api"], m["layer"], m["folder"])
            # Save snapshot after collecting
            layer_key = str(m["layer"])
            old_snap = s["snapshots"].get(layer_key)
            new_snap = snapshot_layer(_state["api"], m["layer"])
            s["snapshots"][layer_key] = merge_snapshots(old_snap, new_snap)
            _save()
            snap = s["snapshots"].get(layer_key, [])
            source_count = sum(1 for e in snap if e.get("source_name"))
            file_count = sum(1 for e in snap if e.get("filename"))
            if source_count or file_count:
                log(f"  Snapshot saved: {file_count} file(s), {source_count} source(s)")
            sf = _state["options"].get("snapshot_folder", "")
            if sf and snap:
                comp = _state.get("locked_composition", "")
                save_combined_snapshot(sf, m["layer"], m["folder"],
                                      snap, comp)
            return jsonify({"ok": True, "copied": len(result["copied"]),
                            "skipped": result["skipped"],
                            "sources": result["sources"],
                            "errors": result["errors"]})
        except Exception as e:
            log(f"  ERROR: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/shutdown", methods=["POST"])
    def shutdown():
        """Shut down the Flask server gracefully."""
        log("  Server shutdown requested from web UI.")
        # Stop all watchers
        for s in _state["sets"]:
            for m in s["mappings"]:
                m["watching"] = False
        # Schedule shutdown after response is sent
        def do_shutdown():
            time.sleep(0.5)
            os._exit(0)
        threading.Thread(target=do_shutdown, daemon=True).start()
        return jsonify({"ok": True})

    @app.route("/api/logs/history")
    def logs_history():
        """Return buffered log messages as JSON (for debugging)."""
        return jsonify(log_manager._messages)

    @app.route("/api/logs")
    def logs_stream():
        """SSE endpoint -- streams log messages to the browser."""
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
        description="Resolume Arena Watch Folder -- sync folders of media to layers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s --folder ~/Videos/SetA --layer 2
  %(prog)s --folder "C:\\Users\\VJ\\Clips" --layer 1 --watch
  %(prog)s --folder /media/show --layer 3 --host 192.168.1.100 --port 8080 --watch
  %(prog)s --ui
  %(prog)s --desktop
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
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Launch as desktop app with native window and system tray",
    )

    args = parser.parse_args()

    # --- Desktop mode ---
    if args.desktop:
        if not HAS_FLASK:
            print("ERROR: Flask is required for --desktop mode. Install it with:\n  pip install flask")
            sys.exit(1)
        try:
            from desktop import main as desktop_main
            desktop_main()
        except ImportError as e:
            print(f"ERROR: Desktop mode requires pywebview and pystray. Install with:")
            print(f"  pip install pywebview pystray Pillow")
            print(f"  (Error: {e})")
            sys.exit(1)
        return

    # --- Web UI mode ---
    if args.ui:
        if not HAS_FLASK:
            print("ERROR: Flask is required for --ui mode. Install it with:\n  pip install flask")
            sys.exit(1)
        app = create_web_app()
        print()
        print("+" + "=" * 48 + "+")
        print("|   Resolume Arena -- Watch Folder Sync (UI)     |")
        print("+" + "=" * 48 + "+")
        print()
        print(f"  Web UI -> http://127.0.0.1:{args.ui_port}")
        print()
        app.run(host="0.0.0.0", port=args.ui_port, debug=False, threaded=True)
        return

    # --- CLI mode (original behavior) ---
    if not args.folder:
        parser.error("--folder is required (unless using --ui or --desktop)")
    if args.layer is None:
        parser.error("--layer is required (unless using --ui or --desktop)")

    print()
    print("+" + "=" * 48 + "+")
    print("|   Resolume Arena -- Watch Folder Sync            |")
    print("+" + "=" * 48 + "+")
    print()
    print(f"  Folder : {Path(args.folder).resolve()}")
    print(f"  Layer  : {args.layer}")
    print(f"  Mode   : {'WATCH (continuous)' if args.watch else 'ONE-SHOT'}")
    print(f"  Arena  : {args.host}:{args.port}")
    print()

    if args.dry_run:
        print("  *** DRY RUN MODE -- no changes will be made ***\n")
        try:
            files = scan_folder(args.folder)
        except ValueError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        print(f"  Found {len(files)} media file(s):")
        for f in files:
            print(f"    . {Path(f).name}")
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
