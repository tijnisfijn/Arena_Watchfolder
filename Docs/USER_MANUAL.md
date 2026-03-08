# Arena Watchfolder - User Manual

Version: March 8, 2026  
Scope: `feature/snapshot-and-lock-improvements`

## Table of Contents
1. [What This Build Adds](#1-what-this-build-adds)
2. [UI Walkthrough (Panel by Panel)](#2-ui-walkthrough-panel-by-panel)
3. [Control Reference](#3-control-reference)
4. [Safety System (Composition Lock + Deck Lock)](#4-safety-system-composition-lock--deck-lock)
5. [Snapshot and Restore System](#5-snapshot-and-restore-system)
6. [Collect from Arena (Reverse Sync)](#6-collect-from-arena-reverse-sync)
7. [Generated Sources Round-Trip](#7-generated-sources-round-trip)
8. [Dialog and Warning Catalog](#8-dialog-and-warning-catalog)
9. [Operational Playbooks](#9-operational-playbooks)
10. [Troubleshooting](#10-troubleshooting)
11. [Best Practices](#11-best-practices)
12. [Appendix: Full-Screen References](#12-appendix-full-screen-references)

---

## 1. What This Build Adds

This branch adds safety gates, stronger restore logic, and a better operator workflow.

### 1.1 Safety upgrades
- **Composition Lock**: sync is blocked if Arena is on the wrong `.avc`.
- **Deck Lock**: sync is blocked if the wrong deck is active.
- **Watch auto-pause/resume**: watch mode pauses on lock mismatch and resumes when context is valid again.
- **Deck lock auto-clear**: if the locked deck no longer exists in a new composition, lock is cleared automatically.

### 1.2 Snapshot and restore upgrades
- **Save All Settings**: one-button global checkpoint across all mappings.
- **Combined Snapshot File**: all layer snapshots in one `watchfolder_snapshot.json`.
- **Smarter clip matching**: slot-first matching for duplicate filenames.
- **Cross-layer restore**: effects/settings follow clips moved between watchfolders.
- **Duplicate recreation**: repeated clip instances get rebuilt and restored correctly.

### 1.3 Workflow and quality-of-life upgrades
- **Collect from Arena** (reverse sync): pull Arena content to folders.
- **Two-column layout**: options left, operations right.
- **Native folder picker** (desktop): OS file dialog support.
- **Updated help/tooltips** in the UI.

---

## 2. UI Walkthrough (Panel by Panel)

### 2.1 Full layout context
![Figure 1 - Full application layout](manual-assets/overview_with_mappings.png)

The interface is split into:
1. **Left column**: connection and safety/options
2. **Right column**: save/collect/sets/log operational flow

### 2.2 Arena Connection panel
![Figure 2 - Arena Connection panel](manual-assets/panel_arena_connection.png)

Purpose: connect Watchfolder to Arena Webserver.

Primary fields:
- `Host` (default `127.0.0.1`)
- `Port` (default `8080`)
- `Connect`
- Connection status indicator

### 2.3 Options panel
![Figure 3 - Options panel](manual-assets/panel_options_full.png)

Purpose: enforce sync safety and configure snapshot persistence.

Includes:
- Rename layers to folder name
- Composition lock controls
- Deck lock controls
- Snapshot file location

### 2.4 Collect from Arena panel
![Figure 4 - Collect from Arena panel](manual-assets/panel_collect_from_arena.png)

Purpose: reverse direction copy from Arena -> filesystem.

Key behavior:
- `Collect All` scans all layers and writes to:
  `destination/composition/deck/layer/`
- Creates/updates mappings based on discovered layers.

### 2.5 Sets and Mappings (empty)
![Figure 5 - Sets and Mappings empty state](manual-assets/panel_sets_empty.png)

Use this when starting from scratch:
- create/select Set
- add mappings manually
- or run `Collect All` to auto-seed mappings

### 2.6 Sets and Mappings (active)
![Figure 6 - Sets and Mappings with active mappings](manual-assets/panel_sets_with_mappings.png)

This is the main operations area during shows.

### 2.7 Log panel
![Figure 7 - Log panel](manual-assets/panel_log.png)

Purpose: runtime feedback and operational verification.

Track here:
- connection status
- lock changes
- sync actions
- warnings/errors

---

## 3. Control Reference

### 3.1 Mapping row controls
Each mapping row provides:
- **Sync Now**: incremental diff sync
- **Force Sync**: clear/reload full layer rebuild
- **Start Watch / Stop Watch**: continuous folder monitoring
- **Restore Settings**: apply snapshot to clips on that mapping
- **Collect**: copy layer files into mapping folder
- **Edit icon**: change folder/layer
- **Remove icon**: delete mapping

### 3.2 Watching state indicator
![Figure 8 - Mapping row while watching](manual-assets/mapping_row_watching.png)

When watching is active:
- row highlight + watching badge
- `Stop Watch` replaces `Start Watch`

### 3.3 Set-level controls
At top of Sets panel:
- Set dropdown
- `Rename`
- `+ New`
- `Delete`
- `Sync All` (when applicable)

---

## 4. Safety System (Composition Lock + Deck Lock)

### 4.1 Composition Lock
Intent: prevent syncing to the wrong show file.

How it behaves:
1. Select target composition in Options.
2. Before sync, current Arena composition is checked.
3. If mismatch, sync is blocked and watch pauses.
4. When expected composition is active again, watch can continue.

Use-case examples:
- **Accidental overwrite prevention** between `Friday.avc` and `Saturday.avc`.
- **Shared workstation isolation** where multiple operators use one machine.

### 4.2 Deck Lock
Intent: prevent syncing to the wrong deck in multi-deck comps.

How it behaves:
1. Select locked deck or choose `Any deck`.
2. Sync requires deck match when lock is set.
3. If locked deck disappears in new composition, lock auto-clears.

Use-case examples:
- Keep warmup and main show media isolated by active deck.

### 4.3 Combined lock behavior
If both are set, both must match.
- composition check first
- then deck check
- sync proceeds only when both pass

---

## 5. Snapshot and Restore System

### 5.1 Save All Settings
A global checkpoint across all mappings.

Why this matters:
- all layers share same save-time context
- prevents mismatched layer states when restoring complex setups

### 5.2 Combined snapshot file
Configured via **Snapshot file location**.

Writes one file:
- `watchfolder_snapshot.json`
- includes all layers/clips/settings
- useful for backup, sync, and migration

### 5.3 Smarter clip matching logic
Restore matching priority:
1. Slot match (most precise)
2. Clip name match
3. FIFO fallback

This solves duplicate filename edge cases where different copies hold different effects.

### 5.4 Cross-layer restore
If a clip moved to another mapping/layer:
- app checks combined snapshot from other layers
- applies matching settings to new location

### 5.5 Duplicate recreation
If snapshot says there were multiple instances of one file:
- app re-opens missing duplicate instances
- restores per-instance settings by slot

---

## 6. Collect from Arena (Reverse Sync)

### 6.1 What it does
Collect reverses the normal flow:
- normal flow: folder -> Arena
- collect flow: Arena -> folder(s)

### 6.2 Collect All behavior
- scans all Arena layers
- copies clip files into organized structure
- creates/updates mappings automatically
- stores snapshot data alongside collected structure

### 6.3 Single mapping Collect
Use `Collect` in one mapping row when you only need one layer exported.

### 6.4 Why this is important
- backup shows created directly in Arena
- migrate to another machine
- rebuild folder structure from Arena state

---

## 7. Generated Sources Round-Trip

Generated sources (e.g. Solid Color, Checkered, Lines, Gradient, Abstract Field) are preserved in the snapshot flow.

Round-trip behavior:
1. Collect captures source entries and source parameters.
2. Force Sync re-creates generated sources in their expected slots.
3. Restore applies source/effect/transport settings.

This allows mixed file + generator shows to be reconstructed reliably.

---

## 8. Dialog and Warning Catalog

You asked whether all warning/verification dialogs should be documented.

Recommendation: include every operator-impacting dialog. This manual includes all critical ones.

### 8.1 Force Sync confirmation
![Figure 9 - Force Sync warning](manual-assets/force_sync_confirm.png)

Meaning: layer will be cleared and rebuilt.

Recommended path:
1. Save settings
2. Force Sync
3. Restore settings

### 8.2 Returning Clips modal
![Figure 10 - Returning Clips modal](manual-assets/returning_clips_modal.png)

Decision:
- **Restore Settings** to recover prior look
- **Keep Fresh** for new default state

### 8.3 Collect All confirmation
![Figure 11 - Collect All confirmation](manual-assets/collect_all_confirm.png)

Confirms large-scope collect with mapping updates.

### 8.4 Collect mapping confirmation
![Figure 12 - Collect mapping confirmation](manual-assets/collect_mapping_confirm.png)

Confirms targeted, single-mapping collect.

### 8.5 Collect completion alert
![Figure 13 - Collect success alert](manual-assets/collect_success_alert.png)

Use to verify file count quickly after operation.

---

## 9. Operational Playbooks

### 9.1 Backup and restore a show
1. Build and tweak show in Arena (files + generators + effects).
2. Run **Collect All** and choose destination.
3. Confirm dialog and verify completion count.
4. Save snapshots.
5. On restore machine: set mappings to collected folders.
6. Run **Force Sync** and **Restore Settings** as needed.

Result: reconstructed files, generators, and clip settings.

### 9.2 Use Arena as a file manager (sorting workflow)
1. Start with unsorted media in Arena.
2. Sort clips by layer role (backgrounds, overlays, masks, logos).
3. Rename layers to meaningful categories.
4. In Watchfolder, run **Collect All**.

Result: filesystem is automatically organized by composition/deck/layer and mappings are created.

### 9.3 Live show workflow
1. Connect to Arena and verify status.
2. Enable Composition/Deck lock as needed.
3. Select active Set.
4. Save All Settings before risky operations.
5. Use `Sync Now` for controlled changes.
6. Use `Start Watch` only on mappings that must auto-update.
7. Monitor Log continuously.

### 9.4 Multi-night set switching
1. Create one Set per night/show variant.
2. Snapshot before switching.
3. Switch Set and allow sync/restore sequence.
4. Verify in log and spot-check key layers.

---

## 10. Troubleshooting

### 10.1 Cannot connect
- verify Arena webserver is enabled
- confirm host/port
- check firewall/network policy

### 10.2 Sync blocked unexpectedly
- verify composition lock target
- verify deck lock target
- check log for mismatch reason

### 10.3 Effects restored incorrectly on duplicates
- use latest snapshot
- rely on slot-stable mapping order
- run Force Sync + Restore for clean rebuild

### 10.4 Collect output not as expected
- verify destination path permissions
- verify active composition/deck context
- check log for skipped/empty/error messages

### 10.5 Watch did not update
- ensure mapping is actually in watching state
- verify lock conditions still pass
- check folder path and file extension support

---

## 11. Best Practices

- Use lock features on shared or high-risk machines.
- Save All Settings before bulk edits, set switches, and force sync.
- Keep snapshot file location on stable storage (optionally cloud-synced).
- Use Force Sync strategically, not routinely.
- Keep layer names semantic for easier collect organization.
- Review logs after every major operation.

---

## 12. Appendix: Full-Screen References

![Appendix A - Full screen with composition lock off](manual-assets/full_ui_comp_lock_off.png)

![Appendix B - Full screen with composition lock on](manual-assets/full_ui_comp_lock_on.png)

![Appendix C - Full screen with deck lock active](manual-assets/full_ui_deck_lock_active.png)

![Appendix D - Full screen with no mappings](manual-assets/full_ui_no_mappings.png)
