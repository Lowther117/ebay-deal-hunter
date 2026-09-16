"""
The local app server.

Serves the UI and a small JSON API on 127.0.0.1 only. Nothing is exposed to the
network - the port is bound to loopback and every request must carry the session
token that the app generated at startup, so nothing else on the machine can
drive it either.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import APP_TITLE, __version__
from . import core
from .paths import DATA_DIR, CONFIG_PATH
from .ui import PAGE

SESSION_TOKEN = secrets.token_urlsafe(24)


class AppState:
    """Everything the UI needs to know, guarded by one lock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.scanning = False
        self.progress = {"done": 0, "total": 0, "watch": ""}
        self.last_run = None
        self.last_result = None
        self.last_error = ""
        self.log = deque(maxlen=400)
        self.auto = False
        self.next_auto = None
        self._stop = threading.Event()
        # Set when the app is running in a browser tab rather than its own
        # window. There is then no window to close, so the page shows a Quit
        # button that ends the process - a packaged build has no console to
        # Ctrl-C in, and would otherwise run invisibly until the next reboot.
        self.browser_mode = False
        self.quit_requested = threading.Event()
        core.LOG_SINK = self.add_log

    # -- log -------------------------------------------------------------- #
    def add_log(self, line: str) -> None:
        with self.lock:
            self.log.append(line)

    def recent_log(self, n=120):
        with self.lock:
            return list(self.log)[-n:]

    # -- scanning --------------------------------------------------------- #
    def start_scan(self, *, names=None, group=None, demo=False) -> bool:
        with self.lock:
            if self.scanning:
                return False
            self.scanning = True
            self.progress = {"done": 0, "total": 0, "watch": ""}
            self.last_error = ""

        def progress(done, total, watch):
            with self.lock:
                self.progress = {"done": done, "total": total, "watch": watch}

        def worker():
            conn = core.open_db()
            try:
                cfg = core.load_config()
                result = core.scan_all(cfg, conn, names=names, group=group,
                                       demo=demo, progress=progress)
            except Exception as exc:  # never let the app die on a bad scan
                core.log(f"Scan failed: {exc!r}")
                result = {"ok": False, "error": str(exc), "scanned": 0, "new_hits": 0}
            finally:
                conn.close()
            with self.lock:
                self.scanning = False
                self.last_run = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self.last_result = result
                self.last_error = "" if result.get("ok") else result.get("error", "")
                self.progress = {"done": 0, "total": 0, "watch": ""}

        threading.Thread(target=worker, daemon=True, name="scanner").start()
        return True

    # -- automatic scanning ----------------------------------------------- #
    def set_auto(self, on: bool) -> None:
        with self.lock:
            self.auto = bool(on)
            self.next_auto = time.time() + self._interval() if on else None

    def _interval(self) -> int:
        try:
            return max(300, int(core.load_config().get("poll_interval_minutes", 20)) * 60)
        except Exception:
            return 1200

    def auto_loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(15)
            with self.lock:
                due = self.auto and self.next_auto and time.time() >= self.next_auto
                busy = self.scanning
            if due and not busy:
                core.log("Automatic scan starting.")
                self.start_scan()
                with self.lock:
                    self.next_auto = time.time() + self._interval()

    def shutdown(self) -> None:
        self._stop.set()
        self.quit_requested.set()

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "scanning": self.scanning,
                "progress": dict(self.progress),
                "last_run": self.last_run,
                "last_result": self.last_result,
                "last_error": self.last_error,
                "auto": self.auto,
                "next_auto_in": max(0, int(self.next_auto - time.time()))
                                if (self.auto and self.next_auto) else None,
                "log": self.recent_log(),
            }


STATE = AppState()


# --------------------------------------------------------------------------- #
# request handling
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    server_version = f"DealHunter/{__version__}"

    def log_message(self, fmt, *args):  # keep the console clean
        pass

    # -- helpers ---------------------------------------------------------- #
    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _authorised(self, query) -> bool:
        token = (query.get("t") or [""])[0]
        if not token:
            token = self.headers.get("X-Session-Token", "")
        try:
            return secrets.compare_digest(token.encode("utf-8"), SESSION_TOKEN.encode("utf-8"))
        except (AttributeError, TypeError):
            return False

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return {}
        if not length or length > 2_000_000:
            return {}
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return body if isinstance(body, dict) else {}

    # -- routes ----------------------------------------------------------- #
    def do_GET(self):
        self._guarded(self._get)

    def do_POST(self):
        self._guarded(self._post)

    def _guarded(self, route):
        """One safety net for every route. Without it a bug in a handler (or a
        broken config.json) closed the connection with no reply, and the page
        sat on "Starting..." for ever with nothing to say why."""
        try:
            route()
        except Exception as exc:  # noqa: BLE001
            core.log(f"Request {self.command} {urlparse(self.path).path} failed: {exc}")
            try:
                self._send(500, {"error": str(exc) or exc.__class__.__name__})
            except Exception:
                pass

    def _get(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)

        # The page itself needs the token too: the app opens it with ?t=...,
        # so nothing else on the machine can fetch a page with the token in it.
        if not self._authorised(query):
            if url.path in ("/", "/index.html"):
                return self._send(403, "This page belongs to the running app - "
                                  "open it from the app, or from the link in hunter.log.",
                                  "text/plain; charset=utf-8")
            return self._send(403, {"error": "bad session token"})

        if url.path in ("/", "/index.html"):
            return self._send(200, PAGE.replace("__TOKEN__", SESSION_TOKEN),
                              "text/html; charset=utf-8")

        if url.path == "/api/data":
            conn = core.open_db()
            try:
                cfg = core.load_config()
                data = core.collect_dashboard_data(conn, cfg)
            finally:
                conn.close()
            data["status"] = STATE.snapshot()
            data["watch_config"] = cfg.get("watches", [])
            data["settings"] = {
                "poll_interval_minutes": cfg.get("poll_interval_minutes", 20),
                "quality_mode": cfg.get("quality_mode", "balanced"),
                "min_seller_feedback_pct": cfg.get("min_seller_feedback_pct", 90),
                "min_seller_feedback_score": cfg.get("min_seller_feedback_score", 5),
                "baseline_max_age_hours": cfg.get("baseline_max_age_hours", 12),
                "has_keys": all(core.credentials()),
                "sites": cfg.get("sites") or {"ebay": True},
                "feed_sources": __import__("dealhunter.sources", fromlist=["x"]).FEED_SOURCE_LABELS,
                "data_dir": str(DATA_DIR),
                "config_path": str(CONFIG_PATH),
                "version": __version__,
                "browser_mode": STATE.browser_mode,
                "dark": bool(cfg.get("dark", True)),
                "save_dir": str(cfg.get("save_dir") or ""),
                "save_dir_default": str(core.downloads_dir()),
            }
            return self._send(200, data)

        if url.path == "/api/status":
            return self._send(200, STATE.snapshot())

        if url.path == "/api/links":
            from .sites import quick_links_for
            name = (query.get("watch") or [""])[0]
            cfg = core.load_config()
            watch = next((w for w in cfg.get("watches", []) if w["name"] == name), None)
            if watch is None:
                return self._send(404, {"error": "no such watch"})
            return self._send(200, {"links": quick_links_for(watch)})

        return self._send(404, {"error": "not found"})

    def _post(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self._authorised(query):
            return self._send(403, {"error": "bad session token"})

        body = self._body()

        if url.path == "/api/quit":
            core.log("Quit requested from the page.")
            STATE.quit_requested.set()
            return self._send(200, {"ok": True})

        if url.path == "/api/scan":
            started = STATE.start_scan(
                names=body.get("watch"), group=body.get("group"),
                demo=bool(body.get("demo")),
            )
            return self._send(200, {"started": started, "busy": not started})

        if url.path == "/api/auto":
            STATE.set_auto(bool(body.get("on")))
            return self._send(200, STATE.snapshot())

        if url.path == "/api/credentials":
            client_id = (body.get("client_id") or "").strip()
            client_secret = (body.get("client_secret") or "").strip()
            if not client_id or not client_secret:
                return self._send(400, {"error": "Both keys are required."})
            core.save_credentials(client_id, client_secret)
            core.log("eBay API keys saved.")
            return self._send(200, {"ok": True})

        if url.path == "/api/watch":
            return self._send(200, update_watch(body))

        if url.path == "/api/settings":
            return self._send(200, update_settings(body))

        if url.path == "/api/open":
            # Links must leave the app window and land in the real browser -
            # inside a native webview a plain target="_blank" goes nowhere.
            target = (body.get("url") or "").strip()
            parsed = urlparse(target)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return self._send(400, {"error": "only http(s) links can be opened"})
            import webbrowser
            opened = webbrowser.open(target, new=2)
            return self._send(200, {"ok": True, "opened": opened})

        if url.path == "/api/test-site":
            which = (body.get("site") or "").strip()
            from . import sources as extra
            if which in extra.SOURCES:
                try:
                    ok, detail = extra.test_source(which, core.load_config())
                    core.log(f"{extra.SOURCES[which][0]} test: {detail}")
                    return self._send(200, {"ok": ok, "detail": detail})
                except Exception as exc:
                    core.log(f"{extra.SOURCES[which][0]} test failed: {exc}")
                    return self._send(200, {"ok": False, "detail": str(exc)[:220]})
            if which == "cex":
                try:
                    cfg = core.load_config()
                    found = core.CexClient(cfg).search("macbook", max_price=5000, limit=3,
                                                       grades=cfg.get("cex_grades") or None)
                    detail = (f"Connected - {len(found)} test results, e.g. "
                              f"{core.normalise_cex(found[0], cfg)['title'][:50]}"
                              if found else "Connected, but the test search found nothing.")
                    core.log(f"CeX test: {detail}")
                    return self._send(200, {"ok": bool(found), "detail": detail})
                except Exception as exc:
                    core.log(f"CeX test failed: {exc}")
                    return self._send(200, {"ok": False, "detail": str(exc)[:220]})
            if which in ("ebay", "ebay_refurbished", "ebay_auctions"):
                cid, secret = core.credentials()
                if not cid or not secret:
                    return self._send(200, {"ok": False,
                                            "detail": "No API keys saved yet."})
                try:
                    client = core.EbayClient(cid, secret, core.load_config()["marketplace"])
                    opt = "AUCTION" if which == "ebay_auctions" else "FIXED_PRICE"
                    filters = [f"buyingOptions:{{{opt}}}", "price:[1..5000]",
                               "priceCurrency:GBP", "itemLocationCountry:GB"]
                    if which == "ebay_refurbished":
                        filters.append("conditions:{"
                                       + "|".join(sorted(core.REFURB_CONDITIONS)) + "}")
                    found = client.search("macbook", filters, limit=3)
                    detail = f"Connected - keys work, {len(found)} test results."
                    core.log(f"eBay test: {detail}")
                    return self._send(200, {"ok": True, "detail": detail})
                except Exception as exc:
                    core.log(f"eBay test failed: {exc}")
                    return self._send(200, {"ok": False, "detail": str(exc)[:220]})
            return self._send(400, {"ok": False, "detail": "unknown site"})

        if url.path == "/api/sites":
            with CONFIG_LOCK:
                cfg = core.load_config()
                sites = dict(cfg.get("sites") or {"ebay": True})
                for key in SITE_KEYS:
                    if key in body:
                        sites[key] = bool(body[key])
                if not any(sites.get(k) for k in SITE_KEYS):
                    return self._send(200, {"ok": False,
                                            "error": "Keep at least one source switched on."})
                cfg["sites"] = sites
                write_config(cfg)
            core.log(f"Sites: {', '.join(k for k, v in sites.items() if v) or 'none'}")
            return self._send(200, {"ok": True, "sites": sites})

        if url.path == "/api/export":
            # A read-only copy of the dashboard, saved where the user asked
            # (Settings > Save to) or in Downloads. Never beside the app.
            cfg = core.load_config()
            stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
            target = core.default_save_dir(cfg) / f"dashboard-snapshot-{stamp}.html"
            build_snapshot(target)
            core.log(f"Snapshot saved to {target}")
            return self._send(200, {"ok": True, "path": str(target)})

        if url.path == "/api/browse-dir":
            # The native folder picker, when the app has a window of its own.
            # In a browser tab there is none, so the page falls back to the
            # typed path.
            try:
                import webview
                window = webview.windows[0] if webview.windows else None
                if window is None:
                    raise RuntimeError("no native window")
                kind = getattr(webview, "FOLDER_DIALOG", None)
                if kind is None:
                    kind = webview.FileDialog.FOLDER
                start = str(core.default_save_dir(core.load_config()))
                picked = window.create_file_dialog(kind, directory=start)
            except Exception as exc:  # noqa: BLE001 - no backend, no window, cancelled
                return self._send(200, {"ok": False, "error": str(exc) or "no folder dialog here"})
            if not picked:
                return self._send(200, {"ok": False, "error": "cancelled"})
            path = picked[0] if isinstance(picked, (list, tuple)) else picked
            return self._send(200, {"ok": True, "path": str(path)})

        if url.path == "/api/clear":
            conn = core.open_db()
            try:
                conn.execute("DELETE FROM items")
                conn.commit()
            finally:
                conn.close()
            core.log("Cleared saved listings.")
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})


# --------------------------------------------------------------------------- #
# config mutation
# --------------------------------------------------------------------------- #

CONFIG_LOCK = threading.Lock()

SITE_KEYS = ("ebay", "ebay_refurbished", "ebay_auctions", "cex",
             "backmarket", "musicmagpie", "cashconverters", "hukd", "reddit_hws")

NUMERIC_WATCH_FIELDS = {
    "max_price": (1, 100000),
    "min_price": (0, 100000),
    "min_discount_pct": (0, 95),
    "result_limit": (10, 200),
    "min_ram_gb": (0, 4096),
    "min_storage_gb": (0, 1_000_000),
}

# Comma-separated in the UI, lists in config.json.
LIST_WATCH_FIELDS = ("brands", "cpus", "require_terms", "exclude_terms")


def _terms(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    return [str(v).strip() for v in (value or []) if str(v).strip()]


def write_config(cfg) -> None:
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def update_watch(body: dict) -> dict:
    name = (body.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "No watch named."}

    with CONFIG_LOCK:
        cfg = core.load_config()
        watches = cfg.get("watches", [])
        target = next((w for w in watches if w["name"] == name), None)
        if target is None:
            return {"ok": False, "error": f"No watch called '{name}'."}

        if "enabled" in body:
            target["enabled"] = bool(body["enabled"])
        if "quality_mode" in body and body["quality_mode"] in ("strict", "balanced", "loose"):
            target["quality_mode"] = body["quality_mode"]

        for field, (lo, hi) in NUMERIC_WATCH_FIELDS.items():
            if field in body:
                try:
                    value = int(float(body[field]))
                except (TypeError, ValueError):
                    return {"ok": False, "error": f"'{field}' must be a number."}
                target[field] = max(lo, min(hi, value))

        for field in LIST_WATCH_FIELDS:
            if field in body:
                target[field] = _terms(body[field])
        for field in ("query", "baseline_query"):
            if field in body:
                value = " ".join(str(body[field]).split())[:300]
                if field == "query" and not value:
                    return {"ok": False, "error": "The search query can't be empty."}
                target[field] = value
        if "specs_required" in body:
            target["specs_required"] = bool(body["specs_required"])

        if target.get("min_price", 0) >= target.get("max_price", 1):
            return {"ok": False, "error": "Minimum price must be below the maximum."}

        write_config(cfg)
    return {"ok": True, "watch": target}


# field -> (low, high, type). Whole-number fields stay whole numbers, so
# config.json doesn't fill up with "20.0".
ALLOWED_SETTINGS = {
    "poll_interval_minutes": (5, 1440, int),
    "min_seller_feedback_pct": (0, 100, float),
    "min_seller_feedback_score": (0, 100000, int),
    "baseline_max_age_hours": (1, 168, int),
}


def update_settings(body: dict) -> dict:
    with CONFIG_LOCK:
        cfg = core.load_config()
        for field, (lo, hi, kind) in ALLOWED_SETTINGS.items():
            if field in body:
                try:
                    value = kind(float(body[field]))
                except (TypeError, ValueError):
                    return {"ok": False, "error": f"'{field}' must be a number."}
                cfg[field] = max(lo, min(hi, value))
        if body.get("quality_mode") in ("strict", "balanced", "loose"):
            cfg["quality_mode"] = body["quality_mode"]
        if "dark" in body:
            cfg["dark"] = bool(body["dark"])   # the Light/Dark toggle
        if "save_dir" in body:
            chosen = str(body["save_dir"] or "").strip()
            if chosen and not Path(chosen).expanduser().is_dir():
                return {"ok": False, "error": f"'{chosen}' is not a folder that exists."}
            cfg["save_dir"] = chosen           # empty means Downloads
        write_config(cfg)
    core.log("Settings saved.")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# snapshot export
# --------------------------------------------------------------------------- #

SNAPSHOT_BANNER = """
  <div class="banner"><strong>Saved snapshot.</strong> This is a read-only copy of the
  dashboard, exported at {when}. Listing links work; buttons that change settings do not.
  Open the app itself to scan again.</div>
"""


def build_snapshot(out_path: Path) -> Path:
    """One standalone HTML file with the current findings baked in - no server,
    no Python. Read-only: the buttons that change things are inert."""
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
        "sites": cfg.get("sites", {"ebay": True}),
        "dark": bool(cfg.get("dark", True)),
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
        '<div id="banner">' + SNAPSHOT_BANNER.format(
            when=data["generated"][:16].replace("T", " ")) + '</div>',
        1,
    )
    # Nothing should poll a server that isn't there.
    html = html.replace("setInterval(poll, 2000);", "/* snapshot - no polling */")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------- #
# lifecycle
# --------------------------------------------------------------------------- #

def start(port_hint: int = 8756) -> tuple[ThreadingHTTPServer, str]:
    """Bind to loopback, preferring the usual port but taking any free one."""
    last_error = None
    for port in [port_hint, 0]:
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError as exc:
            last_error = exc
    else:
        raise RuntimeError(f"Could not open a local port: {last_error}")

    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True, name="http").start()
    threading.Thread(target=STATE.auto_loop, daemon=True, name="auto").start()

    url = f"http://127.0.0.1:{httpd.server_address[1]}/?t={SESSION_TOKEN}"
    core.log(f"{APP_TITLE} {__version__} ready.")
    return httpd, url
