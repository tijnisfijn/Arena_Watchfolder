"""Tests for restore.py — pure functions that match/flatten effect parameters."""

import pytest
from restore import (
    extract_effect_name,
    _get_clip_name,
    _best_match,
    _match_effects_by_name,
    _match_effect_params,
    _flatten_params,
    _strip_nulls,
    _restorable_sections,
)


# ---------------------------------------------------------------------------
# extract_effect_name
# ---------------------------------------------------------------------------

class TestExtractEffectName:
    def test_string_name(self):
        assert extract_effect_name({"name": "Blur"}) == "Blur"

    def test_param_object_name(self):
        assert extract_effect_name({"name": {"value": "Blur", "valuetype": "ParamString"}}) == "Blur"

    def test_missing_name(self):
        assert extract_effect_name({}) == ""

    def test_none_name(self):
        assert extract_effect_name({"name": None}) == ""

    def test_empty_param_value(self):
        assert extract_effect_name({"name": {"valuetype": "ParamString"}}) == ""


# ---------------------------------------------------------------------------
# _get_clip_name
# ---------------------------------------------------------------------------

class TestGetClipName:
    def test_direct_string(self):
        assert _get_clip_name({"name": "My Clip"}) == "My Clip"

    def test_nested_data(self):
        assert _get_clip_name({"data": {"name": "Nested"}}) == "Nested"

    def test_param_object(self):
        assert _get_clip_name({"data": {"name": {"value": "Param"}}}) == "Param"

    def test_missing(self):
        assert _get_clip_name({}) == ""
        assert _get_clip_name({"data": {}}) == ""


# ---------------------------------------------------------------------------
# _strip_nulls
# ---------------------------------------------------------------------------

class TestStripNulls:
    def test_removes_none_values(self):
        assert _strip_nulls({"a": 1, "b": None}) == {"a": 1}

    def test_nested_dicts(self):
        assert _strip_nulls({"a": {"b": None, "c": 2}}) == {"a": {"c": 2}}

    def test_lists(self):
        assert _strip_nulls([{"a": None, "b": 1}, {"c": None}]) == [{"b": 1}, {}]

    def test_scalar(self):
        assert _strip_nulls(42) == 42
        assert _strip_nulls("hello") == "hello"

    def test_empty_dict(self):
        assert _strip_nulls({}) == {}

    def test_all_none(self):
        assert _strip_nulls({"a": None, "b": None}) == {}


# ---------------------------------------------------------------------------
# _flatten_params
# ---------------------------------------------------------------------------

class TestFlattenParams:
    def test_leaf_param(self):
        out = {}
        _flatten_params({"id": 123, "valuetype": "ParamRange", "value": 0.5}, "", out)
        assert "" in out
        assert out[""]["value"] == 0.5

    def test_nested_params(self):
        tree = {
            "opacity": {"id": 1, "valuetype": "ParamRange", "value": 0.8},
            "resize": {
                "scale": {"id": 2, "valuetype": "ParamRange", "value": 1.0}
            },
        }
        out = {}
        _flatten_params(tree, "", out)
        assert "opacity" in out
        assert out["opacity"]["value"] == 0.8
        assert "resize/scale" in out
        assert out["resize/scale"]["value"] == 1.0

    def test_skips_id_name_keys(self):
        tree = {
            "id": 99,
            "name": "Transform",
            "display_name": "Transform",
            "opacity": {"id": 1, "valuetype": "ParamRange", "value": 1.0},
        }
        out = {}
        _flatten_params(tree, "", out)
        assert len(out) == 1
        assert "opacity" in out

    def test_non_dict_ignored(self):
        out = {}
        _flatten_params("not a dict", "", out)
        assert out == {}

    def test_empty_dict(self):
        out = {}
        _flatten_params({}, "", out)
        assert out == {}


# ---------------------------------------------------------------------------
# _match_effects_by_name
# ---------------------------------------------------------------------------

class TestMatchEffectsByName:
    def test_basic_matching(self):
        saved = [{"name": "Blur"}, {"name": "Mirror"}]
        live = [{"name": "Blur"}, {"name": "Mirror"}]
        matched = _match_effects_by_name(saved, live)
        assert len(matched) == 2
        assert matched[0] == (saved[0], live[0])

    def test_duplicate_names_ordered(self):
        saved = [{"name": "Blur"}, {"name": "Blur"}]
        live = [{"name": "Blur"}, {"name": "Blur"}]
        matched = _match_effects_by_name(saved, live)
        assert len(matched) == 2
        assert matched[0] == (saved[0], live[0])
        assert matched[1] == (saved[1], live[1])

    def test_no_match(self):
        saved = [{"name": "Blur"}]
        live = [{"name": "Mirror"}]
        matched = _match_effects_by_name(saved, live)
        assert len(matched) == 0

    def test_empty_lists(self):
        assert _match_effects_by_name([], []) == []
        assert _match_effects_by_name([{"name": "Blur"}], []) == []

    def test_param_object_names(self):
        saved = [{"name": {"value": "Blur", "valuetype": "ParamString"}}]
        live = [{"name": {"value": "Blur", "valuetype": "ParamString"}}]
        matched = _match_effects_by_name(saved, live)
        assert len(matched) == 1


# ---------------------------------------------------------------------------
# _match_effect_params
# ---------------------------------------------------------------------------

class TestMatchEffectParams:
    def test_matching_params(self):
        saved = {
            "opacity": {"id": 100, "valuetype": "ParamRange", "value": 0.5},
        }
        live = {
            "opacity": {"id": 200, "valuetype": "ParamRange", "value": 1.0},
        }
        pairs = _match_effect_params(saved, live)
        assert len(pairs) == 1
        assert pairs[0] == (200, 0.5)  # live_id, saved_value

    def test_same_value_skipped(self):
        saved = {
            "opacity": {"id": 100, "valuetype": "ParamRange", "value": 0.5},
        }
        live = {
            "opacity": {"id": 200, "valuetype": "ParamRange", "value": 0.5},
        }
        pairs = _match_effect_params(saved, live)
        assert len(pairs) == 0

    def test_no_matching_paths(self):
        saved = {
            "blur": {"id": 1, "valuetype": "ParamRange", "value": 0.5},
        }
        live = {
            "mirror": {"id": 2, "valuetype": "ParamRange", "value": 1.0},
        }
        pairs = _match_effect_params(saved, live)
        assert len(pairs) == 0

    def test_missing_live_id(self):
        saved = {
            "opacity": {"id": 1, "valuetype": "ParamRange", "value": 0.5},
        }
        live = {
            "opacity": {"valuetype": "ParamRange", "value": 1.0},
        }
        pairs = _match_effect_params(saved, live)
        assert len(pairs) == 0


# ---------------------------------------------------------------------------
# _best_match
# ---------------------------------------------------------------------------

class TestBestMatch:
    def test_slot_match_priority(self):
        entries = [
            {"slot": 1, "filename": "a.mov", "data": {}},
            {"slot": 3, "filename": "a.mov", "data": {}},
        ]
        clip = {"slot": 3, "path": "/a.mov"}
        result = _best_match(entries, clip)
        assert result["slot"] == 3
        assert len(entries) == 1  # popped

    def test_name_match_fallback(self):
        entries = [
            {"slot": 5, "filename": "a.mov", "data": {"name": "MyClip"}},
        ]
        clip = {"slot": 99, "path": "/a.mov", "data": {"name": "MyClip"}}
        result = _best_match(entries, clip)
        assert result["slot"] == 5

    def test_fifo_fallback(self):
        entries = [
            {"slot": 10, "filename": "a.mov", "data": {}},
            {"slot": 20, "filename": "a.mov", "data": {}},
        ]
        clip = {"slot": 99, "path": "/a.mov"}
        result = _best_match(entries, clip)
        assert result["slot"] == 10  # first one


# ---------------------------------------------------------------------------
# _restorable_sections
# ---------------------------------------------------------------------------

class TestRestorableSections:
    def test_transport_strips_position_value(self):
        clip_data = {
            "transport": {
                "position": {"value": 0.42, "min": 0.0, "max": 1.0},
                "controls": {"speed": {"value": 1.0}},
            }
        }
        sections = _restorable_sections(clip_data)
        assert len(sections) == 1
        transport = sections[0]["transport"]
        assert "value" not in transport["position"]
        assert transport["position"]["min"] == 0.0

    def test_effects_stripped_of_ids(self):
        clip_data = {
            "video": {
                "effects": [
                    {"id": 123, "name": "Blur", "amount": {"value": 0.5}},
                ]
            }
        }
        sections = _restorable_sections(clip_data)
        effects_section = next(s for s in sections if "video" in s and "effects" in s["video"])
        assert "id" not in effects_section["video"]["effects"][0]

    def test_skip_effects_flag(self):
        clip_data = {
            "video": {
                "effects": [{"name": "Blur"}],
                "opacity": {"value": 0.5},
            }
        }
        sections = _restorable_sections(clip_data, skip_effects=True)
        for s in sections:
            if "video" in s:
                assert "effects" not in s["video"]

    def test_audio_section(self):
        clip_data = {
            "audio": {"volume": {"value": 0.8}, "pan": {"value": 0.0}},
        }
        sections = _restorable_sections(clip_data)
        audio_section = next(s for s in sections if "audio" in s)
        assert "volume" in audio_section["audio"]
        assert "pan" in audio_section["audio"]

    def test_name_section(self):
        clip_data = {"name": {"value": "My Clip", "valuetype": "ParamString"}}
        sections = _restorable_sections(clip_data)
        assert any("name" in s for s in sections)

    def test_sourceparams(self):
        clip_data = {
            "video": {
                "sourceparams": {"color": {"value": "#FF0000"}},
            }
        }
        sections = _restorable_sections(clip_data)
        sp = next(s for s in sections if "video" in s and "sourceparams" in s["video"])
        assert sp["video"]["sourceparams"]["color"]["value"] == "#FF0000"

    def test_transition(self):
        clip_data = {"transition": {"duration": {"value": 1.0}}}
        sections = _restorable_sections(clip_data)
        assert any("transition" in s for s in sections)

    def test_empty_clip_data(self):
        assert _restorable_sections({}) == []

    def test_simple_fields(self):
        clip_data = {"beatsnap": {"value": True}, "faderstart": {"value": False}}
        sections = _restorable_sections(clip_data)
        assert any("beatsnap" in s for s in sections)
        assert any("faderstart" in s for s in sections)
