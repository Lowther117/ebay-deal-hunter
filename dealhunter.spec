# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for eBay Deal Hunter.

The same file builds on macOS and on Windows - `sys.platform` picks the right
shape for each:

    macOS    one-folder build, then wrapped into "Deal Hunter.app"
    Windows  one-file build, producing a single "Deal Hunter.exe"

Build with:
    pyinstaller --noconfirm --clean dealhunter.spec

The UI is a Python string constant (dealhunter/ui.py), so the only data file
bundled is the icon.
"""

import os
import sys
from pathlib import Path

APP_NAME = "Deal Hunter"
APP_VERSION = "2.0.0"
BUNDLE_ID = "uk.lowther.dealhunter"

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")

# SPECPATH is injected by PyInstaller; fall back to cwd for plain linting.
ROOT = Path(globals().get("SPECPATH", os.path.abspath(".")))
ASSETS = ROOT / "assets"

# --------------------------------------------------------------------------
# Icon: .icns on macOS, .ico on Windows. Anything else (Linux) gets no icon.
# --------------------------------------------------------------------------
if IS_MAC:
    _icon = ASSETS / "icon.icns"
elif IS_WIN:
    _icon = ASSETS / "icon.ico"
else:
    _icon = None

ICON = str(_icon) if _icon and _icon.exists() else None

# The PNG is the only data file - handy for the window icon at runtime.
datas = []
if (ASSETS / "icon.png").exists():
    datas.append((str(ASSETS / "icon.png"), "assets"))

# --------------------------------------------------------------------------
# Hidden imports: pywebview loads its native backend lazily by name, so
# PyInstaller cannot see it. The dealhunter submodules are listed explicitly
# too, since app.py may import them indirectly.
# --------------------------------------------------------------------------
hiddenimports = [
    "dealhunter",
    "dealhunter.core",
    "dealhunter.paths",
    "dealhunter.server",
    "dealhunter.ui",
    "webview",
    "webview.platforms",
    "webview.util",
]

if IS_MAC:
    hiddenimports += [
        "webview.platforms.cocoa",
        "objc",
        "Foundation",
        "AppKit",
        "WebKit",
    ]
elif IS_WIN:
    hiddenimports += [
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "webview.platforms.mshtml",
        "webview.platforms.cef",
        "clr",
        "clr_loader",
        "pythonnet",
    ]
else:
    hiddenimports += [
        "webview.platforms.gtk",
        "webview.platforms.qt",
    ]

a = Analysis(
    ["app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Nothing here is used - keeping them out trims tens of MB.
        # Deliberately conservative: stdlib modules that other libraries
        # sometimes import indirectly (unittest, doctest...) are left in.
        "tkinter",
        "numpy",
        "PIL",  # only needed at build time, for the icons
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

if IS_WIN:
    # ---- Windows: a single self-contained .exe --------------------------
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,          # windowed - no console window
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=ICON,
    )

else:
    # ---- macOS / Linux: one-folder build --------------------------------
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,          # windowed - no terminal
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=ICON,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name=APP_NAME,
    )

    if IS_MAC:
        app = BUNDLE(
            coll,
            name=f"{APP_NAME}.app",
            icon=ICON,
            bundle_identifier=BUNDLE_ID,
            version=APP_VERSION,
            info_plist={
                "CFBundleName": APP_NAME,
                "CFBundleDisplayName": APP_NAME,
                "CFBundleShortVersionString": APP_VERSION,
                "CFBundleVersion": APP_VERSION,
                "NSHighResolutionCapable": True,
                "LSApplicationCategoryType": "public.app-category.utilities",
                "LSUIElement": False,
                "NSRequiresAquaSystemAppearance": False,
            },
        )
