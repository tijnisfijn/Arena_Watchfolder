"""CLI subcommands for Arena Watchfolder.

Exposes every UI feature as a CLI command, making the tool fully scriptable
and controllable by LLMs or automation pipelines.

Usage:
    python watchfolder.py status
    python watchfolder.py sets list --json
    python watchfolder.py sync 3
    python watchfolder.py snapshot save
    python watchfolder.py config show
"""

import json
import sys
from pathlib import Path

from config import load_config, save_config
from watchfolder import (
    ArenaAPI,
    ArenaConnectionError,
    collect_layer_to_folder,
    load_combined_snapshot,
    log,
    merge_snapshots,
    merge_with_combined,
    recreate_duplicates,
    rename_layer_to_folder,
    restore_snapshot,
    save_combined_snapshot,
    scan_folder,
    snapshot_layer,
    sync_folder_to_layer,
    watch_folder,
    _sanitize_dirname,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_api(args):
    """Create an ArenaAPI connection using CLI flags or config defaults."""
    config = load_config()
    host = args.host if args.host != "127.0.0.1" else config.get("host", "127.0.0.1")
    port = args.port if args.port != 8080 else config.get("port", 8080)
    return ArenaAPI(host=host, port=port)


def _get_config():
    """Load config and return (config, active_set)."""
    config = load_config()
    active_id = config.get("active_set_id", "1")
    active_set = next((s for s in config.get("sets", []) if s["id"] == active_id), None)
    return config, active_set


def _find_mapping(active_set, mapping_id):
    """Find a mapping by ID in a set."""
    if not active_set:
        return None
    return next((m for m in active_set.get("mappings", []) if m["id"] == mapping_id), None)


def _find_set(config, set_id):
    """Find a set by ID."""
    return next((s for s in config.get("sets", []) if s["id"] == set_id), None)


def _next_id(config):
    """Derive the next unused ID from existing config."""
    max_id = 0
    for s in config.get("sets", []):
        try:
            max_id = max(max_id, int(s["id"]))
        except (ValueError, TypeError):
            pass
        for m in s.get("mappings", []):
            try:
                max_id = max(max_id, int(m["id"]))
            except (ValueError, TypeError):
                pass
    return str(max_id + 1)


def _check_locks(config, api):
    """Standalone composition and deck lock check.

    Returns (ok, error_msg).  ok=True means proceed.
    """
    options = config.get("options", {})
    # Composition lock
    if options.get("composition_lock"):
        locked = config.get("locked_composition")
        if locked:
            try:
                current = api.get_composition_name()
            except Exception as e:
                return False, f"Cannot verify composition: {e}"
            if current != locked:
                return False, f"Composition mismatch: expected '{locked}', Arena has '{current}'"
    # Deck lock
    locked_deck = config.get("locked_deck")
    if locked_deck:
        try:
            current = api.get_selected_deck()
        except Exception as e:
            return False, f"Cannot verify deck: {e}"
        if current != locked_deck:
            return False, f"Deck mismatch: expected '{locked_deck}', Arena has '{current}'"
    return True, None


def _output(data: dict, args):
    """Print result as JSON or human-readable text."""
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, default=str))
    else:
        _print_human(data)

    if "error" in data:
        sys.exit(1)


def _print_human(data: dict):
    """Format a result dict as clean text output."""
    if "error" in data:
        print(f"Error: {data['error']}")
        return

    for key, value in data.items():
        if key == "ok":
            continue
        if isinstance(value, list):
            if not value:
                print(f"{key}: (none)")
                continue
            print(f"{key}:")
            for item in value:
                if isinstance(item, dict):
                    parts = [f"{k}={v}" for k, v in item.items()]
                    print(f"  {', '.join(parts)}")
                else:
                    print(f"  {item}")
        elif isinstance(value, dict):
            print(f"{key}:")
            for k, v in value.items():
                print(f"  {k}: {v}")
        else:
            print(f"{key}: {value}")


# ---------------------------------------------------------------------------
# Redirect log() to stderr when --json is active
# ---------------------------------------------------------------------------

_original_log = log


def _setup_logging(args):
    """When --json mode is active, redirect log() output to stderr."""
    if getattr(args, "json", False):
        import watchfolder as wf

        def _stderr_log(message):
            print(message, file=sys.stderr)
        wf.log = _stderr_log


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_status(args):
    config, active_set = _get_config()
    result = {
        "host": config.get("host", "127.0.0.1"),
        "port": config.get("port", 8080),
        "active_set": active_set["name"] if active_set else None,
        "active_set_id": config.get("active_set_id"),
        "mappings": len(active_set.get("mappings", [])) if active_set else 0,
        "sets": len(config.get("sets", [])),
        "locked_composition": config.get("locked_composition"),
        "locked_deck": config.get("locked_deck"),
    }
    try:
        api = _get_api(args)
        result["connected"] = True
        result["composition"] = api.get_composition_name()
        result["deck"] = api.get_selected_deck()
        result["layers"] = api.get_layer_count()
        result["columns"] = api.get_column_count()
    except (ArenaConnectionError, Exception):
        result["connected"] = False
    _output(result, args)


# --- Sets ---

def cmd_sets_list(args):
    config, _ = _get_config()
    sets = []
    for s in config.get("sets", []):
        sets.append({
            "id": s["id"],
            "name": s["name"],
            "mappings": len(s.get("mappings", [])),
            "active": s["id"] == config.get("active_set_id"),
        })
    _output({"sets": sets}, args)


def cmd_sets_create(args):
    config, _ = _get_config()
    new_id = _next_id(config)
    new_set = {
        "id": new_id,
        "name": args.name,
        "mappings": [],
        "snapshots": {},
    }
    config.setdefault("sets", []).append(new_set)
    save_config(config)
    _output({"ok": True, "id": new_id, "name": args.name}, args)


def cmd_sets_rename(args):
    config, _ = _get_config()
    s = _find_set(config, args.set_id)
    if not s:
        _output({"error": f"Set '{args.set_id}' not found"}, args)
        return
    s["name"] = args.name
    save_config(config)
    _output({"ok": True, "id": args.set_id, "name": args.name}, args)


def cmd_sets_delete(args):
    config, _ = _get_config()
    s = _find_set(config, args.set_id)
    if not s:
        _output({"error": f"Set '{args.set_id}' not found"}, args)
        return
    if len(config.get("sets", [])) <= 1:
        _output({"error": "Cannot delete the last set"}, args)
        return
    config["sets"] = [x for x in config["sets"] if x["id"] != args.set_id]
    if config.get("active_set_id") == args.set_id:
        config["active_set_id"] = config["sets"][0]["id"]
    save_config(config)
    _output({"ok": True, "deleted": args.set_id}, args)


def cmd_sets_switch(args):
    config, _ = _get_config()
    new_set = _find_set(config, args.set_id)
    if not new_set:
        _output({"error": f"Set '{args.set_id}' not found"}, args)
        return

    try:
        api = _get_api(args)
    except ArenaConnectionError as e:
        _output({"error": str(e)}, args)
        return

    ok, err = _check_locks(config, api)
    if not ok:
        _output({"error": err}, args)
        return

    old_set = _find_set(config, config.get("active_set_id", ""))
    sf = config.get("options", {}).get("snapshot_folder", "")

    # Snapshot old set
    if old_set:
        log(f"  Saving snapshots for '{old_set['name']}'...")
        for m in old_set.get("mappings", []):
            try:
                snap = snapshot_layer(api, m["layer"])
                old_set.setdefault("snapshots", {})[str(m["layer"])] = snap
                clip_count = sum(1 for e in snap if e["filename"])
                log(f"    Layer {m['layer']}: {clip_count} clips saved")
                if sf:
                    comp = config.get("locked_composition", "")
                    save_combined_snapshot(sf, m["layer"], m["folder"], snap, comp)
            except Exception as e:
                log(f"    Warning: could not snapshot layer {m['layer']}: {e}")

    # Switch active set
    config["active_set_id"] = args.set_id
    log(f"\n  Switching to set '{new_set['name']}'")

    # Sync all mappings in new set + restore snapshots
    for m in new_set.get("mappings", []):
        if m.get("folder"):
            try:
                log(f"  Syncing layer {m['layer']} <- {m['folder']}")
                sync_folder_to_layer(api, m["folder"], m["layer"])
                if config.get("options", {}).get("rename_layers"):
                    rename_layer_to_folder(api, m["folder"], m["layer"])
                layer_snap = merge_with_combined(
                    new_set.get("snapshots", {}).get(str(m["layer"])),
                    sf, m["layer"],
                )
                if layer_snap:
                    log(f"  Restoring settings for layer {m['layer']}...")
                    restore_snapshot(api, m["layer"], layer_snap)
            except Exception as e:
                log(f"  ERROR syncing layer {m['layer']}: {e}")

    save_config(config)
    log("  Set switch complete!")
    _output({"ok": True, "active_set": new_set["name"]}, args)


# --- Mappings ---

def cmd_mappings_list(args):
    config, active_set = _get_config()
    if not active_set:
        _output({"error": "No active set"}, args)
        return
    mappings = []
    for m in active_set.get("mappings", []):
        mappings.append({
            "id": m["id"],
            "folder": m.get("folder", ""),
            "layer": m.get("layer", 0),
        })
    _output({"set": active_set["name"], "mappings": mappings}, args)


def cmd_mappings_add(args):
    config, active_set = _get_config()
    if not active_set:
        _output({"error": "No active set"}, args)
        return
    new_id = _next_id(config)
    mapping = {
        "id": new_id,
        "folder": str(Path(args.folder).resolve()),
        "layer": args.layer,
    }
    active_set.setdefault("mappings", []).append(mapping)
    save_config(config)
    _output({"ok": True, "id": new_id, "folder": mapping["folder"], "layer": args.layer}, args)


def cmd_mappings_update(args):
    config, active_set = _get_config()
    if not active_set:
        _output({"error": "No active set"}, args)
        return
    m = _find_mapping(active_set, args.mapping_id)
    if not m:
        _output({"error": f"Mapping '{args.mapping_id}' not found"}, args)
        return
    if args.folder is not None:
        m["folder"] = str(Path(args.folder).resolve())
    if args.layer is not None:
        m["layer"] = args.layer
    save_config(config)
    _output({"ok": True, "id": m["id"], "folder": m["folder"], "layer": m["layer"]}, args)


def cmd_mappings_remove(args):
    config, active_set = _get_config()
    if not active_set:
        _output({"error": "No active set"}, args)
        return
    m = _find_mapping(active_set, args.mapping_id)
    if not m:
        _output({"error": f"Mapping '{args.mapping_id}' not found"}, args)
        return
    active_set["mappings"] = [x for x in active_set["mappings"] if x["id"] != args.mapping_id]
    # Clean up snapshot for this layer
    active_set.get("snapshots", {}).pop(str(m["layer"]), None)
    save_config(config)
    _output({"ok": True, "deleted": args.mapping_id}, args)


# --- Sync ---

def cmd_sync(args):
    _setup_logging(args)
    config, active_set = _get_config()

    # One-off mode: --folder and --layer
    if getattr(args, "folder", None) and getattr(args, "layer", None):
        try:
            api = _get_api(args)
        except ArenaConnectionError as e:
            _output({"error": str(e)}, args)
            return
        dry_run = getattr(args, "dry_run", False)
        try:
            result = sync_folder_to_layer(api, args.folder, args.layer, dry_run=dry_run)
            _output({
                "ok": True,
                "files": len(result.get("files", [])),
                "added": len(result.get("added", [])),
                "removed": len(result.get("removed", [])),
            }, args)
        except (ValueError, Exception) as e:
            _output({"error": str(e)}, args)
        return

    # Config-based mode: mapping_id
    mapping_id = getattr(args, "mapping_id", None)
    if not mapping_id:
        _output({"error": "Provide a mapping_id, or use --folder and --layer for a one-off sync"}, args)
        return
    if not active_set:
        _output({"error": "No active set"}, args)
        return
    m = _find_mapping(active_set, mapping_id)
    if not m:
        _output({"error": f"Mapping '{mapping_id}' not found"}, args)
        return

    try:
        api = _get_api(args)
    except ArenaConnectionError as e:
        _output({"error": str(e)}, args)
        return

    ok, err = _check_locks(config, api)
    if not ok:
        _output({"error": err}, args)
        return

    force = getattr(args, "force", False)
    dry_run = getattr(args, "dry_run", False)
    layer_key = str(m["layer"])
    sf = config.get("options", {}).get("snapshot_folder", "")

    try:
        old_snap = active_set.get("snapshots", {}).get(layer_key)

        # For force sync, preserve original snapshot before pre-sync overwrites it
        if force:
            layer_snap = merge_with_combined(old_snap, sf, m["layer"])

        # Pre-sync snapshot
        try:
            pre_snap = snapshot_layer(api, m["layer"])
            active_set.setdefault("snapshots", {})[layer_key] = merge_snapshots(old_snap, pre_snap)
            clip_count = sum(1 for e in pre_snap if e["filename"])
            log(f"  Auto-saved settings before sync ({clip_count} clips)")
        except Exception as exc:
            log(f"  Warning: pre-sync snapshot failed: {exc}")

        if not force:
            layer_snap = merge_with_combined(
                active_set.get("snapshots", {}).get(layer_key), sf, m["layer"]
            )

        # Sync
        result = sync_folder_to_layer(
            api, m["folder"], m["layer"],
            dry_run=dry_run, force_full=force, snapshot=layer_snap,
        )

        # After force sync: recreate duplicates + restore
        if force and layer_snap:
            recreate_duplicates(api, m["layer"], layer_snap, logger=log)
            log("  Restoring all saved settings...")
            restore_snapshot(api, m["layer"], layer_snap, include_remembered=True)

        # Rename layer if option enabled
        if config.get("options", {}).get("rename_layers"):
            rename_layer_to_folder(api, m["folder"], m["layer"])

        returning = result.get("returning", [])

        # Post-sync snapshot (unless returning clips need user decision)
        if not returning:
            try:
                post_snap = snapshot_layer(api, m["layer"])
                active_set.setdefault("snapshots", {})[layer_key] = merge_snapshots(
                    active_set.get("snapshots", {}).get(layer_key), post_snap,
                )
                log("  Auto-saved settings after sync")
            except Exception as exc:
                log(f"  Warning: post-sync snapshot failed: {exc}")

        save_config(config)

        if sf and active_set.get("snapshots", {}).get(layer_key):
            comp = config.get("locked_composition", "")
            save_combined_snapshot(sf, m["layer"], m["folder"],
                                  active_set["snapshots"][layer_key], comp)

        _output({
            "ok": True,
            "files": len(result.get("files", [])),
            "added": len(result.get("added", [])),
            "removed": len(result.get("removed", [])),
            "returning": returning,
        }, args)
    except Exception as e:
        _output({"error": str(e)}, args)


def cmd_sync_all(args):
    _setup_logging(args)
    config, active_set = _get_config()
    if not active_set:
        _output({"error": "No active set"}, args)
        return

    try:
        api = _get_api(args)
    except ArenaConnectionError as e:
        _output({"error": str(e)}, args)
        return

    ok, err = _check_locks(config, api)
    if not ok:
        _output({"error": err}, args)
        return

    sf = config.get("options", {}).get("snapshot_folder", "")
    comp = config.get("locked_composition", "")
    results = []

    for m in active_set.get("mappings", []):
        if not m.get("folder"):
            continue
        layer_key = str(m["layer"])
        try:
            log(f"  Syncing layer {m['layer']} <- {m['folder']}")

            # Pre-sync snapshot
            old_snap = active_set.get("snapshots", {}).get(layer_key)
            try:
                pre_snap = snapshot_layer(api, m["layer"])
                active_set.setdefault("snapshots", {})[layer_key] = merge_snapshots(old_snap, pre_snap)
            except Exception:
                pass

            layer_snap = merge_with_combined(
                active_set.get("snapshots", {}).get(layer_key), sf, m["layer"]
            )

            result = sync_folder_to_layer(api, m["folder"], m["layer"], snapshot=layer_snap)

            if config.get("options", {}).get("rename_layers"):
                rename_layer_to_folder(api, m["folder"], m["layer"])

            # Post-sync snapshot
            try:
                post_snap = snapshot_layer(api, m["layer"])
                active_set.setdefault("snapshots", {})[layer_key] = merge_snapshots(
                    active_set.get("snapshots", {}).get(layer_key), post_snap,
                )
                if sf:
                    save_combined_snapshot(sf, m["layer"], m["folder"],
                                          active_set["snapshots"][layer_key], comp)
            except Exception:
                pass

            results.append({
                "mapping_id": m["id"],
                "layer": m["layer"],
                "files": len(result.get("files", [])),
                "added": len(result.get("added", [])),
                "removed": len(result.get("removed", [])),
            })
        except Exception as e:
            log(f"  ERROR syncing layer {m['layer']}: {e}")
            results.append({"mapping_id": m["id"], "layer": m["layer"], "error": str(e)})

    save_config(config)
    _output({"ok": True, "results": results}, args)


# --- Watch ---

def cmd_watch(args):
    _setup_logging(args)
    config, active_set = _get_config()

    # One-off mode
    folder = getattr(args, "folder", None)
    layer = getattr(args, "layer", None)
    if folder and layer:
        try:
            api = _get_api(args)
        except ArenaConnectionError as e:
            _output({"error": str(e)}, args)
            return
        try:
            watch_folder(api, folder, layer)
        except KeyboardInterrupt:
            log("\n  Watch stopped.")
        return

    # Config-based mode
    mapping_id = getattr(args, "mapping_id", None)
    if not mapping_id:
        _output({"error": "Provide a mapping_id, or use --folder and --layer"}, args)
        return
    if not active_set:
        _output({"error": "No active set"}, args)
        return
    m = _find_mapping(active_set, mapping_id)
    if not m:
        _output({"error": f"Mapping '{mapping_id}' not found"}, args)
        return

    try:
        api = _get_api(args)
    except ArenaConnectionError as e:
        _output({"error": str(e)}, args)
        return

    sf = config.get("options", {}).get("snapshot_folder", "")

    def _get_snap():
        cfg = load_config()
        aset = next((s for s in cfg.get("sets", []) if s["id"] == cfg.get("active_set_id")), None)
        snap = aset.get("snapshots", {}).get(str(m["layer"])) if aset else None
        return merge_with_combined(snap, sf, m["layer"])

    def _save_snap(snap):
        cfg = load_config()
        aset = next((s for s in cfg.get("sets", []) if s["id"] == cfg.get("active_set_id")), None)
        if aset:
            aset.setdefault("snapshots", {})[str(m["layer"])] = snap
            save_config(cfg)
            if sf:
                comp = cfg.get("locked_composition", "")
                save_combined_snapshot(sf, m["layer"], m["folder"], snap, comp)

    def _composition_ok():
        cfg = load_config()
        return _check_locks(cfg, api)

    try:
        watch_folder(
            api, m["folder"], m["layer"],
            snapshot_getter=_get_snap,
            snapshot_saver=_save_snap,
            rename_layer=config.get("options", {}).get("rename_layers", False),
            composition_checker=_composition_ok,
        )
    except KeyboardInterrupt:
        log("\n  Watch stopped.")


# --- Snapshot ---

def cmd_snapshot_save(args):
    _setup_logging(args)
    config, active_set = _get_config()
    if not active_set:
        _output({"error": "No active set"}, args)
        return

    try:
        api = _get_api(args)
    except ArenaConnectionError as e:
        _output({"error": str(e)}, args)
        return

    sf = config.get("options", {}).get("snapshot_folder", "")
    comp = config.get("locked_composition", "")
    mapping_id = getattr(args, "mapping_id", None)

    if mapping_id:
        # Single mapping snapshot
        m = _find_mapping(active_set, mapping_id)
        if not m:
            _output({"error": f"Mapping '{mapping_id}' not found"}, args)
            return
        try:
            layer_key = str(m["layer"])
            old_snap = active_set.get("snapshots", {}).get(layer_key)
            new_snap = snapshot_layer(api, m["layer"])
            active_set.setdefault("snapshots", {})[layer_key] = merge_snapshots(old_snap, new_snap)
            clip_count = sum(1 for e in new_snap if e["filename"])
            log(f"  Layer {m['layer']}: snapshot saved ({clip_count} clips)")
            save_config(config)
            if sf:
                save_combined_snapshot(sf, m["layer"], m["folder"],
                                      active_set["snapshots"][layer_key], comp)
            _output({"ok": True, "layer": m["layer"], "clips": clip_count}, args)
        except Exception as e:
            _output({"error": str(e)}, args)
    else:
        # All mappings
        total_clips = 0
        layers_saved = 0
        errors = []
        for m in active_set.get("mappings", []):
            try:
                layer_key = str(m["layer"])
                old_snap = active_set.get("snapshots", {}).get(layer_key)
                new_snap = snapshot_layer(api, m["layer"])
                active_set.setdefault("snapshots", {})[layer_key] = merge_snapshots(old_snap, new_snap)
                clip_count = sum(1 for e in new_snap if e["filename"])
                total_clips += clip_count
                layers_saved += 1
                log(f"  Layer {m['layer']}: snapshot saved ({clip_count} clips)")
                if sf:
                    save_combined_snapshot(sf, m["layer"], m["folder"],
                                          active_set["snapshots"][layer_key], comp)
            except Exception as e:
                errors.append(f"Layer {m['layer']}: {e}")
                log(f"  ERROR snapshotting layer {m['layer']}: {e}")
        save_config(config)
        result = {"ok": True, "clips": total_clips, "layers": layers_saved}
        if errors:
            result["errors"] = errors
        _output(result, args)


def cmd_snapshot_restore(args):
    _setup_logging(args)
    config, active_set = _get_config()
    if not active_set:
        _output({"error": "No active set"}, args)
        return

    m = _find_mapping(active_set, args.mapping_id)
    if not m:
        _output({"error": f"Mapping '{args.mapping_id}' not found"}, args)
        return

    try:
        api = _get_api(args)
    except ArenaConnectionError as e:
        _output({"error": str(e)}, args)
        return

    layer_key = str(m["layer"])
    sf = config.get("options", {}).get("snapshot_folder", "")
    layer_snap = merge_with_combined(
        active_set.get("snapshots", {}).get(layer_key), sf, m["layer"]
    )
    if not layer_snap:
        _output({"error": "No snapshot for this layer"}, args)
        return

    try:
        only_filenames = None
        if getattr(args, "only", None):
            only_filenames = set(args.only.split(","))
            log(f"  Restoring settings for {len(only_filenames)} clip(s) on layer {m['layer']}...")
        else:
            log(f"  Restoring settings for layer {m['layer']}...")

        restore_snapshot(api, m["layer"], layer_snap, only_filenames=only_filenames)

        # Save after restore
        try:
            post_snap = snapshot_layer(api, m["layer"])
            active_set.setdefault("snapshots", {})[layer_key] = merge_snapshots(
                active_set.get("snapshots", {}).get(layer_key), post_snap,
            )
            save_config(config)
            if sf and active_set.get("snapshots", {}).get(layer_key):
                comp = config.get("locked_composition", "")
                save_combined_snapshot(sf, m["layer"], m["folder"],
                                      active_set["snapshots"][layer_key], comp)
            log("  Settings saved after restore")
        except Exception:
            pass

        _output({"ok": True, "layer": m["layer"]}, args)
    except Exception as e:
        _output({"error": str(e)}, args)


# --- Collect ---

def cmd_collect(args):
    _setup_logging(args)
    config, active_set = _get_config()
    if not active_set:
        _output({"error": "No active set"}, args)
        return

    m = _find_mapping(active_set, args.mapping_id)
    if not m:
        _output({"error": f"Mapping '{args.mapping_id}' not found"}, args)
        return
    if not m.get("folder"):
        _output({"error": "Mapping has no folder set"}, args)
        return

    try:
        api = _get_api(args)
    except ArenaConnectionError as e:
        _output({"error": str(e)}, args)
        return

    try:
        result = collect_layer_to_folder(api, m["layer"], m["folder"])

        # Snapshot after collect
        layer_key = str(m["layer"])
        sf = config.get("options", {}).get("snapshot_folder", "")
        old_snap = active_set.get("snapshots", {}).get(layer_key)
        new_snap = snapshot_layer(api, m["layer"])
        active_set.setdefault("snapshots", {})[layer_key] = merge_snapshots(old_snap, new_snap)
        if sf:
            comp = config.get("locked_composition", "")
            save_combined_snapshot(sf, m["layer"], m["folder"],
                                  active_set["snapshots"][layer_key], comp)
        save_config(config)

        _output({
            "ok": True,
            "copied": len(result["copied"]),
            "skipped": result["skipped"],
            "sources": result["sources"],
            "errors": result["errors"],
        }, args)
    except Exception as e:
        _output({"error": str(e)}, args)


def cmd_collect_all(args):
    _setup_logging(args)
    config, active_set = _get_config()
    if not active_set:
        _output({"error": "No active set"}, args)
        return

    try:
        api = _get_api(args)
    except ArenaConnectionError as e:
        _output({"error": str(e)}, args)
        return

    dest_root = Path(args.destination)
    try:
        dest_root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _output({"error": f"Cannot create destination: {e}"}, args)
        return

    comp_name = _sanitize_dirname(api.get_composition_name() or "Composition")
    deck_name = _sanitize_dirname(api.get_selected_deck() or "Deck 1")
    sf = config.get("options", {}).get("snapshot_folder", "")
    comp = config.get("locked_composition", "")
    num_layers = api.get_layer_count()

    results = []
    used_names = {}
    existing = {m["layer"]: m for m in active_set.get("mappings", [])}

    log(f"Collecting from {num_layers} Arena layers...")

    for layer in range(1, num_layers + 1):
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

            # Save snapshot
            layer_key = str(layer)
            old_snap = active_set.get("snapshots", {}).get(layer_key)
            new_snap = snapshot_layer(api, layer)
            active_set.setdefault("snapshots", {})[layer_key] = merge_snapshots(old_snap, new_snap)
            if sf:
                save_combined_snapshot(sf, layer, str(layer_folder),
                                      active_set["snapshots"][layer_key], comp)

            # Create or update mapping
            if layer in existing:
                existing[layer]["folder"] = str(layer_folder)
            else:
                new_id = _next_id(config)
                new_m = {"id": new_id, "folder": str(layer_folder), "layer": layer}
                active_set.setdefault("mappings", []).append(new_m)
                existing[layer] = new_m
        except Exception as e:
            log(f"  ERROR collecting layer {layer}: {e}")
            results.append({"layer": layer, "layer_name": layer_name,
                            "folder": str(layer_folder), "copied": 0, "errors": [str(e)]})

    # Write combined snapshot into collect destination
    collect_snap_dir = str(dest_root / comp_name / deck_name)
    for r in results:
        layer_num = r["layer"]
        snap_data = active_set.get("snapshots", {}).get(str(layer_num))
        if snap_data:
            m = existing.get(layer_num)
            folder_path = m["folder"] if m else r.get("folder", "")
            save_combined_snapshot(collect_snap_dir, layer_num, folder_path, snap_data, comp)

    save_config(config)
    total = sum(r.get("copied", 0) for r in results)
    total_err = sum(len(r.get("errors", [])) for r in results)
    log(f"Collect complete: {total} files copied, {total_err} errors")
    _output({"ok": True, "results": results, "total_copied": total}, args)


# --- Lock ---

def cmd_lock_status(args):
    config, _ = _get_config()
    result = {
        "composition_lock_enabled": config.get("options", {}).get("composition_lock", False),
        "locked_composition": config.get("locked_composition"),
        "locked_deck": config.get("locked_deck"),
    }
    try:
        api = _get_api(args)
        result["current_composition"] = api.get_composition_name()
        result["current_deck"] = api.get_selected_deck()
    except (ArenaConnectionError, Exception):
        pass
    _output(result, args)


def cmd_lock_composition(args):
    config, _ = _get_config()
    config.setdefault("options", {})["composition_lock"] = True
    config["locked_composition"] = args.name
    save_config(config)
    _output({"ok": True, "locked_composition": args.name}, args)


def cmd_lock_deck(args):
    config, _ = _get_config()
    config["locked_deck"] = args.name
    save_config(config)
    _output({"ok": True, "locked_deck": args.name}, args)


def cmd_lock_clear(args):
    config, _ = _get_config()
    config.setdefault("options", {})["composition_lock"] = False
    config["locked_composition"] = None
    config["locked_deck"] = None
    save_config(config)
    _output({"ok": True, "message": "All locks cleared"}, args)


# --- Config ---

_BOOL_KEYS = {"rename_layers", "composition_lock"}
_STR_KEYS = {"host", "compositions_folder", "snapshot_folder"}
_INT_KEYS = {"port"}


def cmd_config_show(args):
    config, active_set = _get_config()
    _output({
        "host": config.get("host", "127.0.0.1"),
        "port": config.get("port", 8080),
        "rename_layers": config.get("options", {}).get("rename_layers", False),
        "composition_lock": config.get("options", {}).get("composition_lock", False),
        "compositions_folder": config.get("options", {}).get("compositions_folder", ""),
        "snapshot_folder": config.get("options", {}).get("snapshot_folder", ""),
        "locked_composition": config.get("locked_composition"),
        "locked_deck": config.get("locked_deck"),
        "active_set": active_set["name"] if active_set else None,
        "sets": len(config.get("sets", [])),
    }, args)


def cmd_config_set(args):
    config, _ = _get_config()
    key = args.key
    value = args.value

    if key in _INT_KEYS:
        config[key] = int(value)
    elif key in _BOOL_KEYS:
        config.setdefault("options", {})[key] = value.lower() in ("true", "1", "yes")
    elif key in _STR_KEYS:
        if key in ("host",):
            config[key] = value
        else:
            config.setdefault("options", {})[key] = value
    else:
        _output({"error": f"Unknown config key: {key}. Valid keys: {', '.join(sorted(_BOOL_KEYS | _STR_KEYS | _INT_KEYS))}"}, args)
        return

    save_config(config)
    _output({"ok": True, key: value}, args)


# ---------------------------------------------------------------------------
# Argparse setup & dispatch
# ---------------------------------------------------------------------------

def build_subparsers(parser):
    """Register all subcommands on the given argparse parser."""
    import argparse

    # Common flags available on every subcommand
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true",
                        help="Output JSON (machine-readable)")
    common.add_argument("--host", default="127.0.0.1",
                        help="Arena webserver host")
    common.add_argument("--port", "-p", type=int, default=8080,
                        help="Arena webserver port")

    sub = parser.add_subparsers(dest="command")

    # --- status ---
    sub.add_parser("status", parents=[common],
                   help="Show connection status and current state")

    # --- sets ---
    sets_p = sub.add_parser("sets", help="Manage mapping sets (profiles)")
    sets_sub = sets_p.add_subparsers(dest="sets_action")
    sets_sub.add_parser("list", parents=[common], help="List all sets")
    p = sets_sub.add_parser("create", parents=[common], help="Create a new set")
    p.add_argument("name", help="Set name")
    p = sets_sub.add_parser("rename", parents=[common], help="Rename a set")
    p.add_argument("set_id", help="Set ID")
    p.add_argument("name", help="New name")
    p = sets_sub.add_parser("delete", parents=[common], help="Delete a set")
    p.add_argument("set_id", help="Set ID")
    p = sets_sub.add_parser("switch", parents=[common],
                            help="Switch active set (snapshots old, syncs + restores new)")
    p.add_argument("set_id", help="Set ID to activate")

    # --- mappings ---
    map_p = sub.add_parser("mappings", help="Manage folder-to-layer mappings")
    map_sub = map_p.add_subparsers(dest="mappings_action")
    map_sub.add_parser("list", parents=[common], help="List mappings in active set")
    p = map_sub.add_parser("add", parents=[common], help="Add a new mapping")
    p.add_argument("--folder", required=True, help="Folder path")
    p.add_argument("--layer", type=int, required=True, help="Layer index (1-based)")
    p = map_sub.add_parser("update", parents=[common], help="Update a mapping")
    p.add_argument("mapping_id", help="Mapping ID")
    p.add_argument("--folder", help="New folder path")
    p.add_argument("--layer", type=int, help="New layer index")
    p = map_sub.add_parser("remove", parents=[common], help="Remove a mapping")
    p.add_argument("mapping_id", help="Mapping ID")

    # --- sync ---
    p = sub.add_parser("sync", parents=[common],
                       help="Sync a mapping (or --folder/--layer for one-off)")
    p.add_argument("mapping_id", nargs="?", help="Mapping ID")
    p.add_argument("--folder", help="Folder path (one-off sync)")
    p.add_argument("--layer", type=int, help="Layer index (one-off sync)")
    p.add_argument("--force", action="store_true", help="Force full re-sync (clear + reload)")
    p.add_argument("--dry-run", action="store_true", help="Preview without changing Arena")

    # --- sync-all ---
    sub.add_parser("sync-all", parents=[common],
                   help="Sync all mappings in the active set")

    # --- watch ---
    p = sub.add_parser("watch", parents=[common],
                       help="Watch and auto-sync on changes (Ctrl+C to stop)")
    p.add_argument("mapping_id", nargs="?", help="Mapping ID")
    p.add_argument("--folder", help="Folder path (one-off watch)")
    p.add_argument("--layer", type=int, help="Layer index (one-off watch)")

    # --- snapshot ---
    snap_p = sub.add_parser("snapshot", help="Save or restore clip settings snapshots")
    snap_sub = snap_p.add_subparsers(dest="snapshot_action")
    p = snap_sub.add_parser("save", parents=[common],
                            help="Save snapshot (all or single mapping)")
    p.add_argument("mapping_id", nargs="?", help="Mapping ID (omit for all)")
    p = snap_sub.add_parser("restore", parents=[common],
                            help="Restore snapshot for a mapping")
    p.add_argument("mapping_id", help="Mapping ID")
    p.add_argument("--only", help="Comma-separated filenames for partial restore")

    # --- collect ---
    p = sub.add_parser("collect", parents=[common],
                       help="Collect clips from Arena layer to mapping folder")
    p.add_argument("mapping_id", help="Mapping ID")

    # --- collect-all ---
    p = sub.add_parser("collect-all", parents=[common],
                       help="Collect all Arena layers into folder structure")
    p.add_argument("--destination", required=True, help="Root destination folder")

    # --- lock ---
    lock_p = sub.add_parser("lock", help="Manage composition and deck locks")
    lock_sub = lock_p.add_subparsers(dest="lock_action")
    lock_sub.add_parser("status", parents=[common], help="Show lock status")
    p = lock_sub.add_parser("composition", parents=[common],
                            help="Lock to a composition")
    p.add_argument("name", help="Composition name")
    p = lock_sub.add_parser("deck", parents=[common], help="Lock to a deck")
    p.add_argument("name", help="Deck name")
    lock_sub.add_parser("clear", parents=[common], help="Clear all locks")

    # --- config ---
    cfg_p = sub.add_parser("config", help="View and modify settings")
    cfg_sub = cfg_p.add_subparsers(dest="config_action")
    cfg_sub.add_parser("show", parents=[common], help="Show current configuration")
    p = cfg_sub.add_parser("set", parents=[common], help="Set a config value")
    p.add_argument("key", help="Key: host, port, rename_layers, composition_lock, compositions_folder, snapshot_folder")
    p.add_argument("value", help="Value to set")


def dispatch(args):
    """Route a parsed command to its handler."""
    _setup_logging(args)
    cmd = getattr(args, "command", None)

    # Top-level commands
    simple = {
        "status": cmd_status,
        "sync": cmd_sync,
        "sync-all": cmd_sync_all,
        "watch": cmd_watch,
        "collect": cmd_collect,
        "collect-all": cmd_collect_all,
    }
    if cmd in simple:
        simple[cmd](args)
        return

    # Nested subcommands
    nested = {
        "sets": ("sets_action", {
            "list": cmd_sets_list,
            "create": cmd_sets_create,
            "rename": cmd_sets_rename,
            "delete": cmd_sets_delete,
            "switch": cmd_sets_switch,
        }),
        "mappings": ("mappings_action", {
            "list": cmd_mappings_list,
            "add": cmd_mappings_add,
            "update": cmd_mappings_update,
            "remove": cmd_mappings_remove,
        }),
        "snapshot": ("snapshot_action", {
            "save": cmd_snapshot_save,
            "restore": cmd_snapshot_restore,
        }),
        "lock": ("lock_action", {
            "list": cmd_lock_status,
            "status": cmd_lock_status,
            "composition": cmd_lock_composition,
            "deck": cmd_lock_deck,
            "clear": cmd_lock_clear,
        }),
        "config": ("config_action", {
            "show": cmd_config_show,
            "set": cmd_config_set,
        }),
    }

    if cmd in nested:
        action_attr, handlers = nested[cmd]
        action = getattr(args, action_attr, None)
        if action and action in handlers:
            handlers[action](args)
        else:
            valid = ", ".join(handlers.keys())
            print(f"Usage: watchfolder.py {cmd} {{{valid}}}")
            sys.exit(1)
        return

    print("Unknown command. Run 'watchfolder.py --help' for usage.")
    sys.exit(1)
