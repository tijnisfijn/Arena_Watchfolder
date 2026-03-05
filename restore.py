"""Clip settings restore logic for Arena Watchfolder.

Provides two restore strategies:
  1. WebSocket-based (preferred): adds effects, sets each parameter by ID.
  2. REST-based (fallback): adds effects via POST, PUTs parameter blobs.

The caller (watchfolder.py) passes in the API client and an optional
WebSocket client — this module imports nothing from watchfolder.py.
"""

import time
from pathlib import Path

try:
    from arena_ws import ArenaWebSocket
except ImportError:
    ArenaWebSocket = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def restore_snapshot(api, layer: int, snapshot: list[dict],
                     ws=None, logger=None,
                     only_filenames: set[str] | None = None):
    """Restore clip settings from a snapshot to the current layer state.

    Matches clips by filename — if a clip with the same filename exists
    in the snapshot and on the layer, its settings are applied.

    Args:
        api:      ArenaAPI instance (REST client).
        layer:    1-based layer index.
        snapshot: List of snapshot entries from snapshot_layer().
        ws:       Optional ArenaWebSocket instance (connected). When
                  provided, effect parameters are set individually by ID
                  for reliable restoration.
        logger:   Optional callable for log output (defaults to print).
        only_filenames: Optional set of filenames to restrict restoration to.
                  When provided, only clips whose filename is in this set
                  will be restored. Other clips are left untouched.
    """
    log = logger or print

    if not snapshot:
        return

    use_ws = ws is not None and ws.connected

    current_clips = api.get_layer_clips(layer)

    # Build lookup: filename -> list of snapshot entries (handles duplicates)
    snap_by_name: dict[str, list[dict]] = {}
    for entry in snapshot:
        if entry["filename"] and entry["data"]:
            snap_by_name.setdefault(entry["filename"], []).append(entry)

    restored = 0
    for clip in current_clips:
        if not clip["path"]:
            continue
        filename = Path(clip["path"]).name
        if only_filenames is not None and filename not in only_filenames:
            continue
        entries = snap_by_name.get(filename, [])
        if not entries:
            continue

        entry = entries.pop(0)
        clip_data = entry["data"]

        # --- Effects ---
        # Try WS first (adds effects + sets individual params).
        # If WS is unavailable, fall back to REST (adds effects only).
        # _ensure_effects_exist handles dedup so effects aren't added twice.
        effects_ok = False
        if use_ws:
            effects_ok = _restore_effects_ws(
                ws, api, layer, clip["slot"], clip_data, log,
            )
        if not effects_ok:
            _ensure_effects_exist(api, layer, clip["slot"], clip_data, log)

        # --- Non-effect sections (transport, video props, etc.) ---
        # These work fine via REST PUT regardless of WS availability.
        # Never skip effects in the PUT — the WS path handles individual
        # param setting, but if it fails we need the blob PUT as fallback.
        any_ok = False
        for section in _restorable_sections(clip_data, skip_effects=effects_ok):
            try:
                api.update_clip(layer, clip["slot"], section)
                any_ok = True
            except Exception:
                pass  # some sections may legitimately fail
        if any_ok or effects_ok:
            restored += 1
        else:
            log(f"    Warning: could not restore settings for slot {clip['slot']}")

    if restored:
        log(f"  Restored settings for {restored} clip(s)")


def extract_effect_name(effect: dict) -> str:
    """Extract the display name from an effect dict.

    Handles both formats returned by Arena:
      - Plain string:  {"name": "Blur", ...}
      - Param object:  {"name": {"value": "Blur", "valuetype": "ParamString"}, ...}

    Returns empty string if name cannot be determined.
    """
    name = effect.get("name")
    if isinstance(name, str):
        return name
    if isinstance(name, dict):
        return name.get("value", "")
    return ""


# ---------------------------------------------------------------------------
# WebSocket restore path
# ---------------------------------------------------------------------------

def _restore_effects_ws(ws, api, layer: int, slot: int,
                        saved_clip_data: dict, log) -> bool:
    """Restore effects and their parameters using REST + WebSocket.

    Steps:
      1. Compare saved vs live effect names (via REST).
      2. Add missing effects via REST POST (synchronous, guaranteed).
      3. Re-read clip from REST to get fresh parameter IDs.
      4. Match saved effect params to live params by key path.
      5. Set each parameter individually via WebSocket (fast).

    Returns True if any effect parameters were successfully set.
    """
    saved_effects = (saved_clip_data.get("video") or {}).get("effects", [])
    if not saved_effects:
        return False

    # Get live clip state from REST to see current effects
    try:
        live_rest = api.get_clip_data(layer, slot)
    except Exception:
        return False
    live_effects = (live_rest.get("video") or {}).get("effects", [])
    live_names = [extract_effect_name(e) for e in live_effects]

    # Add missing effects via REST (synchronous — guaranteed to be present
    # when the call returns, unlike fire-and-forget WebSocket adds).
    added_any = False
    for saved_eff in saved_effects:
        eff_name = extract_effect_name(saved_eff)
        if eff_name and eff_name not in live_names:
            try:
                api.add_clip_effect(layer, slot, eff_name)
                live_names.append(eff_name)
                log(f"    + Re-added effect '{eff_name}' to slot {slot}")
                added_any = True
            except Exception as exc:
                log(f"    Warning: could not add effect '{eff_name}': {exc}")

    # Re-read clip from REST to get fresh parameter IDs (including new effects)
    try:
        live_rest = api.get_clip_data(layer, slot)
    except Exception:
        log(f"    Warning: could not re-read clip {slot} after adding effects")
        return False
    live_effects = (live_rest.get("video") or {}).get("effects", [])

    # Match saved effects to live effects by name, then set params via WS
    params_set = 0
    matched = _match_effects_by_name(saved_effects, live_effects)

    for saved_eff, live_eff in matched:
        pairs = _match_effect_params(saved_eff, live_eff)
        for live_id, value in pairs:
            if ws.set_parameter(live_id, value):
                params_set += 1

    if params_set:
        log(f"    Set {params_set} effect parameter(s) via WebSocket for slot {slot}")
    return params_set > 0


# ---------------------------------------------------------------------------
# REST fallback restore path
# ---------------------------------------------------------------------------

def _ensure_effects_exist(api, layer: int, slot: int,
                          saved_clip_data: dict, log) -> bool:
    """Ensure all saved effects exist on the clip (REST fallback).

    Compares saved vs live effects and adds any missing ones via REST POST.
    Does NOT set effect parameters — that's handled by the WS path or
    by the video effects blob PUT in _restorable_sections.
    Returns True if effects were re-added.
    """
    saved_effects = (saved_clip_data.get("video") or {}).get("effects", [])
    if not saved_effects:
        return False

    try:
        live = api.get_clip_data(layer, slot)
    except Exception:
        return False
    live_effects = (live.get("video") or {}).get("effects", [])
    live_names = [extract_effect_name(e) for e in live_effects]

    added = False
    for saved_eff in saved_effects:
        eff_name = extract_effect_name(saved_eff)
        if eff_name and eff_name not in live_names:
            try:
                api.add_clip_effect(layer, slot, eff_name)
                live_names.append(eff_name)
                log(f"    + Re-added effect '{eff_name}' to slot {slot}")
                added = True
            except Exception as exc:
                log(f"    Warning: could not add effect '{eff_name}': {exc}")

    return added


# ---------------------------------------------------------------------------
# Parameter matching
# ---------------------------------------------------------------------------

def _match_effects_by_name(saved_effects: list[dict],
                           live_effects: list[dict]) -> list[tuple]:
    """Match saved effects to live effects by name and order.

    Returns list of (saved_effect, live_effect) tuples.
    If multiple effects share a name, they are matched in order.
    """
    # Group live effects by name
    live_by_name: dict[str, list[dict]] = {}
    for eff in live_effects:
        name = extract_effect_name(eff)
        if name:
            live_by_name.setdefault(name, []).append(eff)

    matched = []
    for saved_eff in saved_effects:
        name = extract_effect_name(saved_eff)
        candidates = live_by_name.get(name, [])
        if candidates:
            matched.append((saved_eff, candidates.pop(0)))

    return matched


def _match_effect_params(saved_effect: dict,
                         live_effect: dict) -> list[tuple[int, object]]:
    """Walk two effect parameter trees and match by structural key path.

    Returns list of (live_param_id, saved_value) tuples for parameters
    that exist in both trees and have different values.
    """
    saved_flat = {}
    _flatten_params(saved_effect, "", saved_flat)

    live_flat = {}
    _flatten_params(live_effect, "", live_flat)

    pairs = []
    for path, saved_param in saved_flat.items():
        live_param = live_flat.get(path)
        if not live_param:
            continue
        live_id = live_param.get("id")
        if live_id is None:
            continue
        saved_value = saved_param.get("value")
        if saved_value is None:
            continue
        # Only set if the value actually differs
        if saved_value != live_param.get("value"):
            pairs.append((live_id, saved_value))

    return pairs


def _flatten_params(obj: dict, prefix: str, out: dict):
    """Recursively flatten a parameter tree into path -> param_object.

    A parameter object is identified by having both "id" and "valuetype" keys.
    The path is built from dict keys separated by "/".
    """
    if not isinstance(obj, dict):
        return

    # Is this a parameter leaf?
    if "id" in obj and "valuetype" in obj:
        out[prefix] = obj
        return

    # Skip keys that are not part of the parameter tree
    skip_keys = {"id", "name", "display_name"}
    for key, val in obj.items():
        if key in skip_keys:
            continue
        if isinstance(val, dict):
            child_path = f"{prefix}/{key}" if prefix else key
            _flatten_params(val, child_path, out)


# ---------------------------------------------------------------------------
# Helpers (moved from watchfolder.py)
# ---------------------------------------------------------------------------

def _strip_nulls(obj):
    """Recursively remove keys with None values from dicts."""
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    elif isinstance(obj, list):
        return [_strip_nulls(item) for item in obj]
    return obj


def _restorable_sections(clip_data: dict,
                         skip_effects: bool = False) -> list[dict]:
    """Break clip data into individual PUTable sections.

    Strips nulls and read-only fields so Arena accepts them.

    Args:
        clip_data:    Full clip JSON from a snapshot.
        skip_effects: If True, omit the video effects section (because
                      effects are being handled separately via WebSocket).
    """
    sections = []

    # 1) transport (speed, direction, position)
    #    Strip transport.position.value — it's the live playback position
    #    which changes every frame and shouldn't be restored.
    #    Keep in/out (cue points), min, max.
    if clip_data.get("transport"):
        transport = _strip_nulls(clip_data["transport"])
        pos = transport.get("position")
        if isinstance(pos, dict):
            pos.pop("value", None)
        sections.append({"transport": transport})

    video = clip_data.get("video")

    # 2) video effects (Transform, Blur, etc.)
    if not skip_effects and video and video.get("effects"):
        cleaned_effects = []
        for eff in video["effects"]:
            ce = _strip_nulls(eff)
            ce.pop("id", None)  # effect IDs are instance-specific
            cleaned_effects.append(ce)
        sections.append({"video": {"effects": cleaned_effects}})

    # 3) video properties (opacity, resize, color channels)
    if video:
        vid_props = {}
        for key in ("opacity", "resize", "r", "g", "b", "a"):
            if video.get(key) is not None:
                vid_props[key] = _strip_nulls(video[key])
        if vid_props:
            sections.append({"video": vid_props})

    # 4) audio (volume, pan)
    audio = clip_data.get("audio")
    if audio:
        audio_props = {}
        for key in ("volume", "pan"):
            if audio.get(key) is not None:
                audio_props[key] = _strip_nulls(audio[key])
        if audio_props:
            sections.append({"audio": audio_props})

    # 5) clip name
    if clip_data.get("name") is not None:
        sections.append({"name": _strip_nulls(clip_data["name"])})

    # 6) simple top-level fields
    for key in ("transporttype", "target", "triggerstyle", "ignorecolumntrigger",
                "faderstart", "beatsnap", "dashboard"):
        if clip_data.get(key) is not None:
            sections.append({key: _strip_nulls(clip_data[key])})

    # 7) transition
    if clip_data.get("transition"):
        cleaned = _strip_nulls(clip_data["transition"])
        if cleaned:
            sections.append({"transition": cleaned})

    return sections
