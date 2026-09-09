"""
Where the app keeps its files.

A packaged .app or .exe sits in a read-only bundle, so nothing is ever written
next to the program. Everything lives in the normal per-user data folder for
the platform, which also means the data survives reinstalling the app. On
macOS this matters twice over: writing inside a signed .app invalidates its
signature and the next launch is killed by Gatekeeper.

    macOS    ~/Library/Application Support/eBay Deal Hunter
    Windows  %APPDATA%\\eBay Deal Hunter
    Linux    ~/.local/share/ebay-deal-hunter

DEAL_HUNTER_HOME overrides all of that. A relative value is taken as relative
to the program, not to the working directory - a Finder-launched app starts in
"/", where nothing is writable.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "eBay Deal Hunter"


def program_dir() -> Path:
    """The folder the program sits in - never written to, only used to make a
    relative DEAL_HUNTER_HOME mean something sensible."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent
    exe_dir = Path(sys.executable).resolve().parent
    parts = exe_dir.parts
    if (sys.platform == "darwin" and len(parts) >= 3
            and parts[-1] == "MacOS" and parts[-2] == "Contents"
            and parts[-3].endswith(".app")):
        return exe_dir.parent.parent.parent
    return exe_dir


def data_dir() -> Path:
    """The per-user data folder, created on the way past.

    This runs at import time, so it must not raise: an unwritable home folder
    would otherwise kill a windowed build before it can report anything. A
    temp folder is a poor home for the database but a much better outcome than
    an app that closes instantly.
    """
    override = os.environ.get("DEAL_HUNTER_HOME", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            path = program_dir() / path
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        path = Path(base) / "ebay-deal-hunter"

    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "ebay-deal-hunter"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError:
            return Path(tempfile.gettempdir())
        return fallback


def bundle_dir() -> Path:
    """Where read-only resources live - differs once PyInstaller has packaged us."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


DATA_DIR = data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "deals.sqlite3"
CREDS_PATH = DATA_DIR / "credentials.json"
TOKEN_CACHE = DATA_DIR / ".token_cache.json"
LOG_PATH = DATA_DIR / "hunter.log"
