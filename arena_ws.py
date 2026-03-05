"""Synchronous WebSocket client for Resolume Arena.

Connects to Arena's WebSocket API (ws://{host}:{port}/api/v1) and provides
methods for real-time parameter control and composition state queries.

This module is completely standalone — no imports from other project files.
"""

import json
import time
import urllib.parse

try:
    import websocket
except ImportError:
    websocket = None


class ArenaWebSocket:
    """Synchronous WebSocket client for Resolume Arena.

    On connect(), receives the initial composition_state which contains
    all parameter IDs needed for precise parameter-by-ID updates.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8080,
                 timeout: float = 10.0, logger=None):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._log = logger or print
        self._ws = None
        self._composition = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Connect and receive the initial composition_state.

        Returns True on success, False on failure.
        """
        if websocket is None:
            self._log("  WebSocket: websocket-client library not installed")
            return False

        uri = f"ws://{self._host}:{self._port}/api/v1"
        try:
            self._ws = websocket.create_connection(uri, timeout=self._timeout)
        except Exception as exc:
            self._log(f"  WebSocket: could not connect to {uri}: {exc}")
            self._ws = None
            return False

        # Arena sends composition_state, sources_update, effects_update on connect.
        # We only need the composition_state (identified by having "layers" key
        # and no "type" key).
        if not self._read_composition_state():
            self.close()
            return False

        return True

    def close(self):
        """Close the WebSocket connection."""
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    @property
    def connected(self) -> bool:
        """Whether the WebSocket is currently connected."""
        return self._ws is not None

    # ------------------------------------------------------------------
    # Effect management
    # ------------------------------------------------------------------

    def add_clip_effect(self, clip_id: int, effect_name: str) -> bool:
        """Add a video effect to a clip by name.

        Uses the WebSocket post action with an effect URI.
        Returns True on success.
        """
        encoded = urllib.parse.quote(effect_name, safe="")
        msg = {
            "action": "post",
            "path": f"/composition/clips/by-id/{clip_id}/effects/video/add",
            "body": f"effect:///video/{encoded}",
        }
        return self._send(msg)

    # ------------------------------------------------------------------
    # Parameter control
    # ------------------------------------------------------------------

    def set_parameter(self, param_id: int, value) -> bool:
        """Set a parameter value by its numeric ID.

        Returns True if the message was sent successfully.
        """
        msg = {
            "action": "set",
            "parameter": f"/parameter/by-id/{param_id}",
            "value": value,
        }
        return self._send(msg)

    # ------------------------------------------------------------------
    # Composition state queries
    # ------------------------------------------------------------------

    def get_clip_state(self, layer_idx: int, clip_idx: int) -> dict | None:
        """Look up a clip in the cached composition_state.

        Args:
            layer_idx: 1-based layer index.
            clip_idx:  1-based clip slot index.

        Returns the clip dict (with full parameter IDs) or None.
        """
        if not self._composition:
            return None
        layers = self._composition.get("layers", [])
        if layer_idx < 1 or layer_idx > len(layers):
            return None
        clips = layers[layer_idx - 1].get("clips", [])
        if clip_idx < 1 or clip_idx > len(clips):
            return None
        return clips[clip_idx - 1]

    def refresh_composition(self) -> bool:
        """Re-read the composition state after a structural change.

        After adding effects or layers, Arena broadcasts an updated
        composition_state. This drains incoming messages until one
        arrives (with timeout).

        Returns True if a new composition_state was received.
        """
        return self._read_composition_state()

    @property
    def composition(self) -> dict | None:
        """The most recently received composition_state."""
        return self._composition

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send(self, msg: dict) -> bool:
        """Send a JSON message over the WebSocket."""
        if not self._ws:
            return False
        try:
            self._ws.send(json.dumps(msg))
            return True
        except Exception as exc:
            self._log(f"  WebSocket send error: {exc}")
            return False

    def _read_composition_state(self) -> bool:
        """Read messages until a composition_state arrives or timeout."""
        if not self._ws:
            return False

        deadline = time.time() + self._timeout
        old_timeout = self._ws.gettimeout()

        try:
            while time.time() < deadline:
                remaining = max(0.1, deadline - time.time())
                self._ws.settimeout(remaining)
                try:
                    raw = self._ws.recv()
                except websocket.WebSocketTimeoutException:
                    break
                except Exception:
                    break

                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                # composition_state has "layers" but no "type" field
                if "layers" in data and "type" not in data:
                    self._composition = data
                    return True
        finally:
            try:
                self._ws.settimeout(old_timeout)
            except Exception:
                pass

        return False
