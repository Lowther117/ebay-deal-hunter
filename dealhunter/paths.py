"""
Where the app keeps its files.

A packaged .app or .exe sits in a read-only bundle, so nothing is ever written
next to the program. Everything lives in the normal per-user data folder for
the platform, which also means the data survives reinstalling the app.

    macOS    ~/Library/Application Support/eBay Deal Hunter
    Windows  %APPDATA%\\eBay Deal Hunter
    Linux    ~/.local/share/ebay-deal-hunter
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "eBay Deal Hunter"


def data_dir() -> Path:
    override = os.environ.get("DEAL_HUNTER_HOME", "").strip()
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        path = Path(base) / "ebay-deal-hunter"
    path.mkdir(parents=True, exist_ok=True)
    return path


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
