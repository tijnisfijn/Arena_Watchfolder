# Arena Watchfolder — CLI Reference

Full command-line interface for scripting, automation, and LLM control.

> **Prerequisite:** Resolume Arena must be running with the web server enabled (Preferences → Webserver).

---

## Quick start

```bash
# 1. Check connection
python watchfolder.py status

# 2. Create a set (a named profile)
python watchfolder.py sets create "My Gig"

# 3. Add a folder→layer mapping
python watchfolder.py mappings add --folder ~/Videos/Loops --layer 1

# 4. Sync it
python watchfolder.py sync 3          # use the mapping ID from step 3

# 5. Save your clip settings (effects, speed, cue points)
python watchfolder.py snapshot save
```

---

## Global flags

These flags work on **every** subcommand:

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | off | Output JSON to stdout (logs go to stderr) |
| `--host` | `127.0.0.1` | Arena webserver host |
| `--port`, `-p` | `8080` | Arena webserver port |

Host and port are resolved in order: **explicit flag → config file → default**.

---

## Command reference

### `status`

Show connection state, active set, locks, and Arena info.

```bash
python watchfolder.py status
python watchfolder.py status --json
```

**Output fields:** `host`, `port`, `connected`, `composition`, `deck`, `layers`, `columns`, `active_set`, `mappings`, `sets`, `locked_composition`, `locked_deck`

---

### `sets` — Manage sets (profiles)

A **set** is a named collection of folder→layer mappings with their snapshots. Think of it as a profile for a gig or show.

```bash
python watchfolder.py sets list
python watchfolder.py sets create "Festival Night"
python watchfolder.py sets rename 2 "Festival Day"
python watchfolder.py sets delete 2
python watchfolder.py sets switch 2
```

| Subcommand | Arguments | Description |
|------------|-----------|-------------|
| `list` | — | List all sets with IDs and mapping counts |
| `create` | `<name>` | Create a new empty set |
| `rename` | `<set_id> <name>` | Rename an existing set |
| `delete` | `<set_id>` | Delete a set (cannot delete the last one) |
| `switch` | `<set_id>` | Snapshot the current set, switch, sync + restore the new one |

**`switch` workflow:** snapshots all mappings in the current set → activates the new set → syncs all its mappings → restores saved clip settings. This is a one-command gig changeover.

---

### `mappings` — Manage folder→layer mappings

Each mapping connects one folder on disk to one Arena layer.

```bash
python watchfolder.py mappings list
python watchfolder.py mappings add --folder ~/Videos/Loops --layer 1
python watchfolder.py mappings add --folder ~/Videos/BG --layer 2
python watchfolder.py mappings update 3 --layer 4
python watchfolder.py mappings remove 3
```

| Subcommand | Arguments | Description |
|------------|-----------|-------------|
| `list` | — | List all mappings in the active set |
| `add` | `--folder <path> --layer <N>` | Add a new mapping |
| `update` | `<mapping_id> [--folder] [--layer]` | Change folder or layer |
| `remove` | `<mapping_id>` | Remove a mapping and its snapshots |

---

### `sync` — Sync files to Arena

Push folder contents to an Arena layer. Files in the folder become clips; files not in the folder are removed from the layer.

```bash
# Sync a saved mapping (uses config)
python watchfolder.py sync 3

# Force full re-sync (clear + reload + restore all settings)
python watchfolder.py sync 3 --force

# Preview without changing Arena
python watchfolder.py sync 3 --dry-run

# One-off sync (no config needed)
python watchfolder.py sync --folder ~/Videos/Loops --layer 1
```

| Flag | Description |
|------|-------------|
| `mapping_id` | Mapping ID (from `mappings list`) |
| `--folder` | Folder path (one-off mode, no config needed) |
| `--layer` | Layer index, 1-based (one-off mode) |
| `--force` | Clear layer, reload all clips, restore all saved settings |
| `--dry-run` | Show what would happen without touching Arena |

**Sync handles snapshots automatically:** saves clip settings before sync, restores matching settings after sync, and saves again post-sync.

---

### `sync-all`

Sync every mapping in the active set, in order.

```bash
python watchfolder.py sync-all
```

---

### `watch` — Continuous file monitoring

Watch a folder for changes and auto-sync when files are added, removed, or modified. Press **Ctrl+C** to stop.

```bash
# Watch a saved mapping
python watchfolder.py watch 3

# One-off watch (no config needed)
python watchfolder.py watch --folder ~/Videos/Loops --layer 1
```

Watch mode respects composition and deck locks — it pauses when locks mismatch and resumes when the context is valid again.

---

### `snapshot` — Save and restore clip settings

Snapshots capture everything about your clips: effects, speed, cue points, blend modes, audio levels, and more. They persist across syncs.

```bash
# Save snapshots for all mappings
python watchfolder.py snapshot save

# Save snapshot for a single mapping
python watchfolder.py snapshot save 3

# Restore all settings for a mapping
python watchfolder.py snapshot restore 3

# Restore settings for specific clips only
python watchfolder.py snapshot restore 3 --only "loop1.mp4,loop2.mp4"
```

| Subcommand | Arguments | Description |
|------------|-----------|-------------|
| `save` | `[mapping_id]` | Save clip settings (all mappings if no ID given) |
| `restore` | `<mapping_id> [--only <files>]` | Restore saved settings |

---

### `collect` — Reverse sync (Arena → disk)

Copy clip source files from Arena back to your folder. Useful for backing up or reorganizing content.

```bash
# Collect clips for a single mapping
python watchfolder.py collect 3

# Collect ALL Arena layers into an organized folder structure
python watchfolder.py collect-all --destination ~/Backup
```

`collect-all` creates a folder structure: `<destination>/<composition>/<deck>/<layer_name>/`

---

### `lock` — Safety locks

Prevent accidental sync to the wrong composition or deck.

```bash
python watchfolder.py lock status
python watchfolder.py lock composition "My Show"
python watchfolder.py lock deck "Deck 1"
python watchfolder.py lock clear
```

| Subcommand | Arguments | Description |
|------------|-----------|-------------|
| `status` | — | Show current lock state and Arena's active composition/deck |
| `composition` | `<name>` | Block sync unless Arena has this composition loaded |
| `deck` | `<name>` | Block sync unless this deck is active |
| `clear` | — | Remove all locks |

When a lock is active, `sync`, `sync-all`, `watch`, and `sets switch` will **refuse to run** if the Arena state doesn't match.

---

### `config` — View and change settings

```bash
python watchfolder.py config show
python watchfolder.py config set host 192.168.1.100
python watchfolder.py config set port 8080
python watchfolder.py config set rename_layers true
python watchfolder.py config set snapshot_folder ~/Snapshots
```

| Key | Type | Description |
|-----|------|-------------|
| `host` | string | Arena webserver host |
| `port` | integer | Arena webserver port |
| `rename_layers` | boolean | Rename Arena layers to match folder names on sync |
| `composition_lock` | boolean | Enable/disable composition lock |
| `compositions_folder` | string | Path to compositions folder |
| `snapshot_folder` | string | Path for combined snapshot files |

Boolean values accept: `true`, `false`, `1`, `0`, `yes`.

---

## Legacy mode

The original flat-flag interface still works for simple one-off tasks:

```bash
python watchfolder.py --folder ~/Videos/MySet --layer 2
python watchfolder.py --folder ~/Videos/MySet --layer 2 --watch
python watchfolder.py --folder ~/Videos/MySet --layer 1 --dry-run
```

| Flag | Short | Description |
|------|-------|-------------|
| `--folder` | `-f` | Folder path |
| `--layer` | `-l` | Layer index (1-based) |
| `--watch` | `-w` | Continuous mode |
| `--dry-run` | — | Preview only |
| `--ui` | — | Launch web UI |
| `--ui-port` | — | Web UI port (default: 5000) |
| `--desktop` | — | Launch desktop app |

---

## LLM / automation guide

The CLI is designed to be fully controllable by LLMs with terminal access (Claude, ChatGPT, etc.) and by scripts.

### JSON output

Add `--json` to any command. Structured JSON goes to **stdout**, log messages go to **stderr**.

```bash
python watchfolder.py status --json
```

```json
{
  "host": "127.0.0.1",
  "port": 8080,
  "connected": true,
  "composition": "My Show",
  "deck": "Deck 1",
  "layers": 6,
  "columns": 20,
  "active_set": "Festival",
  "active_set_id": "1",
  "mappings": 3,
  "sets": 2,
  "locked_composition": null,
  "locked_deck": null
}
```

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Error (details in JSON `error` field or stderr) |

### Automation workflow example

```bash
#!/bin/bash
# Gig changeover script

WF="python watchfolder.py"

# 1. Lock to the right composition
$WF lock composition "Festival Main"
$WF lock deck "Deck 1"

# 2. Switch to the festival set
$WF sets switch 2

# 3. Verify everything synced
$WF status --json | python3 -c "
import json, sys
s = json.load(sys.stdin)
assert s['connected'], 'Not connected!'
print(f'Active: {s[\"active_set\"]} — {s[\"mappings\"]} mappings')
"
```

### LLM integration pattern

An LLM with terminal access can control the full workflow:

```
1. Run `watchfolder.py status --json` to understand current state
2. Run `watchfolder.py mappings list --json` to see what's configured
3. Run `watchfolder.py sync 3 --json` to sync a mapping
4. Parse the JSON response to verify success
5. Run `watchfolder.py snapshot save` to preserve settings
```

Every command returns a JSON object with either an `ok` field (success) or an `error` field (failure), making it easy to branch on results.

### Key JSON response patterns

**Success:**
```json
{ "ok": true, "id": "3", "name": "My Set" }
```

**Success with data:**
```json
{ "ok": true, "files": 12, "added": 3, "removed": 1 }
```

**Error:**
```json
{ "error": "Composition mismatch: expected 'My Show', Arena has 'Other'" }
```

**Lists:**
```json
{
  "sets": [
    { "id": "1", "name": "Default", "mappings": 2, "active": true },
    { "id": "2", "name": "Festival", "mappings": 4, "active": false }
  ]
}
```
