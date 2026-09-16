#!/usr/bin/env python3
"""
Export a standalone copy of the dashboard.

Produces one HTML file with the current findings baked into it - no server, no
Python, nothing to install. Useful for glancing at results on another device, or
sending someone a snapshot. It is read-only: the buttons that change things are
inert, because there's nothing behind them.

    python3 tools/make_preview.py [output.html]

Without an argument it lands in the folder chosen under Settings > Save to, or
your Downloads folder. The app's own "Save snapshot" button does the same.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dealhunter import core                      # noqa: E402
from dealhunter.server import build_snapshot     # noqa: E402


def build(out_path: Path) -> Path:
    return build_snapshot(out_path)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        target = core.default_save_dir(core.load_config()) / "dashboard-snapshot.html"
    built = build(target.resolve())
    print(f"Wrote {built} ({built.stat().st_size // 1024} KB)")
