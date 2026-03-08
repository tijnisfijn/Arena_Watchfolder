#!/usr/bin/env python3
"""Build Arena Watchfolder as a standalone app using PyInstaller.

Usage:
    python build.py            # build for the current platform
    python build.py --clean    # remove previous build artifacts first

Produces:
    macOS:   dist/Arena Watchfolder.app
    Windows: dist/Arena Watchfolder/Arena Watchfolder.exe
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "Arena Watchfolder"
ENTRY_POINT = "watchfolder.py"
ROOT = Path(__file__).parent

# Modules that are imported conditionally or lazily
HIDDEN_IMPORTS = [
    # Project modules (imported inside functions)
    "desktop",
    "config",
    "restore",
    "arena_ws",
    # pywebview
    "webview",
    # System tray (Windows/Linux)
    "pystray",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    # Watchdog (imported inside watch_folder())
    "watchdog",
    "watchdog.observers",
    "watchdog.observers.polling",
    "watchdog.events",
    # WebSocket (conditionally imported)
    "websocket",
]

# Data files to bundle: (source, dest_dir_in_bundle)
DATA_FILES = [
    ("templates", "templates"),
]


def clean():
    """Remove previous build artifacts."""
    for d in ["build", "dist"]:
        p = ROOT / d
        if p.exists():
            print(f"Removing {p}/")
            shutil.rmtree(p)
    spec = ROOT / f"{APP_NAME}.spec"
    if spec.exists():
        print(f"Removing {spec}")
        spec.unlink()


def build():
    system = platform.system()
    print(f"Building {APP_NAME} for {system}...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--windowed",              # no console window
        "--noconfirm",             # overwrite without asking
    ]

    # Icon
    if system == "Darwin":
        icon = ROOT / "icon.icns"
        if icon.exists():
            cmd += ["--icon", str(icon)]
        cmd += [
            "--osx-bundle-identifier", "com.tijnisfijn.arena-watchfolder",
        ]
    elif system == "Windows":
        icon = ROOT / "icon.ico"
        if icon.exists():
            cmd += ["--icon", str(icon)]

    # Hidden imports
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]

    # Data files
    sep = ";" if system == "Windows" else ":"
    for src, dest in DATA_FILES:
        cmd += ["--add-data", f"{src}{sep}{dest}"]

    # Entry point
    cmd.append(ENTRY_POINT)

    print(f"Running: {' '.join(cmd[:6])} ... {cmd[-1]}")
    result = subprocess.run(cmd, cwd=ROOT)

    if result.returncode != 0:
        print("\nBuild FAILED.")
        sys.exit(1)

    # Post-build summary
    if system == "Darwin":
        app_path = ROOT / "dist" / f"{APP_NAME}.app"
        print(f"\nBuild complete: {app_path}")
        print(f"  To run: open \"{app_path}\"")
        print(f"  To distribute: zip the .app and upload to GitHub Releases")
    elif system == "Windows":
        exe_path = ROOT / "dist" / APP_NAME / f"{APP_NAME}.exe"
        print(f"\nBuild complete: {exe_path}")
        print(f"  To distribute: zip the '{APP_NAME}' folder and upload to GitHub Releases")
    else:
        print(f"\nBuild complete: dist/{APP_NAME}/")


def main():
    if "--clean" in sys.argv:
        clean()

    # Check PyInstaller is installed
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Check desktop dependencies
    missing = []
    for pkg, name in [("webview", "pywebview"), ("PIL", "Pillow")]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(name)
    if missing:
        print(f"Installing missing desktop dependencies: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)

    build()


if __name__ == "__main__":
    main()
