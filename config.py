"""Persistent configuration for Arena Watchfolder."""

import json
from pathlib import Path


def default_compositions_folder() -> str:
    """Return the platform-appropriate default Compositions folder.

    macOS:   ~/Documents/Resolume Arena/Compositions
    Windows: ~\\Documents\\Resolume Arena\\Compositions
    """
    return str(
        Path.home() / "Documents" / "Resolume Arena" / "Compositions"
    )


def _config_path() -> Path:
    return Path(__file__).parent / "watchfolder_config.json"


def load_config() -> dict:
    """Load configuration from disk, or return defaults if not found."""
    path = _config_path()
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return _defaults()
    return _defaults()


def save_config(config: dict):
    """Save configuration to disk (atomic write)."""
    path = _config_path()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2)
    tmp.replace(path)


def _defaults() -> dict:
    return {
        "host": "127.0.0.1",
        "port": 8080,
        "sets": [
            {
                "id": "1",
                "name": "Default",
                "mappings": [],
                "snapshots": {},
            }
        ],
        "active_set_id": "1",
        "locked_composition": None,
        "locked_deck": None,
        "options": {
            "rename_layers": False,
            "composition_lock": False,
            "compositions_folder": default_compositions_folder(),
            "snapshot_folder": "",
        },
    }
