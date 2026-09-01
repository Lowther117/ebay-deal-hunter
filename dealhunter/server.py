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
        return secrets.compare_digest(token, SESSION_TOKEN)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return {}
        if not length or length > 2_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # -- routes ----------------------------------------------------------- #
    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)

        if url.path in ("/", "/index.html"):
            return self._send(200, PAGE.replace("__TOKEN__", SESSION_TOKEN),
                              "text/html; charset=utf-8")

        if not self._authorised(query):
            return self._send(403, {"error": "bad session token"})

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
                "has_keys": bool(core.credentials()[0] and core.credentials()[1]),
                "sites": cfg.get("sites") or {"ebay": True},
                "data_dir": str(DATA_DIR),
                "config_path": str(CONFIG_PATH),
                "version": __version__,
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

    def do_POST(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if not self._authorised(query):
            return self._send(403, {"error": "bad session token"})

        body = self._body()

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
                for key in ("ebay", "ebay_refurbished", "ebay_auctions"):
                    if key in body:
                        sites[key] = bool(body[key])
                if not any(sites.get(k) for k in
                           ("ebay", "ebay_refurbished", "ebay_auctions")):
                    return self._send(200, {"ok": False,
                                            "error": "Keep at least one source switched on."})
                cfg["sites"] = sites
                write_config(cfg)
            core.log(f"Sites: {', '.join(k for k, v in sites.items() if v) or 'none'}")
            return self._send(200, {"ok": True, "sites": sites})

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

NUMERIC_WATCH_FIELDS = {
    "max_price": (1, 100000),
    "min_price": (0, 100000),
    "min_discount_pct": (0, 95),
    "result_limit": (10, 200),
}


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

        if target.get("min_price", 0) >= target.get("max_price", 1):
            return {"ok": False, "error": "Minimum price must be below the maximum."}

        write_config(cfg)
    return {"ok": True, "watch": target}


ALLOWED_SETTINGS = {
    "poll_interval_minutes": (5, 1440),
    "min_seller_feedback_pct": (0, 100),
    "min_seller_feedback_score": (0, 100000),
    "baseline_max_age_hours": (1, 168),
}


def update_settings(body: dict) -> dict:
    with CONFIG_LOCK:
        cfg = core.load_config()
        for field, (lo, hi) in ALLOWED_SETTINGS.items():
            if field in body:
                try:
                    value = float(body[field])
                except (TypeError, ValueError):
                    return {"ok": False, "error": f"'{field}' must be a number."}
                cfg[field] = max(lo, min(hi, value))
        if body.get("quality_mode") in ("strict", "balanced", "loose"):
            cfg["quality_mode"] = body["quality_mode"]
        write_config(cfg)
    core.log("Settings saved.")
    return {"ok": True}


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
