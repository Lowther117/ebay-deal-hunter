#!/usr/bin/env python3
"""
Generate the eBay Deal Hunter app icon from scratch with Pillow.

Nothing is loaded from disk - the artwork is drawn programmatically, so the
build machine only needs Pillow. Everything is drawn on a 4x canvas and
downsampled with LANCZOS, which gives clean antialiased edges without any
external image assets.

Design (deliberately simple so it survives 16x16):
    1. a rounded-square badge with a deep blue vertical gradient
    2. a bold white magnifying glass (solid disc + thick angled handle)
    3. a deep blue downward "price drop" arrow inside the lens

Outputs, relative to the repo root:
    assets/icon.png            1024x1024 master
    assets/icon.ico            Windows multi-size icon (16..256)
    assets/icon.iconset/       macOS iconset folder (icon_16x16 .. icon_512x512@2x)
    assets/icon.icns           only if `iconutil` is available (macOS only)

Run:
    python3 tools/make_icons.py

Install Pillow first if needed:
    pip install pillow --break-system-packages
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - helpful message rather than a traceback
    sys.exit(
        "Pillow is required to build the icons.\n"
        "Install it with:  pip install pillow --break-system-packages"
    )

# --------------------------------------------------------------------------
# Layout constants, all expressed in the 1024x1024 design space.
# --------------------------------------------------------------------------

MASTER = 1024          # size of the finished master PNG
SS = 4                 # supersampling factor - we draw at MASTER * SS
CANVAS = MASTER * SS

BADGE_RADIUS = 230     # rounded-square corner radius

GRAD_TOP = (42, 120, 214)     # #2a78d6
GRAD_BOTTOM = (24, 79, 149)   # #184f95
WHITE = (255, 255, 255, 255)
DEEP_BLUE = (24, 79, 149, 255)

LENS_CX, LENS_CY = 430, 415    # centre of the magnifying glass lens
LENS_R = 265                   # lens (white disc) radius

HANDLE_START = (617, 602)      # on the lens edge, 45 degrees down-right
HANDLE_END = (862, 847)
HANDLE_W = 122                 # thick enough to survive a 16px render

# Downward "price drop" arrow, drawn inside the lens.
ARROW_SHAFT_HALF_W = 50
ARROW_TOP = 250
ARROW_SHOULDER = 432           # where the shaft stops and the head begins
ARROW_HEAD_HALF_W = 152
ARROW_TIP = 600

# The macOS iconset requires exactly these files.
ICONSET_SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]

ICO_SIZES = [16, 32, 48, 64, 128, 256]

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "assets"


def s(value: float) -> int:
    """Scale a design-space coordinate up to the supersampled canvas."""
    return int(round(value * SS))


def vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    """A vertical top->bottom linear gradient, rendered at full canvas size."""
    # Build a 1px-wide strip then stretch it - far faster than per-pixel work.
    strip = Image.new("RGB", (1, size))
    px = strip.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        px[0, y] = (
            int(round(top[0] + (bottom[0] - top[0]) * t)),
            int(round(top[1] + (bottom[1] - top[1]) * t)),
            int(round(top[2] + (bottom[2] - top[2]) * t)),
        )
    return strip.resize((size, size), Image.NEAREST)


def draw_master() -> Image.Image:
    """Draw the icon at CANVAS size and downsample to MASTER with LANCZOS."""
    # --- 1. badge: gradient clipped to a rounded square ------------------
    gradient = vertical_gradient(CANVAS, GRAD_TOP, GRAD_BOTTOM).convert("RGBA")

    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, CANVAS - 1, CANVAS - 1],
        radius=s(BADGE_RADIUS),
        fill=255,
    )

    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    img.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(img)

    # --- 2. magnifying glass handle (drawn first, disc overlaps it) -------
    draw.line(
        [(s(HANDLE_START[0]), s(HANDLE_START[1])), (s(HANDLE_END[0]), s(HANDLE_END[1]))],
        fill=WHITE,
        width=s(HANDLE_W),
        joint="curve",
    )
    # Rounded cap on the free end of the handle.
    cap_r = s(HANDLE_W) // 2
    draw.ellipse(
        [
            s(HANDLE_END[0]) - cap_r,
            s(HANDLE_END[1]) - cap_r,
            s(HANDLE_END[0]) + cap_r,
            s(HANDLE_END[1]) + cap_r,
        ],
        fill=WHITE,
    )

    # --- 3. lens: a solid white disc for maximum contrast -----------------
    draw.ellipse(
        [
            s(LENS_CX - LENS_R),
            s(LENS_CY - LENS_R),
            s(LENS_CX + LENS_R),
            s(LENS_CY + LENS_R),
        ],
        fill=WHITE,
    )

    # --- 4. downward price arrow inside the lens --------------------------
    draw.rectangle(
        [
            s(LENS_CX - ARROW_SHAFT_HALF_W),
            s(ARROW_TOP),
            s(LENS_CX + ARROW_SHAFT_HALF_W),
            s(ARROW_SHOULDER),
        ],
        fill=DEEP_BLUE,
    )
    draw.polygon(
        [
            (s(LENS_CX - ARROW_HEAD_HALF_W), s(ARROW_SHOULDER)),
            (s(LENS_CX + ARROW_HEAD_HALF_W), s(ARROW_SHOULDER)),
            (s(LENS_CX), s(ARROW_TIP)),
        ],
        fill=DEEP_BLUE,
    )

    return img.resize((MASTER, MASTER), Image.LANCZOS)


def flatten_on_gradient(img: Image.Image) -> Image.Image:
    """
    Windows .ico handles alpha poorly in some legacy surfaces, but we keep the
    transparency around the rounded corners - just make sure the image really
    is RGBA so Pillow writes a 32-bit icon.
    """
    return img if img.mode == "RGBA" else img.convert("RGBA")


def write_png(master: Image.Image) -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / "icon.png"
    master.save(out, format="PNG")
    return out


def write_ico(master: Image.Image) -> Path:
    out = ASSETS / "icon.ico"
    flatten_on_gradient(master).save(
        out,
        format="ICO",
        sizes=[(n, n) for n in ICO_SIZES],
    )
    return out


def write_iconset(master: Image.Image) -> Path:
    iconset = ASSETS / "icon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    for name, size in ICONSET_SIZES:
        master.resize((size, size), Image.LANCZOS).save(iconset / name, format="PNG")
    return iconset


def try_iconutil(iconset: Path) -> Path | None:
    """
    Convert the iconset to .icns. `iconutil` ships with macOS only, so this is
    a best-effort step - on Linux/Windows the mac build script does it instead.
    """
    if not shutil.which("iconutil"):
        return None
    icns = ASSETS / "icon.icns"
    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover
        print(f"  !  iconutil failed: {exc.stderr.decode(errors='replace').strip()}")
        return None
    return icns


def sanity_check(master: Image.Image) -> None:
    """Fail loudly if the artwork came out blank or a single flat colour."""
    colours = master.convert("RGB").getcolors(maxcolors=1 << 24) or []
    distinct = len(colours)
    if distinct < 50:
        raise SystemExit(
            f"Icon looks wrong - only {distinct} distinct colours. Aborting."
        )
    # The lens should be white-ish and the badge blue-ish.
    centre = master.convert("RGB").getpixel((LENS_CX, LENS_CY - 260))
    corner = master.convert("RGB").getpixel((MASTER // 2, 40))
    print(f"  -  distinct colours: {distinct}")
    print(f"  -  lens sample RGB {centre}, badge sample RGB {corner}")


def main() -> int:
    print("==> Drawing icon master at {0}x{0} (supersampled {1}x)".format(MASTER, SS))
    master = draw_master()
    sanity_check(master)

    png = write_png(master)
    print(f"==> wrote {png.relative_to(REPO_ROOT)} ({png.stat().st_size:,} bytes)")

    ico = write_ico(master)
    print(f"==> wrote {ico.relative_to(REPO_ROOT)} ({ico.stat().st_size:,} bytes)")

    iconset = write_iconset(master)
    total = sum(p.stat().st_size for p in iconset.glob("*.png"))
    print(
        f"==> wrote {iconset.relative_to(REPO_ROOT)}/ "
        f"({len(ICONSET_SIZES)} files, {total:,} bytes)"
    )

    icns = try_iconutil(iconset)
    if icns:
        print(f"==> wrote {icns.relative_to(REPO_ROOT)} ({icns.stat().st_size:,} bytes)")
    else:
        print("==> skipped icon.icns - `iconutil` not found (macOS only).")
        print("    The mac build script converts assets/icon.iconset for you.")

    print("==> icons done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
