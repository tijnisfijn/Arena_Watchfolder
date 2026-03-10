# What's New in This Branch

> Branch: `feature/snapshot-and-lock-improvements`
> Base: `main`

This update adds safety locks, smarter clip restoration, cross-machine snapshot sharing, and a refreshed two-column UI layout. All changes are backward-compatible with existing configs.

---

## New Features

### 1. Composition Lock

Prevents syncing when the wrong composition is loaded in Arena.

**How it works:** Select a `.avc` file from the dropdown in Options. Before every sync, the app checks if Arena has that composition loaded. If not, the sync is blocked and watch mode pauses automatically until the correct composition is active again.

**Use case — Avoiding accidental overwrites:**
> You have two compositions: `Friday_Night.avc` and `Saturday_Night.avc`. You lock to `Friday_Night`. If someone opens `Saturday_Night` in Arena, the app refuses to sync — protecting your Saturday clips from being overwritten with Friday's media.

**Use case — Shared workstations:**
> Multiple VJs share one Arena machine. Each locks their Watchfolder to their own composition. No matter who's using Arena, clips only sync when the right composition is loaded.

---

### 2. Deck Lock

Prevents syncing when the wrong deck is active in Arena.

**How it works:** When a composition has multiple decks, a "Deck Lock" dropdown appears below the composition lock. Select which deck to lock to, or leave on "Any deck" to allow syncing regardless. The dropdown auto-hides for single-deck compositions.

**Use case — Multi-deck shows:**
> Your composition has a "Warmup" deck and a "Main Set" deck. You lock to "Main Set". During warmup, the app won't sync — your main set media stays untouched until you switch to the correct deck.

**Use case — Combined with composition lock:**
> Both locks work together. The app checks the composition first, then the deck. Both must match before any sync is allowed.

---

### 3. Save All Settings (Global Snapshot)

One button saves clip settings across all mappings at once, keeping everything in sync.

**How it works:** The "Save & Restore" card in the right column has a single "Save All Settings" button. Clicking it snapshots every mapping's layer simultaneously. Restore stays per-mapping (since you may want to restore just one layer).

**Use case — Pre-show checkpoint:**
> You've spent an hour tweaking effects on 3 layers. Hit "Save All Settings" once and all your work is captured — effects, speed, cue points, blend modes, everything. If something goes wrong during the show, restore any layer back to your saved state.

**Use case — Keeping layers in sync:**
> When you save all layers at the same moment, their snapshots reflect the exact same point in time. This matters when clips on different layers interact (e.g. a mask layer and a content layer that need matching effects).

---

### 4. Combined Snapshot File

All layer snapshots saved to a single portable JSON file for backup and cross-machine sharing.

**How it works:** Set a "Snapshot file location" in Options. Every time settings are saved (manually or on set switch), a `watchfolder_snapshot.json` file is written to that folder. It contains all layers, all clips, and all their settings in one document.

**Use case — Syncing between machines:**
> Main machine saves snapshots to a Dropbox folder. Backup machine points to the same Dropbox folder. If the main machine dies, the backup machine can restore all clip settings from the shared snapshot — even though it never had those settings locally.

**Use case — Version history:**
> Point the snapshot folder to a Git-tracked or cloud-synced directory. Every save creates a new version of the file that you can roll back to if needed.

---

### 5. Smarter Clip Matching

Clips are now matched by slot position first, then by name, then by order — solving the "duplicate clips get wrong effects" problem.

**How it works:** When restoring settings, the app tries three matching strategies in order:

1. **Slot match** — same filename in the same clip slot position (most accurate)
2. **Clip name match** — same filename with the same custom Arena clip name
3. **FIFO fallback** — first available entry for that filename (existing behavior)

**Use case — Multiple copies of the same file:**
> You have `robot.mov` loaded 4 times on one layer, each with different effects (Blur, Bloom, ChromaKey, Invert). After re-syncing, each copy lands back in its original slot and gets the correct effects — not random ones.

**Use case — Renamed clips:**
> You renamed a clip to "Hero Shot" in Arena. Even if the slot position changes, the app matches by that custom name and restores the right settings.

---

### 6. Cross-Layer Restore

When a file moves from one watchfolder to another, its effects follow it.

**How it works:** After syncing, if a clip has no local snapshot match, the app checks the combined snapshot file for entries from other layers. If found, those settings are applied.

**Use case — Reorganizing media between layers:**
> You move `abstract_loop.mov` from your Backgrounds folder (layer 1) to your Overlays folder (layer 3). When layer 3 syncs, the app finds the effects you had on layer 1 and applies them — your Blur and Color Balance come with it.

---

### 7. Duplicate Clip Recreation

Manually duplicated clips in Arena are automatically recreated from snapshots.

**How it works:** If a snapshot shows a file had 5 copies on a layer but sync only created 1, the app opens 4 more copies in their original slot positions. Then the slot-based matching ensures each copy gets its individual effects restored.

**Use case — VJ clip banks:**
> You duplicated `strobe.mov` 8 times in Arena, each with a different color effect for instant access during a set. You save settings, then switch to a different media set. When you switch back, all 8 copies are rebuilt with their individual color effects intact.

---

### 8. Native Folder Picker (macOS)

Desktop mode now uses the native macOS file dialog for browsing folders, bypassing TCC permission restrictions.

**How it works:** In desktop mode, clicking "Browse" opens the native NSOpenPanel dialog instead of the custom file browser. This has proper macOS permission access to ~/Documents, ~/Desktop, and other protected directories.

**Use case — macOS Sequoia users:**
> On macOS Sequoia, Python is blocked from reading ~/Documents due to TCC privacy restrictions. The native dialog works without needing Full Disk Access.

---

### 9. Two-Column Layout

The UI now uses a responsive two-column layout for better use of screen space.

**Layout:**
- **Left column** (fixed 340px): Arena Connection + Options (locks, snapshot folder)
- **Right column** (flexible): Save & Restore card + Sets & Mappings + Log

Collapses to a single column on screens narrower than 800px. Desktop window widened to 1200x800 to fit.

---

## Files Changed

| File | What changed |
|------|-------------|
| `watchfolder.py` | Composition lock, deck lock, global snapshot endpoint, combined snapshot I/O, cross-layer restore, duplicate recreation, improved browse error handling |
| `templates/index.html` | Two-column layout, composition/deck lock UI, Save & Restore card, snapshot folder config, native dialog integration |
| `config.py` | New defaults for composition lock, deck lock, snapshot folder |
| `desktop.py` | Native folder/file picker via pywebview, wider window (1200x800) |
| `restore.py` | Slot-based and name-based clip matching priority |

## Backward Compatibility

- Existing configs load without issues — new fields default to `None`/disabled
- Old snapshots without slot data fall through to FIFO matching (same as before)
- Single-column layout still works on narrow screens
- All new features are opt-in (locks disabled by default, snapshot folder empty)
