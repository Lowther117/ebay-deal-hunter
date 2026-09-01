#!/usr/bin/env python3
"""
eBay Deal Hunter - desktop app entry point.

Starts the local engine and opens it in a native window. If pywebview isn't
installed (or has no backend on this machine) it falls back to the default
browser, so the app always starts rather than dying with an import error.

    python3 app.py              open the app
    python3 app.py --browser    skip the native window, use the browser
    python3 app.py --scan       run one scan in the terminal and exit
    python3 app.py --list       list every watch and exit
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser

from dealhunter import APP_TITLE, __version__
from dealhunter import core, server
from dealhunter.paths import DATA_DIR, LOG_PATH


def run_headless_scan(args) -> int:
    """Terminal mode - handy for a scheduled scan without opening the window."""
    cfg = core.load_config()
    conn = core.open_db()
    try:
        result = core.scan_all(
            cfg, conn,
            names=args.watch.split(",") if args.watch else None,
            group=args.group.split(",") if args.group else None,
            demo=args.demo,
        )
    finally:
        conn.close()
    if not result.get("ok"):
        core.log("Scan failed: " + result.get("error", "unknown error"))
        return 1
    core.log(f"Done - {result['new_hits']} new, {result['scanned']} matching listings.")
    return 0


def list_watches() -> int:
    cfg = core.load_config()
    watches = cfg.get("watches", [])
    groups: dict[str, list] = {}
    for w in watches:
        groups.setdefault(w.get("group", "Other"), []).append(w)
    on = sum(1 for w in watches if w.get("enabled", True))
    print(f"\n{len(watches)} watches in {len(groups)} groups ({on} switched on)\n")
    for group in sorted(groups):
        print(f"  {group}")
        for w in groups[group]:
            mark = "on " if w.get("enabled", True) else "off"
            print(f"    [{mark}] {w['name']:<28} up to GBP {str(w.get('max_price', '-')):<6}"
                  f" {w.get('min_discount_pct', 0)}%+ under market")
        print()
    return 0


def open_window(url: str) -> bool:
    """Native window via pywebview. Returns False if it isn't usable here."""
    try:
        import webview
    except ImportError:
        return False
    try:
        webview.create_window(
            APP_TITLE, url,
            width=1340, height=900, min_size=(900, 620),
            confirm_close=False,
        )
        webview.start()  # blocks until the window is closed
        return True
    except Exception as exc:  # no GUI backend, headless machine, etc.
        core.log(f"Native window unavailable ({exc}) - falling back to the browser.")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{APP_TITLE} {__version__}")
    parser.add_argument("--browser", action="store_true", help="use the default browser instead of a window")
    parser.add_argument("--scan", action="store_true", help="run one scan in the terminal and exit")
    parser.add_argument("--list", action="store_true", help="list every watch and exit")
    parser.add_argument("--watch", help="with --scan: only these watches, comma separated")
    parser.add_argument("--group", help="with --scan: only this category")
    parser.add_argument("--demo", action="store_true", help="use demo data instead of calling eBay")
    parser.add_argument("--port", type=int, default=8756, help="preferred local port")
    args = parser.parse_args()

    # Mirror the log to a file so problems are diagnosable after the fact.
    try:
        log_file = open(LOG_PATH, "a", encoding="utf-8")
        original_sink = core.LOG_SINK

        def sink(line):
            log_file.write(line + "\n")
            log_file.flush()
            if original_sink:
                original_sink(line)

        core.LOG_SINK = sink
    except OSError:
        pass

    if args.list:
        return list_watches()
    if args.scan:
        return run_headless_scan(args)

    core.load_config()  # writes the starter config on a fresh install
    httpd, url = server.start(args.port)
    core.log(f"Data folder: {DATA_DIR}")

    if args.browser or not open_window(url):
        webbrowser.open(url)
        core.log(f"Open in your browser: {url}")
        core.log("Close this window (or press Ctrl-C) to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    server.STATE.shutdown()
    httpd.shutdown()
    core.log("Closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
