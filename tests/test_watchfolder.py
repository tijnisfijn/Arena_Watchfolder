"""Tests for watchfolder.py — helpers, snapshots, and sync logic."""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add parent to path so imports work
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from watchfolder import (
    normalize_path,
    _sanitize_dirname,
    _extract_clip_name,
    _extract_source_type,
    scan_folder,
    sync_folder_to_layer,
    merge_snapshots,
    load_combined_snapshot,
    save_combined_snapshot,
    merge_with_combined,
    get_cross_layer_entries,
    SNAPSHOT_FILENAME,
)


# ---------------------------------------------------------------------------
# normalize_path
# ---------------------------------------------------------------------------

class TestNormalizePath:
    def test_none(self):
        assert normalize_path(None) is None

    def test_file_uri(self):
        result = normalize_path("file:///Users/test/video.mov")
        assert result == str(Path("/Users/test/video.mov").resolve())

    def test_encoded_uri(self):
        result = normalize_path("file:///Users/test/my%20video.mov")
        assert "my video.mov" in result

    def test_plain_path(self):
        result = normalize_path("/Users/test/video.mov")
        assert result == str(Path("/Users/test/video.mov").resolve())


# ---------------------------------------------------------------------------
# _sanitize_dirname
# ---------------------------------------------------------------------------

class TestSanitizeDirname:
    def test_clean_name(self):
        assert _sanitize_dirname("My Layer") == "My Layer"

    def test_invalid_chars(self):
        result = _sanitize_dirname('layer<>:"/\\|?*name')
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result

    def test_leading_dots(self):
        assert _sanitize_dirname("...hidden") == "hidden"

    def test_empty_becomes_untitled(self):
        assert _sanitize_dirname("") == "Untitled"

    def test_all_special_becomes_untitled(self):
        assert _sanitize_dirname("...") == "Untitled"


# ---------------------------------------------------------------------------
# _extract_clip_name
# ---------------------------------------------------------------------------

class TestExtractClipName:
    def test_string_name(self):
        assert _extract_clip_name({"name": "Solid Color"}) == "Solid Color"

    def test_param_name(self):
        assert _extract_clip_name({"name": {"value": "Checkered"}}) == "Checkered"

    def test_missing(self):
        assert _extract_clip_name({}) == ""

    def test_none(self):
        assert _extract_clip_name({"name": None}) == ""


# ---------------------------------------------------------------------------
# _extract_source_type
# ---------------------------------------------------------------------------

class TestExtractSourceType:
    def test_basic(self):
        clip = {"video": {"description": "Shaper"}}
        assert _extract_source_type(clip) == "Shaper"

    def test_no_video(self):
        assert _extract_source_type({}) == ""

    def test_no_description(self):
        assert _extract_source_type({"video": {}}) == ""

    def test_description_none(self):
        assert _extract_source_type({"video": {"description": None}}) == ""

    def test_description_not_string(self):
        assert _extract_source_type({"video": {"description": 42}}) == ""

    def test_real_arena_clip(self):
        """Simulate a renamed generator where name != source type."""
        clip = {
            "name": {"value": "Spinner"},
            "video": {"description": "Shaper"},
        }
        assert _extract_source_type(clip) == "Shaper"
        assert _extract_clip_name(clip) == "Spinner"


# ---------------------------------------------------------------------------
# scan_folder
# ---------------------------------------------------------------------------

class TestScanFolder:
    def test_returns_media_files(self, tmp_path):
        (tmp_path / "video.mov").touch()
        (tmp_path / "clip.mp4").touch()
        (tmp_path / "readme.txt").touch()
        result = scan_folder(str(tmp_path))
        assert len(result) == 2
        assert any("video.mov" in r for r in result)
        assert any("clip.mp4" in r for r in result)

    def test_empty_folder(self, tmp_path):
        result = scan_folder(str(tmp_path))
        assert result == []

    def test_nonexistent_folder(self):
        with pytest.raises(ValueError):
            scan_folder("/nonexistent/path")

    def test_sorted_output(self, tmp_path):
        (tmp_path / "z_clip.mov").touch()
        (tmp_path / "a_clip.mov").touch()
        result = scan_folder(str(tmp_path))
        assert "a_clip" in result[0]
        assert "z_clip" in result[1]

    def test_ignores_subdirectories(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        (tmp_path / "video.mov").touch()
        result = scan_folder(str(tmp_path))
        assert len(result) == 1


# ---------------------------------------------------------------------------
# sync_folder_to_layer — snapshot-aware slot placement
# ---------------------------------------------------------------------------

class TestSyncSlotPlacement:
    def _make_api(self):
        api = MagicMock()
        api.get_column_count.return_value = 20
        api.get_layer_name.return_value = "Layer 1"
        api.clear_layer_clips.return_value = None
        api.batch_open_clips.return_value = None
        api.grow_columns.return_value = None
        return api

    def test_force_sync_uses_snapshot_slots(self, tmp_path):
        """Files should be placed in their original snapshot slots."""
        (tmp_path / "a.mov").touch()
        (tmp_path / "b.mov").touch()
        api = self._make_api()
        snapshot = [
            {"slot": 5, "filename": "a.mov", "data": {"x": 1}},
            {"slot": 10, "filename": "b.mov", "data": {"y": 2}},
        ]
        sync_folder_to_layer(api, str(tmp_path), 1, force_full=True, snapshot=snapshot)
        pairs = api.batch_open_clips.call_args[0][1]
        slot_map = {Path(f).name: s for s, f in pairs}
        assert slot_map["a.mov"] == 5
        assert slot_map["b.mov"] == 10

    def test_force_sync_reserves_generator_slots(self, tmp_path):
        """New files should not be placed in generator-reserved slots."""
        (tmp_path / "new.mov").touch()
        api = self._make_api()
        snapshot = [
            {"slot": 1, "source_name": "Metaballs", "source_type": "Metaballs",
             "filename": None, "data": {"gen": True}},
            {"slot": 2, "source_name": "Shaper", "source_type": "Shaper",
             "filename": None, "data": {"gen": True}},
        ]
        sync_folder_to_layer(api, str(tmp_path), 1, force_full=True, snapshot=snapshot)
        pairs = api.batch_open_clips.call_args[0][1]
        slots_used = {s for s, _ in pairs}
        assert 1 not in slots_used  # reserved for Metaballs
        assert 2 not in slots_used  # reserved for Shaper
        assert 3 in slots_used  # new file goes to first free slot

    def test_force_sync_no_snapshot_sequential(self, tmp_path):
        """Without snapshot, files should be placed sequentially."""
        (tmp_path / "a.mov").touch()
        (tmp_path / "b.mov").touch()
        api = self._make_api()
        sync_folder_to_layer(api, str(tmp_path), 1, force_full=True, snapshot=None)
        pairs = api.batch_open_clips.call_args[0][1]
        assert pairs[0][0] == 1
        assert pairs[1][0] == 2

    def test_force_sync_mixed_known_and_new_files(self, tmp_path):
        """Known files use snapshot slots, new files fill remaining gaps."""
        (tmp_path / "a.mov").touch()
        (tmp_path / "b.mov").touch()
        (tmp_path / "new.mov").touch()
        api = self._make_api()
        snapshot = [
            {"slot": 1, "source_name": "Gen", "source_type": "Gen",
             "filename": None, "data": {"gen": True}},
            {"slot": 3, "filename": "a.mov", "data": {"x": 1}},
            {"slot": 5, "filename": "b.mov", "data": {"y": 2}},
        ]
        sync_folder_to_layer(api, str(tmp_path), 1, force_full=True, snapshot=snapshot)
        pairs = api.batch_open_clips.call_args[0][1]
        slot_map = {Path(f).name: s for s, f in pairs}
        assert slot_map["a.mov"] == 3
        assert slot_map["b.mov"] == 5
        assert slot_map["new.mov"] == 2  # skips 1 (reserved for Gen)


# ---------------------------------------------------------------------------
# merge_snapshots
# ---------------------------------------------------------------------------

class TestMergeSnapshots:
    def test_no_old_snap(self):
        new = [{"slot": 1, "filename": "a.mov", "data": {}}]
        result = merge_snapshots(None, new)
        assert result == new

    def test_preserves_removed_clips(self):
        old = [{"slot": 1, "filename": "removed.mov", "data": {"some": "data"}}]
        new = [{"slot": 1, "filename": "new.mov", "data": {}}]
        result = merge_snapshots(old, new)
        assert len(result) == 2
        remembered = [e for e in result if e.get("remembered")]
        assert len(remembered) == 1
        assert remembered[0]["filename"] == "removed.mov"

    def test_no_duplicate_filenames(self):
        old = [{"slot": 1, "filename": "a.mov", "data": {"old": True}}]
        new = [{"slot": 2, "filename": "a.mov", "data": {"new": True}}]
        result = merge_snapshots(old, new)
        # a.mov is in new, so old entry should NOT be remembered
        assert len(result) == 1
        assert result[0]["data"] == {"new": True}

    def test_empty_data_not_remembered(self):
        old = [{"slot": 1, "filename": "a.mov", "data": None}]
        new = []
        result = merge_snapshots(old, new)
        assert len(result) == 0

    def test_generated_sources_preserved(self):
        old = [{"slot": 5, "source_name": "Checkered", "filename": None,
                "data": {"color": "red"}}]
        new = []
        result = merge_snapshots(old, new)
        remembered = [e for e in result if e.get("remembered")]
        assert len(remembered) == 1
        assert remembered[0]["source_name"] == "Checkered"

    def test_generated_source_still_present(self):
        old = [{"slot": 5, "source_name": "Checkered", "filename": None,
                "data": {"color": "red"}}]
        new = [{"slot": 5, "source_name": "Checkered", "filename": None,
                "data": {"color": "blue"}}]
        result = merge_snapshots(old, new)
        # Source is still present, should not be duplicated as remembered
        assert len(result) == 1
        assert result[0]["data"]["color"] == "blue"

    def test_source_type_preserved_in_remembered(self):
        old = [{"slot": 3, "source_name": "Spinner", "source_type": "Shaper",
                "filename": None, "data": {"params": True}}]
        new = []
        result = merge_snapshots(old, new)
        remembered = [e for e in result if e.get("remembered")]
        assert len(remembered) == 1
        assert remembered[0]["source_type"] == "Shaper"
        assert remembered[0]["source_name"] == "Spinner"

    def test_source_type_none_when_not_present(self):
        """Old snapshots without source_type should still work."""
        old = [{"slot": 3, "source_name": "Metaballs", "filename": None,
                "data": {"x": 1}}]
        new = []
        result = merge_snapshots(old, new)
        remembered = [e for e in result if e.get("remembered")]
        assert len(remembered) == 1
        assert remembered[0].get("source_type") is None
        assert remembered[0]["source_name"] == "Metaballs"


# ---------------------------------------------------------------------------
# Combined snapshot file I/O
# ---------------------------------------------------------------------------

class TestCombinedSnapshot:
    def test_save_and_load(self, tmp_path):
        snap = [{"slot": 1, "filename": "a.mov", "data": {"x": 1}}]
        save_combined_snapshot(str(tmp_path), 1, "/path/to/folder", snap, "TestComp")
        result = load_combined_snapshot(str(tmp_path))
        assert result["version"] == 1
        assert result["composition"] == "TestComp"
        assert "1" in result["layers"]
        assert result["layers"]["1"]["clips"][0]["filename"] == "a.mov"

    def test_load_missing_file(self, tmp_path):
        result = load_combined_snapshot(str(tmp_path))
        assert result == {}

    def test_load_empty_folder(self):
        result = load_combined_snapshot("")
        assert result == {}

    def test_save_empty_folder_noop(self):
        # Should not raise
        save_combined_snapshot("", 1, "/path", [], "")

    def test_atomic_write(self, tmp_path):
        """Verify the .tmp file is cleaned up (atomic rename)."""
        snap = [{"slot": 1, "filename": "a.mov", "data": {"x": 1}}]
        save_combined_snapshot(str(tmp_path), 1, "/path", snap, "Test")
        assert (tmp_path / SNAPSHOT_FILENAME).exists()
        assert not (tmp_path / (SNAPSHOT_FILENAME.replace(".json", ".tmp"))).exists()

    def test_updates_existing_layer(self, tmp_path):
        snap1 = [{"slot": 1, "filename": "a.mov", "data": {"x": 1}}]
        snap2 = [{"slot": 1, "filename": "b.mov", "data": {"y": 2}}]
        save_combined_snapshot(str(tmp_path), 1, "/path", snap1, "Test")
        save_combined_snapshot(str(tmp_path), 2, "/path2", snap2, "Test")
        result = load_combined_snapshot(str(tmp_path))
        assert "1" in result["layers"]
        assert "2" in result["layers"]

    def test_skips_entries_without_data(self, tmp_path):
        snap = [
            {"slot": 1, "filename": "a.mov", "data": {"x": 1}},
            {"slot": 2, "filename": None, "data": None},
        ]
        save_combined_snapshot(str(tmp_path), 1, "/path", snap, "Test")
        result = load_combined_snapshot(str(tmp_path))
        assert len(result["layers"]["1"]["clips"]) == 1

    def test_source_entries_persisted(self, tmp_path):
        """Generated source entries (no filename, has source_name) should be saved."""
        snap = [
            {"slot": 1, "filename": "a.mov", "data": {"x": 1}},
            {"slot": 3, "source_name": "Spinner", "source_type": "Shaper",
             "filename": None, "data": {"params": True}},
        ]
        save_combined_snapshot(str(tmp_path), 1, "/path", snap, "Test")
        result = load_combined_snapshot(str(tmp_path))
        clips = result["layers"]["1"]["clips"]
        assert len(clips) == 2
        source_clip = next(c for c in clips if c.get("source_name"))
        assert source_clip["source_name"] == "Spinner"
        assert source_clip["source_type"] == "Shaper"

    def test_empty_slots_not_persisted(self, tmp_path):
        """Empty slots (no filename AND no source_name) should be filtered out."""
        snap = [
            {"slot": 1, "filename": None, "source_name": None, "data": None},
            {"slot": 2, "source_name": "Metaballs", "filename": None,
             "data": {"y": 2}},
        ]
        save_combined_snapshot(str(tmp_path), 1, "/path", snap, "Test")
        result = load_combined_snapshot(str(tmp_path))
        clips = result["layers"]["1"]["clips"]
        assert len(clips) == 1
        assert clips[0]["source_name"] == "Metaballs"


class TestMergeWithCombined:
    def test_source_entries_merged(self, tmp_path):
        """Source entries from combined file should supplement config snap."""
        combined_snap = [
            {"slot": 3, "source_name": "Spinner", "source_type": "Shaper",
             "filename": None, "data": {"params": True}},
        ]
        save_combined_snapshot(str(tmp_path), 1, "/path", combined_snap, "Test")
        config_snap = [{"slot": 1, "filename": "a.mov", "data": {"x": 1}}]
        result = merge_with_combined(config_snap, str(tmp_path), 1)
        assert len(result) == 2
        source = next(e for e in result if e.get("source_name"))
        assert source["source_type"] == "Shaper"

    def test_source_entries_not_duplicated(self, tmp_path):
        """Source already in config_snap should not be duplicated."""
        combined_snap = [
            {"slot": 3, "source_name": "Spinner", "source_type": "Shaper",
             "filename": None, "data": {"old": True}},
        ]
        save_combined_snapshot(str(tmp_path), 1, "/path", combined_snap, "Test")
        config_snap = [
            {"slot": 3, "source_name": "Spinner", "source_type": "Shaper",
             "filename": None, "data": {"new": True}},
        ]
        result = merge_with_combined(config_snap, str(tmp_path), 1)
        assert len(result) == 1
        assert result[0]["data"]["new"] is True


class TestGetCrossLayerEntries:
    def test_excludes_current_layer(self, tmp_path):
        snap1 = [{"slot": 1, "filename": "a.mov", "data": {"x": 1}}]
        snap2 = [{"slot": 1, "filename": "b.mov", "data": {"y": 2}}]
        save_combined_snapshot(str(tmp_path), 1, "/path", snap1, "Test")
        save_combined_snapshot(str(tmp_path), 2, "/path", snap2, "Test")
        entries = get_cross_layer_entries(str(tmp_path), 1)
        assert len(entries) == 1
        assert entries[0]["filename"] == "b.mov"

    def test_empty_folder(self):
        entries = get_cross_layer_entries("", 1)
        assert entries == []


# ---------------------------------------------------------------------------
# Config (atomic writes)
# ---------------------------------------------------------------------------

class TestConfig:
    def test_save_and_load(self, tmp_path):
        from config import save_config, load_config, _config_path
        # Temporarily override config path
        import config
        original = config._config_path
        config._config_path = lambda: tmp_path / "test_config.json"
        try:
            data = {"host": "127.0.0.1", "port": 8080, "sets": []}
            save_config(data)
            loaded = load_config()
            assert loaded["host"] == "127.0.0.1"
            assert loaded["port"] == 8080
        finally:
            config._config_path = original

    def test_atomic_write_no_tmp_leftover(self, tmp_path):
        import config
        original = config._config_path
        config._config_path = lambda: tmp_path / "test_config.json"
        try:
            config.save_config({"test": True})
            assert (tmp_path / "test_config.json").exists()
            assert not (tmp_path / "test_config.tmp").exists()
        finally:
            config._config_path = original

    def test_load_missing_returns_defaults(self, tmp_path):
        import config
        original = config._config_path
        config._config_path = lambda: tmp_path / "nonexistent.json"
        try:
            result = config.load_config()
            assert "sets" in result
            assert result["host"] == "127.0.0.1"
        finally:
            config._config_path = original

    def test_load_corrupted_returns_defaults(self, tmp_path):
        import config
        original = config._config_path
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json{{{")
        config._config_path = lambda: bad_file
        try:
            result = config.load_config()
            assert "sets" in result  # defaults
        finally:
            config._config_path = original
