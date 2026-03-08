"""
Desktop app wrapper for Arena Watchfolder.

Starts the Flask web app inside a native window (pywebview) with an optional
system tray icon (pystray). On macOS the tray is skipped because both pywebview
and pystray require the main thread — the Quit button in the UI is used instead.

Usage:
    python watchfolder.py --desktop
"""

import os
import platform
import socket
import threading

import webview

from watchfolder import create_web_app, log


def _find_free_port() -> int:
    """Find a random free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_flask(app, port: int):
    """Run the Flask server in a daemon thread."""
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


def _can_use_tray() -> bool:
    """Check whether system tray is usable on this platform.

    macOS requires both pywebview and pystray to own the main thread,
    so they can't coexist — skip the tray on macOS.
    """
    if platform.system() == "Darwin":
        return False
    try:
        import pystray          # noqa: F401
        from PIL import Image   # noqa: F401
        return True
    except ImportError:
        return False


def _start_tray(window, on_quit):
    """Start the system tray icon (Windows/Linux only)."""
    import pystray
    from PIL import Image, ImageDraw

    # Generate a simple tray icon (purple circle on transparent background)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, 56, 56], fill=(124, 131, 255, 255))

    def show_window(icon, item):
        if window:
            window.show()

    def quit_app(icon, item):
        icon.stop()
        on_quit()

    menu = pystray.Menu(
        pystray.MenuItem("Open Window", show_window, default=True),
        pystray.MenuItem("Quit", quit_app),
    )

    icon = pystray.Icon("watchfolder", img, "Arena Watchfolder", menu)
    icon.run()


def main():
    port = _find_free_port()
    app = create_web_app(desktop_mode=True)

    # Start Flask in a background thread
    flask_thread = threading.Thread(
        target=_start_flask, args=(app, port), daemon=True,
    )
    flask_thread.start()

    url = f"http://127.0.0.1:{port}"
    log(f"  Desktop mode: Flask running on {url}")

    use_tray = _can_use_tray()

    # -- Expose Python helpers to JavaScript (window.pywebviewApi) --
    class Api:
        def pick_folder(self, start_path=""):
            """Open a native folder-picker dialog.

            Returns the selected folder path, or None if cancelled.
            Uses the OS file dialog which has proper macOS TCC access
            (~/Documents, ~/Desktop, etc.).
            """
            result = window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=start_path or "",
            )
            if result and len(result) > 0:
                return result[0]
            return None

        def pick_avc_file(self, start_path=""):
            """Open a native file-picker dialog filtered to .avc files.

            Returns the selected file path, or None if cancelled.
            """
            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=start_path or "",
                file_types=("Arena Composition (*.avc)",),
            )
            if result and len(result) > 0:
                return result[0]
            return None

        def list_avc_files(self, folder):
            """List .avc composition names in a folder.

            Uses os.listdir which gets TCC access when the app was
            launched via the native window (inherited from NSOpenPanel
            grants or Full Disk Access).  Falls back gracefully.
            """
            import os
            try:
                names = []
                for name in sorted(os.listdir(folder)):
                    if name.lower().endswith(".avc") and not name.startswith("."):
                        names.append(name[:-4])  # strip .avc
                return names
            except (PermissionError, FileNotFoundError, OSError):
                return []

    js_api = Api()

    # Create the native window
    window = webview.create_window(
        "Arena Watchfolder",
        url,
        width=1200,
        height=800,
        min_size=(800, 500),
        js_api=js_api,
    )

    if use_tray:
        def on_quit():
            for w in webview.windows:
                w.destroy()

        # Start tray in a background thread (works on Windows/Linux)
        tray_thread = threading.Thread(
            target=_start_tray, args=(window, on_quit), daemon=True,
        )
        tray_thread.start()

        # Closing the window minimizes to tray instead of quitting
        def on_closing():
            window.hide()
            return False  # Prevent actual close

        window.events.closing += on_closing

    # Start the webview event loop (must be on main thread for macOS)
    webview.start()

    # If we get here the window was closed — exit cleanly
    os._exit(0)


if __name__ == "__main__":
    main()
