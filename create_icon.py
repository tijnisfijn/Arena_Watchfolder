#!/usr/bin/env python3
"""Generate app icons for Arena Watchfolder.

Creates icon.icns (macOS) and icon.ico (Windows) from a simple
programmatic design — purple folder shape on a dark background,
matching the app's dark theme.

Usage:
    python create_icon.py
"""

import io
import struct
import platform
from pathlib import Path
from PIL import Image, ImageDraw

# App brand color (matches tray icon and UI accent)
ACCENT = (124, 131, 255)        # #7C83FF
BG_DARK = (30, 30, 36)          # Dark background matching the UI
BG_MID = (44, 44, 52)           # Slightly lighter for depth
WHITE = (255, 255, 255)

SIZES = [16, 32, 64, 128, 256, 512, 1024]


def draw_icon(size: int) -> Image.Image:
    """Draw a single icon at the given size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size  # shorthand

    # Rounded-rect background
    margin = int(s * 0.06)
    radius = int(s * 0.18)
    d.rounded_rectangle(
        [margin, margin, s - margin, s - margin],
        radius=radius,
        fill=BG_DARK,
    )

    # Folder body (rounded rect)
    fx1 = int(s * 0.18)
    fy1 = int(s * 0.32)
    fx2 = int(s * 0.82)
    fy2 = int(s * 0.78)
    fr = int(s * 0.06)
    d.rounded_rectangle([fx1, fy1, fx2, fy2], radius=fr, fill=ACCENT)

    # Folder tab (small rounded rect on top-left of the folder body)
    tx1 = fx1
    ty1 = int(s * 0.24)
    tx2 = int(s * 0.48)
    ty2 = fy1 + fr
    tr = int(s * 0.04)
    d.rounded_rectangle([tx1, ty1, tx2, ty2], radius=tr, fill=ACCENT)

    # Sync arrows (two small triangles in the folder body)
    cx = int(s * 0.50)
    cy = int(s * 0.55)
    arrow_size = int(s * 0.09)

    # Right-pointing arrow (top)
    ax = cx + int(s * 0.02)
    ay = cy - int(s * 0.04)
    d.polygon([
        (ax - arrow_size, ay - arrow_size // 2),
        (ax + arrow_size, ay),
        (ax - arrow_size, ay + arrow_size // 2),
    ], fill=WHITE)

    # Left-pointing arrow (bottom)
    ax2 = cx - int(s * 0.02)
    ay2 = cy + int(s * 0.06)
    d.polygon([
        (ax2 + arrow_size, ay2 - arrow_size // 2),
        (ax2 - arrow_size, ay2),
        (ax2 + arrow_size, ay2 + arrow_size // 2),
    ], fill=WHITE)

    return img


def create_ico(images: dict[int, Image.Image], path: Path):
    """Create a .ico file from multiple sizes."""
    # Use PIL's built-in ICO save (supports up to 256x256)
    ico_sizes = [s for s in sorted(images.keys()) if s <= 256]
    imgs = [images[s] for s in ico_sizes]
    imgs[0].save(
        path,
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
        append_images=imgs[1:],
    )


def create_icns(images: dict[int, Image.Image], path: Path):
    """Create a .icns file from multiple sizes."""
    # macOS icns type codes for each size
    type_map = {
        16: b"icp4",    # 16x16  PNG
        32: b"icp5",    # 32x32  PNG
        64: b"icp6",    # 64x64  PNG
        128: b"ic07",   # 128x128 PNG
        256: b"ic08",   # 256x256 PNG
        512: b"ic09",   # 512x512 PNG
        1024: b"ic10",  # 1024x1024 PNG
    }

    entries = []
    for size, type_code in type_map.items():
        if size not in images:
            continue
        buf = io.BytesIO()
        images[size].save(buf, format="PNG")
        png_data = buf.getvalue()
        # Each entry: type (4 bytes) + length (4 bytes) + data
        entry_length = 8 + len(png_data)
        entry = type_code + struct.pack(">I", entry_length) + png_data
        entries.append(entry)

    # icns header: 'icns' + total file length
    body = b"".join(entries)
    total_length = 8 + len(body)
    icns_data = b"icns" + struct.pack(">I", total_length) + body

    path.write_bytes(icns_data)


def main():
    root = Path(__file__).parent

    # Generate all sizes
    print("Generating icon images...")
    images = {}
    for size in SIZES:
        images[size] = draw_icon(size)
        print(f"  {size}x{size}")

    # Save .ico (Windows)
    ico_path = root / "icon.ico"
    create_ico(images, ico_path)
    print(f"Saved {ico_path}")

    # Save .icns (macOS)
    icns_path = root / "icon.icns"
    create_icns(images, icns_path)
    print(f"Saved {icns_path}")

    # Also save a 512x PNG for reference
    png_path = root / "icon.png"
    images[512].save(png_path, format="PNG")
    print(f"Saved {png_path}")

    print("Done!")


if __name__ == "__main__":
    main()
