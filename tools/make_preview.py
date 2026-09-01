#!/usr/bin/env python3
"""
Export a standalone copy of the dashboard.

Produces one HTML file with the current findings baked into it - no server, no
Python, nothing to install. Useful for glancing at results on another device, or
sending someone a snapshot. It is read-only: the buttons that change things are
inert, because there's nothing behind them.

    python3 tools/make_preview.py [output.html]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dealhunter import core                      # noqa: E402
from dealhunter.server import STATE              # noqa: E402
from dealhunter.ui import PAGE                   # noqa: E402


BANNER = """
  <div class="banner"><strong>Saved snapshot.</strong> This is a read-only copy of the
  dashboard, exported at {when}. Listing links work; buttons that change settings do not.
  Open the app itself to scan again.</div>
"""


def build(out_path: Path) -> Path:
    conn = core.open_db()
    try:
        cfg = core.load_config()
        data = core.collect_dashboard_data(conn, cfg)
    finally:
        conn.close()

    data["status"] = {"scanning": False, "progress": {}, "last_run": data["generated"],
                      "last_result": None, "last_error": "", "auto": False,
                      "next_auto_in": None, "log": ["Saved snapshot - no live engine."]}
    data["watch_config"] = cfg.get("watches", [])
    data["settings"] = {
        "poll_interval_minutes": cfg.get("poll_interval_minutes", 20),
        "quality_mode": cfg.get("quality_mode", "balanced"),
        "min_seller_feedback_pct": cfg.get("min_seller_feedback_pct", 90),
        "min_seller_feedback_score": cfg.get("min_seller_feedback_score", 5),
        "has_keys": True,          # suppresses the "add your keys" prompt
        "sites": cfg.get("sites", {"ebay": True, "cex": False}),
        "data_dir": "", "version": "snapshot",
    }

    html = PAGE.replace("__TOKEN__", "static")
    html = html.replace(
        "<script>\nconst TOKEN",
        "<script>\nconst STATIC_DATA = " + json.dumps(data, ensure_ascii=False)
        + ";\nconst TOKEN",
        1,
    )
    html = html.replace(
        '<div id="banner"></div>',
        '<div id="banner">' + BANNER.format(when=data["generated"][:16].replace("T", " "))
        + '</div>',
        1,
    )
    # Nothing should poll a server that isn't there.
    html = html.replace("setInterval(poll, 2000);", "/* snapshot - no polling */")

    out_path.write_text(html, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dashboard-snapshot.html")
    built = build(target.resolve())
    print(f"Wrote {built} ({built.stat().st_size // 1024} KB)")
