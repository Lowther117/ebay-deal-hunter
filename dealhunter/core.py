"""
eBay Deal Hunter - scanning engine.

Pure standard library. Knows nothing about the GUI: it finds listings, judges
their condition, scores them against the UK market, and stores the results.

Sources: eBay UK (Buy It Now, Refurbished, auctions ending soon) through the
official Browse API, and CeX through the stock-search service its own website
uses. Everything after fetching - the UK check, condition gates, scoring and
storage - is shared, so a listing is judged the same way wherever it came from.
"""

from __future__ import annotations

import base64
import json
import os
import random
import re
import sqlite3
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .paths import CONFIG_PATH, DB_PATH, TOKEN_CACHE

EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"

USER_AGENT = f"ebay-deal-hunter/{__version__} (personal use)"

# CeX searches its stock through Algolia, reached via a proxy on CeX's own
# domain with a search-only key that every visitor's browser is handed (it can
# read the index and nothing else). These values were read from uk.webuy.com
# in September 2026 - its appsettings call returns them as algoliaAppId,
# algoliaSearchAppKey and algoliaIndexName. If CeX rotates the key, the Test
# button on the Settings tab says so; put the new values in config.json as
# cex_app_id / cex_api_key / cex_index and nothing else needs to change.
CEX_SEARCH_HOST = "https://search.webuy.io"
CEX_APP_ID = "LNNFEEWZVA"
CEX_API_KEY = "bf79f2b6699e60a18ae330a1248b452c"
CEX_INDEX = "prod_cex_uk"
CEX_PRODUCT_URL = "https://uk.webuy.com/product-detail?id="
# The search proxy sits behind Cloudflare, which is happier with a browser-shaped
# request than a bare Python one.
CEX_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

# Replaced by the app so log lines reach the UI as well as the console.
LOG_SINK = None


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except (OSError, ValueError, AttributeError):
        pass  # no console (windowed build) or the pipe went away
    if LOG_SINK is not None:
        try:
            LOG_SINK(line)
        except Exception:
            pass


def money(value) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #

DEFAULT_CONFIG = {
    "marketplace": "EBAY_GB",
    "currency": "GBP",
    "poll_interval_minutes": 40,
    "open_dashboard_on_new_hits": False,
    "min_seller_feedback_pct": 90.0,
    "min_seller_feedback_score": 5,
    "baseline_sample_size": 100,
    "baseline_max_age_hours": 12,
    "listing_expiry_days": 7,
    "quality_mode": "balanced",  # strict | balanced | loose
    "dark": True,                # the window's Light/Dark toggle - dark by default
    "global_exclude_terms": [
        # dead or dying
        "for parts", "spares", "spares or repair", "spares repairs", "repair",
        "repairs", "faulty", "broken", "cracked", "smashed", "damaged",
        "not working", "non working", "doesn't work", "does not work", "no power",
        "won't turn on", "wont turn on", "no display", "no boot", "dead",
        "water damage", "liquid damage", "untested", "as is", "as-is", "unknown fault",
        "spares/repair", "salvage", "incomplete", "missing keys", "missing parts",
        "read description", "read carefully", "please read",
        # locked / unusable
        "icloud locked", "icloud lock", "activation lock", "find my on",
        "mdm locked", "efi locked", "firmware locked", "passcode locked",
        "network locked", "blacklisted", "bad esn", "no imei",
        # not the actual item
        "screen only", "lcd only", "display only", "case only", "shell only",
        "cover only", "empty box", "box only", "logic board", "motherboard",
        "top case", "palmrest", "bezel", "hinge", "keyboard only", "charger only",
        "cable only", "battery only", "housing", "manual only", "poster",
        "sticker", "decal", "skin", "replica", "dummy", "model only", "prop",
        "faulty spares", "job lot",
    ],
    "working_terms": [
        "fully working", "full working order", "in working order", "works perfectly",
        "works great", "works well", "working order", "tested working", "fully tested",
        "tested and working", "boots", "boots up", "powers on", "fully functional",
        "functional", "excellent condition", "very good condition", "good condition",
        "great condition", "immaculate", "mint condition", "pristine", "like new",
        "refurbished", "refurb", "professionally refurbished", "serviced",
        "perfect working", "no faults", "no issues", "fault free", "ready to use",
    ],
    "trusted_conditions": [
        "new", "new (other)", "new with box", "new without box", "new with tags",
        "open box", "certified - refurbished", "certified refurbished",
        "excellent - refurbished", "very good - refurbished", "good - refurbished",
        "seller refurbished", "manufacturer refurbished", "refurbished",
    ],
    "banned_conditions": [
        "for parts or not working", "for parts", "parts only", "not working",
    ],
    "auction_ending_within_hours": 12,
    "refurbished_discount_allowance": 15,
    # CeX: which grades to accept (A best, C most worn - all three are tested
    # and carry the same warranty), what to add for delivery so totals are
    # honest, and which stores count as local (shown when they have it in).
    "cex_grades": ["A", "B", "C"],
    "cex_delivery_charge": 0.0,
    "cex_local_stores": ["Merthyr Tydfil", "Pontypridd"],
    # Towns whose shop stock counts as "local" (collection-only Cash Converters
    # stock is otherwise dropped). Shop searches are cached for shop_cache_hours
    # so automatic scans don't hammer three shops every 40 minutes.
    "local_towns": ["Merthyr Tydfil", "Pontypridd", "Aberdare", "Cardiff"],
    "shop_cache_hours": 6,
    "cashconverters_pages": 2,
    "hukd_tags": [],
    "sites": {
        "ebay": True,
        "ebay_refurbished": True,
        "ebay_auctions": True,
        "cex": True,
        "backmarket": True,
        "musicmagpie": True,
        "cashconverters": True,
        "hukd": True,
        "reddit_hws": False,
    },
    "watches": [],
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log(f"No config.json found at {CONFIG_PATH} - writing a starter one.")
        CONFIG_PATH.write_text(json.dumps(STARTER_CONFIG, indent=2), encoding="utf-8")
    cfg = dict(DEFAULT_CONFIG)
    try:
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"config.json is not valid JSON ({exc.msg} at line {exc.lineno}) - "
            f"fix or delete {CONFIG_PATH}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError(f"config.json should contain one object - fix or delete {CONFIG_PATH}")
    cfg.update(loaded)
    _adopt_new_watches(cfg)
    return cfg


def _adopt_new_watches(cfg: dict) -> None:
    """Add watches that a newer version brought to a config.json that predates
    them. Without this an upgraded install never sees anything new, because
    config.json holds the whole catalogue from the day it was first written.
    Existing watches are left exactly as the user has them."""
    watches = cfg.get("watches")
    if not isinstance(watches, list):
        return
    have = {w.get("name") for w in watches if isinstance(w, dict)}
    added = [dict(w) for w in WATCH_CATALOGUE if w["name"] not in have]
    # Sources a newer version brought get their default on/off state too;
    # the user's choices on the existing ones are kept.
    sites = cfg.get("sites")
    new_sites = []
    if isinstance(sites, dict):
        for key, default in DEFAULT_CONFIG["sites"].items():
            if key not in sites:
                sites[key] = default
                new_sites.append(key)
    if not added and not new_sites:
        return
    watches.extend(added)
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        if added:
            log(f"Added {len(added)} new watch(es) from this version: "
                + ", ".join(w["name"] for w in added))
        if new_sites:
            log("New sources from this version: " + ", ".join(new_sites)
                + " (see Settings to switch them on or off)")
    except OSError as exc:
        log(f"Could not save the new watches to config.json: {exc}")


def downloads_dir() -> Path:
    """The user's Downloads folder - where anything saved for the user lands
    unless they have chosen somewhere else in Settings."""
    if os.name == "nt":
        # Windows can relocate Downloads, so ask the shell rather than assume.
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]

            downloads = GUID(0x374DE290, 0x123F, 0x4565,
                             (wintypes.BYTE * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            buf = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(downloads), 0, None,
                                                          ctypes.byref(buf)) == 0:
                found = buf.value
                ctypes.windll.ole32.CoTaskMemFree(buf)
                if found and os.path.isdir(found):
                    return Path(found)
        except Exception:
            pass
    home = Path.home()
    candidate = home / "Downloads"
    return candidate if candidate.is_dir() else home


def default_save_dir(cfg: dict | None = None) -> Path:
    """Where saved files go: the "save_dir" setting if it points at a real
    folder, otherwise Downloads. Config, keys and logs are not affected."""
    chosen = str((cfg or {}).get("save_dir") or "").strip()
    if chosen:
        path = Path(chosen).expanduser()
        if path.is_dir():
            return path
    return downloads_dir()


# --------------------------------------------------------------------------- #
# eBay API client
# --------------------------------------------------------------------------- #

class EbayError(RuntimeError):
    """`code` is the HTTP status when there was one. `fatal` means the rest of
    the scan cannot succeed either - bad keys, the daily rate limit, or no
    network - so the scan stops rather than failing the same way 100 times."""

    def __init__(self, message: str, code: int | None = None, fatal: bool = False):
        super().__init__(message)
        self.code = code
        self.fatal = fatal


def is_auth_error(exc: Exception) -> bool:
    """Should this error stop the whole scan? Bad keys, rate limit, no network.

    Decided from the response code, not by searching the message for "403" -
    an item id or offset containing those digits used to abort a scan.
    """
    if getattr(exc, "fatal", False):
        return True
    code = getattr(exc, "code", None)
    if code in (401, 403):
        return True
    text = str(exc).lower()
    return "invalid_client" in text or "unauthorized" in text


def _open(req, timeout, label="eBay"):
    """urlopen with one retry on a dropped connection or DNS blip.

    A second failure is treated as no network at all: without this a scan of
    26 watches x 3 sources sat through ~80 timeouts, unstoppable, with the
    window saying "Scanning..." for the best part of an hour.
    """
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            try:
                return json.loads(raw.decode("utf-8"))
            except ValueError as exc:
                raise EbayError(f"{label} replied with something that wasn't JSON "
                                f"({raw[:80]!r}).") from exc
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 2:
                reason = getattr(exc, "reason", exc)
                raise EbayError(f"Network problem reaching {label}: {reason}", fatal=True) from exc
            time.sleep(2)


class EbayClient:
    def __init__(self, client_id: str, client_secret: str, marketplace: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.marketplace = marketplace
        self._token = None
        self._token_expiry = 0.0
        self._load_cached_token()

    # -- auth ------------------------------------------------------------- #
    def _load_cached_token(self) -> None:
        if not TOKEN_CACHE.exists():
            return
        try:
            data = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            if data.get("client_id") == self.client_id and data.get("expiry", 0) > time.time() + 60:
                self._token = data["token"]
                self._token_expiry = data["expiry"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    def _fetch_token(self) -> None:
        creds = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode("utf-8")
        ).decode("ascii")
        body = urllib.parse.urlencode(
            {"grant_type": "client_credentials", "scope": EBAY_SCOPE}
        ).encode("utf-8")
        req = urllib.request.Request(
            EBAY_OAUTH_URL,
            data=body,
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            payload = _open(req, timeout=30)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise EbayError(
                f"Could not get an eBay token (HTTP {exc.code}). "
                f"Check the App ID / Cert ID are your *production* keys. "
                f"eBay said: {detail}", code=exc.code, fatal=True,
            ) from exc

        try:
            self._token = payload["access_token"]
        except (KeyError, TypeError) as exc:
            raise EbayError("eBay's token reply had no access_token in it.", fatal=True) from exc
        self._token_expiry = time.time() + int(payload.get("expires_in", 7200))
        try:
            TOKEN_CACHE.write_text(
                json.dumps(
                    {
                        "client_id": self.client_id,
                        "token": self._token,
                        "expiry": self._token_expiry,
                    }
                ),
                encoding="utf-8",
            )
            os.chmod(TOKEN_CACHE, 0o600)
        except OSError:
            pass

    def token(self) -> str:
        if not self._token or time.time() > self._token_expiry - 60:
            self._fetch_token()
        return self._token

    # -- search ----------------------------------------------------------- #
    def search(self, query: str, filters: list[str], limit: int = 100,
               sort: str | None = None, category_ids: list[str] | None = None) -> list[dict]:
        """Return a list of itemSummaries. Pages automatically up to `limit`."""
        collected: list[dict] = []
        offset = 0
        page_size = min(200, limit)
        refreshed_token = False

        while len(collected) < limit:
            params = {
                "q": query,
                "limit": str(min(page_size, limit - len(collected))),
                "offset": str(offset),
            }
            if filters:
                params["filter"] = ",".join(filters)
            if sort:
                params["sort"] = sort
            if category_ids:
                params["category_ids"] = ",".join(category_ids)

            url = f"{EBAY_BROWSE_URL}?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self.token()}",
                    "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
                    "X-EBAY-C-ENDUSERCTX": "contextualLocation=country=GB",
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                payload = _open(req, timeout=45)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                if exc.code == 429:
                    # The limit is per day, so the rest of the scan would only
                    # fail the same way - stop here and let auto try later.
                    raise EbayError("eBay rate limit hit - back off and try later.",
                                    code=429, fatal=True) from exc
                if exc.code == 401 and not refreshed_token:
                    # A cached token eBay no longer accepts. Fetch a fresh one
                    # and retry this page once before blaming the keys.
                    self._token = None
                    refreshed_token = True
                    continue
                raise EbayError(f"eBay search failed (HTTP {exc.code}): {detail}",
                                code=exc.code) from exc

            items = payload.get("itemSummaries") or []
            collected.extend(items)
            total = int(payload.get("total", 0))
            offset += len(items)
            if not items or offset >= total:
                break
            time.sleep(0.3)  # be polite

        return collected[:limit]


# --------------------------------------------------------------------------- #
# normalising + filtering
# --------------------------------------------------------------------------- #

def biggest_image(url: str) -> str:
    """
    eBay hands back a small thumbnail (s-l140 / s-l225). The same URL with a
    larger size code returns a proper picture, which is what we want on screen.
    """
    if not url:
        return ""
    return re.sub(r"/s-l\d+\.(jpg|jpeg|png|webp)", r"/s-l500.\1", url, flags=re.I)


def normalise(item: dict) -> dict:
    price = money((item.get("price") or {}).get("value"))
    currency = (item.get("price") or {}).get("currency", "GBP")

    # On an auction, `price` is the start price - what matters is the bid so far.
    bid = item.get("currentBidPrice") or {}
    bid_count = int(item.get("bidCount") or 0)
    is_auction = "AUCTION" in (item.get("buyingOptions") or [])
    if is_auction and bid.get("value") is not None:
        price = money(bid["value"])
        currency = bid.get("currency", currency)

    shipping = 0.0
    free_shipping = False
    for opt in item.get("shippingOptions") or []:
        cost = (opt.get("shippingCost") or {}).get("value")
        if cost is not None:
            shipping = money(cost)
            free_shipping = shipping == 0.0
            break

    seller = item.get("seller") or {}
    image = (item.get("image") or {}).get("imageUrl") or ""
    if not image:
        thumbs = item.get("thumbnailImages") or []
        image = thumbs[0].get("imageUrl", "") if thumbs else ""
    image = biggest_image(image)

    loc = item.get("itemLocation") or {}
    country = (loc.get("country") or "").upper()
    location = ", ".join(
        p for p in [loc.get("city"), loc.get("postalCode"), loc.get("country")] if p
    )

    return {
        "country": country,
        "bid_count": bid_count,
        "is_auction": is_auction,
        "ends": item.get("itemEndDate", "") or "",
        "item_id": item.get("itemId", ""),
        "title": (item.get("title") or "").strip(),
        "price": price,
        "shipping": shipping,
        "total": round(price + shipping, 2),
        "currency": currency,
        "free_shipping": free_shipping,
        "condition": item.get("condition") or "Unspecified",
        "url": item.get("itemWebUrl", ""),
        "image": image,
        "seller_name": seller.get("username", ""),
        "seller_pct": money(seller.get("feedbackPercentage") or 0),
        "seller_score": int(seller.get("feedbackScore") or 0),
        "location": location,
        "buying_options": ",".join(item.get("buyingOptions") or []),
        "categories": ",".join(
            c.get("categoryName", "") for c in (item.get("categories") or [])
        ),
    }


def title_blocked(title: str, excludes: list[str]) -> str | None:
    """Return the offending term if the title trips an exclusion."""
    low = f" {title.lower()} "
    for term in excludes:
        t = term.lower().strip()
        if not t:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"
        if re.search(pattern, low):
            return term
    return None


def title_has_all(title: str, required: list[str]) -> bool:
    """Every required term appears as a whole word. A plain substring test let
    "tb" pass on "portable" and "ssd" on nothing useful - whole words only."""
    low = f" {title.lower()} "
    for term in required:
        t = term.lower().strip()
        if not t:
            continue
        if not re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low):
            return False
    return True


# --------------------------------------------------------------------------- #
# specs: brand, CPU, RAM, storage
# --------------------------------------------------------------------------- #
#
# A watch can ask for a minimum RAM or storage, a CPU family and a brand. eBay
# titles are the only source of that for eBay listings, so they are parsed;
# CeX hands the same facts over as structured attributes, so nothing is
# guessed there. A listing that simply doesn't state a spec is "unknown", and
# the watch decides whether unknowns are kept (flagged "spec unclear") or
# dropped - "specs_required".

SPEC_FIELDS = ("brands", "cpus", "min_ram_gb", "min_storage_gb")

_SIZE_RE = re.compile(r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*(gb|tb)(?![a-z0-9])", re.I)
_LABEL_RE = re.compile(r"(?<![a-z0-9])(ram|ddr[345]l?|lpddr[345]x?|memory|unified|"
                       r"ssd|hdd|nvme|storage|emmc|hard\s*drive|m\.2|sata|flash)(?![a-z0-9])", re.I)
_RAM_LABELS = {"ram", "memory", "unified"}     # anything starting ddr/lpddr is RAM too
_SEPARATOR_RE = re.compile(r"[,/|;()\-]")


def parse_specs(title: str) -> dict:
    """Pull RAM and storage sizes (GB) out of a title where they are stated.

    Every size ("16GB", "1TB") is found, then every label word (RAM, SSD...)
    is given to the nearest size: the one before it, unless a separator sits
    between them or the label ends in a colon, in which case the one after
    ("16GB RAM, 512GB SSD" and "RAM: 16GB, SSD: 512GB" both read correctly).
    Unlabelled sizes fall back to plausibility: two of them means the smaller
    is RAM and the larger storage; one on its own is storage if it is 120GB+
    or the item is a phone or tablet, otherwise RAM. Returns {} when unsure.
    """
    low = title.lower()
    sizes = [(m.start(), m.end(),
              float(m.group(1)) * (1024 if m.group(2).lower() == "tb" else 1))
             for m in _SIZE_RE.finditer(low)]
    if not sizes:
        return {}
    kinds = [None] * len(sizes)

    for lm in _LABEL_RE.finditer(low):
        word = lm.group(1).lower()
        kind = "ram" if (word in _RAM_LABELS or word.startswith(("ddr", "lpddr"))) else "storage"
        before = [i for i, (s, e, _) in enumerate(sizes) if e <= lm.start()]
        after = [i for i, (s, e, _) in enumerate(sizes) if s >= lm.end()]
        target = None
        if before:
            gap = low[sizes[before[-1]][1]:lm.start()]
            prefix_style = _SEPARATOR_RE.search(gap) or low[lm.end():lm.end() + 1] == ":"
            if not (prefix_style and after):
                target = before[-1]
        if target is None and after:
            target = after[0]
        if target is not None and kinds[target] is None:
            kinds[target] = kind

    ram = [v for (s, e, v), k in zip(sizes, kinds) if k == "ram"]
    sto = [v for (s, e, v), k in zip(sizes, kinds) if k == "storage"]
    free = [v for (s, e, v), k in zip(sizes, kinds) if k is None]

    # Sanity: nothing consumer-grade has more than 128GB of RAM. Two "RAM"
    # values with no storage means the second label was really the drive.
    if len(ram) >= 2 and not sto:
        sto.append(max(ram)); ram.remove(max(ram))
    ram_ok = [v for v in ram if v <= 128]
    sto += [v for v in ram if v > 128]
    ram = ram_ok

    out = {}
    if ram:
        out["ram_gb"] = max(ram)
    if sto:
        out["storage_gb"] = max(sto)
    if free:
        handheld = any(w in low for w in ("iphone", "ipad", "galaxy tab", "tablet", "pixel",
                                          "phone", "kindle", "switch", "steam deck"))
        if len(free) >= 2 and "ram_gb" not in out and "storage_gb" not in out:
            out["ram_gb"], out["storage_gb"] = min(free), max(free)
        elif "storage_gb" not in out and (max(free) >= 120 or handheld):
            out["storage_gb"] = max(free)
        elif "ram_gb" not in out and max(free) <= 128:
            out["ram_gb"] = max(free)
    return out


def _listed(value) -> list[str]:
    """Accept a list or a comma-separated string; return clean lowercase terms."""
    if isinstance(value, str):
        value = value.split(",")
    return [str(v).strip().lower() for v in (value or []) if str(v).strip()]


def spec_check(rec: dict, watch: dict) -> tuple[bool, str, bool]:
    """
    Does this listing meet the watch's spec fields?

    Returns (ok, reason, unclear). `unclear` is True when a requested spec
    wasn't stated at all - the watch's `specs_required` decides whether that
    is a rejection or just a flag.
    """
    specs = dict(rec.get("specs") or {})
    title = rec.get("title", "")
    for key in ("ram_gb", "storage_gb"):
        if key not in specs:
            specs.update({k: v for k, v in parse_specs(title).items() if k not in specs})
            break
    rec["specs"] = specs
    required = bool(watch.get("specs_required"))
    unclear = False

    brands = _listed(watch.get("brands"))
    if brands:
        stated = (specs.get("brand") or "").lower()
        if stated:
            if not any(b == stated or b in stated for b in brands):
                return False, f"brand is {stated}", False
        elif not any(title_has_all(title, [b]) for b in brands):
            return False, f"not one of: {', '.join(brands)}", False

    cpus = _listed(watch.get("cpus"))
    if cpus:
        stated = (specs.get("cpu") or "").lower()
        hay = f"{stated} {title}"
        if not any(title_has_all(hay, [c]) for c in cpus):
            if stated or _cpu_mentioned(title):
                return False, "cpu not in list", False
            if required:
                return False, "cpu not stated", True
            unclear = True

    for key, label in (("min_ram_gb", "RAM"), ("min_storage_gb", "storage")):
        want = watch.get(key)
        if not want:
            continue
        try:
            want = float(want)
        except (TypeError, ValueError):
            continue
        have = specs.get(key.replace("min_", ""))
        if have is None:
            if required:
                return False, f"{label} not stated", True
            unclear = True
            continue
        if have < want:
            return False, f"{label} {have:g}GB < {want:g}GB", False

    return True, "", unclear


_CPU_RE = re.compile(r"(?<![a-z0-9])(i[3579]|ryzen|celeron|pentium|athlon|core\s*2|xeon|"
                     r"m[1-4]|snapdragon|apple\s+m[1-4]|atom)(?![a-z])", re.I)


def _cpu_mentioned(title: str) -> bool:
    return bool(_CPU_RE.search(title))


def specs_summary(specs: dict) -> str:
    """One short line for the row: 'Apple · i5 · 8GB · 256GB'."""
    if not specs:
        return ""
    bits = []
    if specs.get("brand"):
        bits.append(str(specs["brand"]))
    if specs.get("cpu"):
        bits.append(str(specs["cpu"]))
    for key in ("ram_gb", "storage_gb"):
        v = specs.get(key)
        if v:
            bits.append(f"{v / 1024:g}TB" if v >= 1024 and v % 512 == 0 else f"{v:g}GB")
    return " · ".join(bits)


# Whole words only. "un" as a prefix used to be in here, which meant "Arduino
# Uno fully working" read as a negation - the word before ended in "no".
NEGATORS = {
    "not", "non", "no", "never", "without", "nothing", "isnt", "isn't",
    "doesnt", "doesn't", "wasnt", "wasn't", "barely", "hardly", "stopped",
    "ceased", "needs", "requires", "untested", "unknown",
}

# How many words before a claim get checked for a negation. Three covers
# "not in working order" and "never been in working order" without reaching
# back so far that an unrelated earlier word poisons it.
NEGATION_LOOKBACK_WORDS = 3

WORD_RE = re.compile(r"[a-z0-9']+")


def has_working_evidence(title: str, working_terms: list[str]) -> str | None:
    """
    Find a phrase in the title that positively claims the item works.

    Every match is checked against the words immediately before it, so
    "non functional", "not in working order" and "never been in working order"
    are all correctly read as the opposite of a working claim.
    """
    low = title.lower()
    for term in working_terms:
        t = term.lower().strip()
        if not t:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"
        for match in re.finditer(pattern, low):
            preceding = WORD_RE.findall(low[:match.start()])[-NEGATION_LOOKBACK_WORDS:]
            if not any(w in NEGATORS for w in preceding):
                return term
    return None


def has_negated_working_claim(title: str, working_terms: list[str]) -> str | None:
    """
    The mirror image: a working phrase that IS negated.

    "non functional" and "not in working order" are statements that the thing is
    broken, so they should be thrown out rather than merely left unproven.
    """
    low = title.lower()
    for term in working_terms:
        t = term.lower().strip()
        if not t:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"
        for match in re.finditer(pattern, low):
            preceding = WORD_RE.findall(low[:match.start()])[-NEGATION_LOOKBACK_WORDS:]
            hit = next((w for w in preceding if w in NEGATORS), None)
            if hit and hit not in ("needs", "requires"):  # "needs charger" isn't a fault
                return f"{hit} {term}"
    return None


def assess_quality(rec: dict, watch: dict, cfg: dict, excludes: list[str]) -> tuple[str, str]:
    """
    Decide whether a listing is a working item.

    Returns (verdict, reason) where verdict is one of:
      "working" - condition or title positively says it functions
      "unsure"  - nothing says it's broken, but nothing says it works either
      "reject"  - eBay condition or the title says it's broken / not the item
    """
    title = rec["title"]
    cond = (rec["condition"] or "").strip().lower()

    banned = [c.lower() for c in cfg.get("banned_conditions", [])]
    if cond in banned or "not working" in cond or "for parts" in cond:
        return "reject", f"eBay condition is '{rec['condition']}'"

    hit = title_blocked(title, excludes)
    if hit:
        return "reject", f"title says '{hit}'"

    negated = has_negated_working_claim(title, cfg.get("working_terms", []))
    if negated:
        return "reject", f"title says '{negated}'"

    trusted = [c.lower() for c in cfg.get("trusted_conditions", [])]
    if cond in trusted:
        return "working", f"condition '{rec['condition']}'"

    phrase = has_working_evidence(title, cfg.get("working_terms", []))
    if phrase:
        return "working", f"title says '{phrase}'"

    return "unsure", "no condition claim either way"


def quality_allows(verdict: str, mode: str) -> bool:
    if verdict == "reject":
        return False
    if mode == "strict":
        return verdict == "working"
    if mode == "loose":
        return True
    return verdict in ("working", "unsure")  # balanced


def build_filters(watch: dict, cfg: dict, *, for_baseline: bool) -> list[str]:
    currency = cfg["currency"]
    filters = ["buyingOptions:{FIXED_PRICE}"]

    conditions = watch.get("conditions") or []
    if conditions:
        filters.append("conditions:{" + "|".join(conditions) + "}")

    # eBay wants an explicit two-sided range, so always give it one.
    if for_baseline:
        # The market sample deliberately ignores the bargain cap - we want the
        # normal going rate, which sits well above what we're hunting for.
        lo = watch.get("baseline_min_price", 1)
        hi = watch.get("baseline_max_price") or (
            int(watch.get("max_price", 100)) * 20
        )
        filters.append(f"price:[{lo}..{hi}]")
    else:
        floor = watch.get("min_price", 1)
        cap = watch.get("max_price") or 100000
        filters.append(f"price:[{floor}..{cap}]")
    filters.append(f"priceCurrency:{currency}")

    # UK-only, always. Item must physically be in Great Britain and deliverable
    # here - this is what keeps import duty, VAT handling fees and customs out
    # of it. There is deliberately no per-watch override.
    filters.append("itemLocationCountry:GB")
    filters.append("deliveryCountry:GB")
    return filters


# Titles that give away an overseas seller using a UK-looking listing.
IMPORT_TELLS = [
    "import", "imported", "customs", "duty free", "ships from china",
    "ship from china", "from china", "from usa", "from the usa", "from hong kong",
    "us seller", "china post", "aliexpress", "japan import", "jp import",
    "us plug", "eu plug", "us version", "japanese version", "110v", "120v",
    "no uk plug", "adapter needed",
]


def uk_ok(rec: dict, cfg: dict) -> tuple[bool, str]:
    """Second line of defence against anything that would attract import fees."""
    country = rec.get("country", "")
    if country and country != "GB":
        return False, f"item is located in {country}"
    tell = title_blocked(rec["title"], cfg.get("import_tells", IMPORT_TELLS))
    if tell:
        return False, f"title suggests an import ('{tell}')"
    return True, ""


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id       TEXT PRIMARY KEY,
    watch         TEXT NOT NULL,
    grp           TEXT,
    source        TEXT,
    country       TEXT,
    title         TEXT,
    price         REAL,
    shipping      REAL,
    total         REAL,
    currency      TEXT,
    free_shipping INTEGER,
    condition     TEXT,
    url           TEXT,
    image         TEXT,
    seller_name   TEXT,
    seller_pct    REAL,
    seller_score  INTEGER,
    location      TEXT,
    baseline      REAL,
    discount_pct  REAL,
    first_seen    TEXT,
    last_seen     TEXT,
    is_live       INTEGER DEFAULT 1,
    flags         TEXT,
    bid_count     INTEGER DEFAULT 0,
    ends          TEXT,
    quality       TEXT,
    quality_why   TEXT,
    specs         TEXT
);
CREATE TABLE IF NOT EXISTS baselines (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    watch     TEXT NOT NULL,
    ts        TEXT NOT NULL,
    median    REAL,
    sample_n  INTEGER,
    p10       REAL,
    p90       REAL
);
CREATE TABLE IF NOT EXISTS runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    watches   INTEGER,
    scanned   INTEGER,
    new_hits  INTEGER,
    note      TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_watch ON items(watch);
CREATE INDEX IF NOT EXISTS idx_baselines_watch ON baselines(watch, ts);
"""


# Columns added after the first release. CREATE TABLE IF NOT EXISTS does nothing
# to a table that already exists, so an upgraded install would otherwise fail on
# every insert with "table items has no column named ...".
MIGRATIONS = {
    "items": [
        ("grp", "TEXT"),
        ("source", "TEXT"),
        ("country", "TEXT"),
        ("quality", "TEXT"),
        ("quality_why", "TEXT"),
        ("flags", "TEXT"),
        ("is_live", "INTEGER DEFAULT 1"),
        ("bid_count", "INTEGER DEFAULT 0"),
        ("ends", "TEXT"),
        ("specs", "TEXT"),
    ],
}


def migrate(conn: sqlite3.Connection) -> None:
    for table, columns in MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table is brand new, SCHEMA already made it correctly
        for name, decl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                log(f"Database upgraded: added {table}.{name}")
    conn.commit()


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


def latest_baseline(conn: sqlite3.Connection, watch: str, max_age_hours: float):
    row = conn.execute(
        "SELECT median, sample_n, ts FROM baselines WHERE watch=? ORDER BY id DESC LIMIT 1",
        (watch,),
    ).fetchone()
    if not row or not row["median"]:
        return None
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["ts"])).total_seconds() / 3600
    if age > max_age_hours:
        return None
    return row["median"]


def save_baseline(conn, watch, median, n, p10, p90) -> None:
    conn.execute(
        "INSERT INTO baselines (watch, ts, median, sample_n, p10, p90) VALUES (?,?,?,?,?,?)",
        (watch, now_utc(), median, n, p10, p90),
    )
    conn.commit()


def upsert_item(conn, rec: dict) -> bool:
    """Insert or update. Returns True if this is a brand-new hit."""
    existing = conn.execute(
        "SELECT item_id, total FROM items WHERE item_id=?", (rec["item_id"],)
    ).fetchone()
    ts = now_utc()
    if existing:
        conn.execute(
            """UPDATE items SET title=?, price=?, shipping=?, total=?, condition=?,
               seller_pct=?, seller_score=?, baseline=?, discount_pct=?, last_seen=?,
               is_live=1, flags=?, quality=?, quality_why=?, url=?, image=?,
               bid_count=?, ends=?, specs=? WHERE item_id=?""",
            (rec["title"], rec["price"], rec["shipping"], rec["total"], rec["condition"],
             rec["seller_pct"], rec["seller_score"], rec["baseline"], rec["discount_pct"],
             ts, rec["flags"], rec.get("quality", ""), rec.get("quality_why", ""),
             rec["url"], rec["image"], int(rec.get("bid_count") or 0),
             rec.get("ends", ""), specs_summary(rec.get("specs") or {}), rec["item_id"]),
        )
        return False

    conn.execute(
        """INSERT INTO items (item_id, watch, grp, source, country, title, price,
           shipping, total, currency, free_shipping, condition, url, image,
           seller_name, seller_pct, seller_score, location, baseline, discount_pct,
           first_seen, last_seen, is_live, flags, quality, quality_why,
           bid_count, ends, specs)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?)""",
        (rec["item_id"], rec["watch"], rec.get("group", "Other"),
         rec.get("source", "eBay"), rec.get("country", "GB"), rec["title"], rec["price"], rec["shipping"],
         rec["total"], rec["currency"], int(rec["free_shipping"]), rec["condition"],
         rec["url"], rec["image"], rec["seller_name"], rec["seller_pct"],
         rec["seller_score"], rec["location"], rec["baseline"], rec["discount_pct"],
         ts, ts, rec["flags"], rec.get("quality", ""), rec.get("quality_why", ""),
         int(rec.get("bid_count") or 0), rec.get("ends", ""),
         specs_summary(rec.get("specs") or {})),
    )
    return True


# --------------------------------------------------------------------------- #
# scanning
# --------------------------------------------------------------------------- #

def trimmed_stats(values: list[float]):
    """Return (median, p10, p90, n) with the extremes trimmed off."""
    vals = sorted(v for v in values if v > 0)
    if len(vals) < 4:
        return (statistics.median(vals) if vals else 0.0, 0.0, 0.0, len(vals))
    # Trim the same number off each end. Trimming only the top (which is what
    # int(n*0.9) does on its own for n < 10) drags the median down and makes a
    # thin market look cheaper than it is.
    k = int(len(vals) * 0.10)
    core = vals[k:len(vals) - k] if k else vals
    p10 = vals[int((len(vals) - 1) * 0.10)]
    p90 = vals[int((len(vals) - 1) * 0.90)]
    return round(statistics.median(core), 2), round(p10, 2), round(p90, 2), len(core)


def compute_baseline(client, conn, watch, cfg, excludes) -> float | None:
    """Median total price of comparable *live* Buy It Now listings."""
    name = watch["name"]
    cached = latest_baseline(conn, name, cfg["baseline_max_age_hours"])
    if cached:
        return cached

    query = watch.get("baseline_query") or watch["query"]
    filters = build_filters(watch, cfg, for_baseline=True)
    try:
        raw = client.search(
            query,
            filters,
            limit=cfg["baseline_sample_size"],
            category_ids=watch.get("category_ids"),
        )
    except EbayError as exc:
        if is_auth_error(exc):
            raise                       # keys are wrong: stop, don't limp on
        log(f"  ! baseline for '{name}' failed: {exc}")
        return None

    required = watch.get("require_terms") or []
    totals = []
    for item in raw:
        rec = normalise(item)
        # The baseline must reflect *working, UK-based* items only, or a market
        # full of broken units and overseas imports drags the median down and
        # nothing ever looks like a deal.
        if not uk_ok(rec, cfg)[0]:
            continue
        verdict, _ = assess_quality(rec, watch, cfg, excludes)
        if verdict == "reject":
            continue
        if required and not title_has_all(rec["title"], required):
            continue
        # A 16GB watch compared against every laptop's median is meaningless,
        # so the sample is narrowed the same way the hunt is. Unknowns stay in
        # - dropping them thins the sample too far.
        if not spec_check(rec, watch)[0]:
            continue
        if rec["total"] > 0:
            totals.append(rec["total"])

    if len(totals) < 5:
        log(f"  ! baseline for '{name}': only {len(totals)} clean comparables - skipping score")
        return None

    median, p10, p90, n = trimmed_stats(totals)
    save_baseline(conn, name, median, n, p10, p90)
    log(f"  baseline for '{name}': median {cfg['currency']} {median:.2f} from {n} listings")
    return median


def scan_watch(client, conn, watch, cfg, baseline) -> tuple[int, int]:
    """eBay Buy It Now - the main source."""
    filters = build_filters(watch, cfg, for_baseline=False)
    try:
        raw = client.search(
            watch["query"],
            filters,
            limit=watch.get("result_limit", 100),
            sort=watch.get("sort", "newlyListed"),
            category_ids=watch.get("category_ids"),
        )
    except EbayError as exc:
        if is_auth_error(exc):
            raise
        log(f"  ! search failed: {exc}")
        return 0, 0

    records = [normalise(item) for item in raw]
    kept, new_hits = process_records(conn, watch, cfg, records, baseline, "eBay")
    return kept, new_hits


REFURB_CONDITIONS = {
    "CERTIFIED_REFURBISHED",    # 2000 - refurbished by the manufacturer
    "EXCELLENT_REFURBISHED",    # 2010
    "VERY_GOOD_REFURBISHED",    # 2020
    "GOOD_REFURBISHED",         # 2030
}


def scan_watch_refurbished(client, conn, watch, cfg, baseline) -> tuple[int, int]:
    """
    eBay's own Refurbished programme - the reputable end of the site.

    These are the four graded conditions eBay only lets qualified sellers and
    brand outlets use, and they carry a warranty (typically one to two years).
    The condition guesswork is skipped: eBay has already vetted the grading,
    which is more than can be said for a seller's title.

    Refurbished stock costs more than a private used sale, so the discount bar
    drops a little - a warranty is worth real money.
    """
    allowance = int(cfg.get("refurbished_discount_allowance", 15) or 0)
    relaxed = dict(watch)
    relaxed["min_discount_pct"] = max(0, watch.get("min_discount_pct", 0) - allowance)
    relaxed["conditions"] = sorted(REFURB_CONDITIONS)

    filters = build_filters(relaxed, cfg, for_baseline=False)
    try:
        raw = client.search(
            watch["query"], filters,
            limit=watch.get("result_limit", 100),
            sort=watch.get("sort", "newlyListed"),
            category_ids=watch.get("category_ids"),
        )
    except EbayError as exc:
        if is_auth_error(exc):
            raise
        log(f"  ! refurbished search failed: {exc}")
        return 0, 0

    records = []
    for item in raw:
        rec = normalise(item)
        rec["trusted_source"] = True
        rec["quality_why"] = f"{rec['condition']} - eBay Refurbished, warranty included"
        records.append(rec)

    if not records:
        return 0, 0
    return process_records(conn, relaxed, cfg, records, baseline, "eBay refurb")


def scan_watch_auctions(client, conn, watch, cfg, baseline) -> tuple[int, int]:
    """
    The same hunt, but on auctions about to end.

    A cheap Buy It Now is a race against everyone else watching. An auction
    ending at 2am on a Tuesday with two bids is where things actually go under
    value. Only listings ending soon are worth showing - an auction with three
    days left is priced at nothing and tells you nothing.
    """
    name = watch["name"]
    hours = int(cfg.get("auction_ending_within_hours", 12) or 12)

    filters = ["buyingOptions:{AUCTION}"]
    conditions = watch.get("conditions") or []
    if conditions:
        filters.append("conditions:{" + "|".join(conditions) + "}")
    floor = watch.get("min_price", 1)
    cap = watch.get("max_price") or 100000
    filters.append(f"price:[{floor}..{cap}]")
    filters.append(f"priceCurrency:{cfg['currency']}")
    filters.append("itemLocationCountry:GB")
    filters.append("deliveryCountry:GB")

    try:
        raw = client.search(
            watch["query"], filters,
            limit=watch.get("result_limit", 100),
            sort="endingSoonest",
            category_ids=watch.get("category_ids"),
        )
    except EbayError as exc:
        if is_auth_error(exc):
            raise
        log(f"  ! auction search failed: {exc}")
        return 0, 0

    cutoff = datetime.now(timezone.utc) + timedelta(hours=hours)
    records = []
    for item in raw:
        rec = normalise(item)
        ends = rec.get("ends") or ""
        if ends:
            try:
                when = datetime.fromisoformat(ends.replace("Z", "+00:00"))
            except ValueError:
                continue
            if when > cutoff:
                continue          # too far out to mean anything yet
        records.append(rec)

    if not records:
        log(f"  [eBay auction] nothing ending in the next {hours}h")
        return 0, 0
    return process_records(conn, watch, cfg, records, baseline, "eBay auction")


# --------------------------------------------------------------------------- #
# CeX
# --------------------------------------------------------------------------- #

class CexError(RuntimeError):
    """A CeX problem never stops the eBay half of a scan. `fatal` means CeX is
    switched off for the rest of this scan (refused, rate limited, no network)
    rather than failing the same way on every watch."""

    def __init__(self, message: str, code: int | None = None, fatal: bool = False):
        super().__init__(message)
        self.code = code
        self.fatal = fatal


def cex_queries(query: str) -> list[str]:
    """Turn an eBay-style query into the searches CeX's index understands.

    eBay reads "thinkpad t480 OR t490" as alternatives; Algolia would look for
    the word "or". So each alternative becomes its own search and the results
    are merged. Symbols eBay tolerates are dropped too.
    """
    out = []
    for part in re.split(r"\s+OR\s+", query, flags=re.I):
        part = re.sub(r"[^\w\s.+-]", " ", part)
        part = re.sub(r"\s+", " ", part).strip()
        if part and part.lower() not in (p.lower() for p in out):
            out.append(part)
    return out[:6]


class CexClient:
    """Read-only search against the index behind uk.webuy.com."""

    def __init__(self, cfg: dict):
        self.host = (cfg.get("cex_search_host") or CEX_SEARCH_HOST).rstrip("/")
        self.app_id = cfg.get("cex_app_id") or CEX_APP_ID
        self.api_key = cfg.get("cex_api_key") or CEX_API_KEY
        self.index = cfg.get("cex_index") or CEX_INDEX

    def search(self, query: str, *, min_price=0, max_price=None, limit: int = 100,
               grades=None, online_only: bool = True) -> list[dict]:
        numeric = ["boxVisibilityOnWeb=1", "boxWebBuyAllowed=1"]
        if online_only:
            numeric.append("inStockOnline=1")   # collection-only stock can't be bought online
        if min_price:
            numeric.append(f"sellPrice>={int(min_price)}")
        if max_price:
            numeric.append(f"sellPrice<={int(max_price)}")
        params = {
            "query": query,
            "hitsPerPage": max(1, min(int(limit or 100), 1000)),
            "page": 0,
            "numericFilters": numeric,
            "attributesToRetrieve": ["objectID", "boxName", "sellPrice", "Grade",
                                     "categoryFriendlyName", "imageUrls", "stores",
                                     "inStockOnline", "ecomQuantity", "priceLastChanged",
                                     "Manufacturer", "CPU Series", "RAM", "Storage"],
            "attributesToHighlight": [],
        }
        if grades:
            params["facetFilters"] = [[f"Grade:{g}" for g in grades]]   # inner list = OR
        req = urllib.request.Request(
            f"{self.host}/1/indexes/{self.index}/query",
            data=json.dumps(params).encode("utf-8"),
            headers={
                "x-algolia-application-id": self.app_id,
                "x-algolia-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://uk.webuy.com",
                "Referer": "https://uk.webuy.com/",
                "User-Agent": CEX_USER_AGENT,
            },
        )
        try:
            payload = _open(req, timeout=30, label="CeX")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code in (401, 403):
                raise CexError(f"CeX search refused the request (HTTP {exc.code}). Its search "
                               f"key may have changed - see the README. CeX said: {detail}",
                               code=exc.code, fatal=True) from exc
            if exc.code == 429:
                raise CexError("CeX search rate limit hit - back off and try later.",
                               code=429, fatal=True) from exc
            raise CexError(f"CeX search failed (HTTP {exc.code}): {detail}", code=exc.code) from exc
        except EbayError as exc:      # _open's network failure, relabelled
            raise CexError(str(exc), fatal=exc.fatal) from exc
        if not isinstance(payload, dict) or "hits" not in payload:
            raise CexError(f"CeX search gave an unexpected reply: {str(payload)[:120]}")
        return payload.get("hits") or []


def _first(value) -> str:
    """CeX stores most attributes as one-element lists."""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return "" if value is None else str(value)


def normalise_cex(hit: dict, cfg: dict) -> dict:
    grade = _first(hit.get("Grade")).strip().upper()
    price = money(hit.get("sellPrice"))
    delivery = money(cfg.get("cex_delivery_charge") or 0)
    stocked = hit.get("stores") or []
    local = [s for s in (cfg.get("cex_local_stores") or []) if s in stocked]
    location = "CeX online" + (f" - also in {', '.join(local)}" if local else "")
    images = hit.get("imageUrls") or {}
    image = images.get("large") or images.get("medium") or images.get("small") or ""
    if image:
        # Category folders have spaces in them ("Laptops - Apple Mac").
        image = urllib.parse.quote(image, safe=":/?=&%")
    box = str(hit.get("objectID") or "")

    # CeX states the specs outright - no need to read them off the name.
    specs = {}
    if _first(hit.get("Manufacturer")):
        specs["brand"] = _first(hit.get("Manufacturer")).strip()
    if _first(hit.get("CPU Series")):
        specs["cpu"] = _first(hit.get("CPU Series")).strip()
    for attr, key in (("RAM", "ram_gb"), ("Storage", "storage_gb")):
        m = _SIZE_RE.search(_first(hit.get(attr)) or "")
        if m:
            specs[key] = float(m.group(1)) * (1024 if m.group(2).lower() == "tb" else 1)

    return {
        "specs": specs,
        "country": "GB",
        "bid_count": 0,
        "is_auction": False,
        "ends": "",
        "item_id": f"cex-{box}",
        "title": (hit.get("boxName") or "").strip(),
        "price": price,
        "shipping": delivery,
        "total": round(price + delivery, 2),
        "currency": "GBP",
        "free_shipping": delivery == 0.0,
        "condition": f"CeX grade {grade}" if grade else "CeX tested",
        "url": CEX_PRODUCT_URL + urllib.parse.quote(box),
        "image": image,
        "seller_name": "CeX",
        "seller_pct": 100.0,
        "seller_score": 0,
        "location": location,
        "buying_options": "FIXED_PRICE",
        "categories": hit.get("categoryFriendlyName") or "",
        "trusted_source": True,
        "quality_why": (f"grade {grade} - " if grade else "")
                       + "CeX tested stock, 24-month warranty",
    }


def scan_watch_cex(client: CexClient, conn, watch, cfg, baseline) -> tuple[int, int]:
    """
    The same hunt on CeX's online stock.

    Every box is tested and warrantied, so the condition guesswork is skipped
    like it is for eBay Refurbished, and the discount bar drops by the same
    allowance - shop prices sit above private sales, and the warranty is what
    you pay for. Prices are scored against the eBay market median when there
    is one, so "under market" means under what the same thing fetches used.
    """
    allowance = int(cfg.get("refurbished_discount_allowance", 15) or 0)
    relaxed = dict(watch)
    relaxed["min_discount_pct"] = max(0, watch.get("min_discount_pct", 0) - allowance)

    seen = set()
    records = []
    for q in cex_queries(watch["query"]):
        hits = client.search(
            q,
            min_price=watch.get("min_price", 0),
            max_price=watch.get("max_price"),
            limit=watch.get("result_limit", 100),
            grades=cfg.get("cex_grades") or None,
        )
        for hit in hits:
            rec = normalise_cex(hit, cfg)
            if not rec["item_id"] or rec["item_id"] in seen:
                continue
            seen.add(rec["item_id"])
            records.append(rec)
        time.sleep(0.2)  # be polite

    if not records:
        log("  [CeX] nothing in stock online for this watch")
        return 0, 0
    return process_records(conn, relaxed, cfg, records, baseline, "CeX")


def process_records(conn, watch, cfg, records, baseline, source) -> tuple[int, int]:
    """
    Filter, judge and store a batch of listings from any site.

    Everything after fetching is site-agnostic: the UK check, the condition
    gates, the seller checks and the market scoring are the same whether the
    listing came from eBay's Buy It Now, Refurbished or auction listings,
    or from anywhere else added later.
    """
    name = watch["name"]
    excludes = list(cfg["global_exclude_terms"]) + list(watch.get("exclude_terms") or [])
    required = watch.get("require_terms") or []
    min_disc = watch.get("min_discount_pct", 0)
    min_pct = watch.get("min_seller_feedback_pct", cfg["min_seller_feedback_pct"])
    min_score = watch.get("min_seller_feedback_score", cfg["min_seller_feedback_score"])
    mode = watch.get("quality_mode", cfg.get("quality_mode", "balanced"))
    cap = watch.get("max_price")

    new_hits = 0
    kept = 0
    rejected = 0
    non_uk = 0
    off_spec = 0
    for rec in records:
        if not rec.get("item_id"):
            continue

        ok_uk, uk_why = uk_ok(rec, cfg)
        if not ok_uk:
            non_uk += 1
            continue

        trusted = bool(rec.get("trusted_source"))
        if trusted:
            # A shop that tests and warranties its stock has already answered
            # the condition question - don't second-guess it on wording alone.
            # The "not actually the item" words still apply though: a charger
            # or a case turns up for "macbook" at CeX just as it does on eBay.
            hit = title_blocked(rec["title"], excludes)
            if hit:
                verdict, why = "reject", f"title says '{hit}'"
            else:
                verdict, why = "working", rec.get("quality_why", f"{source} tested stock")
        else:
            verdict, why = assess_quality(rec, watch, cfg, excludes)
        if not quality_allows(verdict, mode):
            rejected += 1
            continue
        if required and not title_has_all(rec["title"], required):
            continue
        spec_ok, spec_why, spec_unclear = spec_check(rec, watch)
        if not spec_ok:
            off_spec += 1
            continue
        if cap and rec["total"] > cap:
            continue
        if not trusted and not rec.get("no_feedback"):
            # Feedback is an eBay idea. A shop is judged by its returns policy,
            # and a Reddit post has no feedback to judge - the row says so.
            if rec["seller_pct"] and rec["seller_pct"] < min_pct:
                continue
            if rec["seller_score"] < min_score:
                continue

        discount = None
        if baseline:
            discount = round((1 - rec["total"] / baseline) * 100, 1)
            if min_disc and discount < min_disc:
                continue

        flags = []
        if discount is not None and discount >= 90:
            flags.append("too-good-to-be-true")
        if not trusted and not rec.get("no_feedback") and rec["seller_score"] < 25:
            flags.append("low-feedback-seller")
        if rec["shipping"] > rec["price"]:
            flags.append("postage-heavy")
        if verdict == "unsure":
            flags.append("condition-unclear")
        if spec_unclear:
            flags.append("spec-unclear")

        rec.update(
            watch=name,
            group=watch.get("group", "Other"),
            source=source,
            baseline=baseline or 0.0,
            discount_pct=discount if discount is not None else 0.0,
            flags="|".join(flags),
            quality=verdict,
            quality_why=why,
        )
        kept += 1
        if upsert_item(conn, rec):
            new_hits += 1
            disc_txt = f"{discount:.0f}% under market" if discount is not None else "no baseline"
            log(f"  NEW  {cfg['currency']} {rec['total']:>8.2f}  ({disc_txt}, {verdict}, {source})  {rec['title'][:58]}")

    conn.commit()
    log(f"  [{source}] {kept} kept | {rejected} rejected on condition | "
        f"{off_spec} off-spec | {non_uk} non-UK | {new_hits} new")
    return kept, new_hits


# --------------------------------------------------------------------------- #
# demo data
# --------------------------------------------------------------------------- #


DEMO_ART = {
    "laptop":  "<rect x='14' y='22' width='72' height='46' rx='4' fill='#dfe6ef' stroke='#8a99ad' stroke-width='2'/><rect x='20' y='28' width='60' height='34' rx='2' fill='#2a78d6'/><rect x='6' y='68' width='88' height='7' rx='3' fill='#8a99ad'/>",
    "audio":   "<path d='M22 58V44a28 28 0 0 1 56 0v14' fill='none' stroke='#2a78d6' stroke-width='7'/><rect x='14' y='52' width='16' height='26' rx='7' fill='#184f95'/><rect x='70' y='52' width='16' height='26' rx='7' fill='#184f95'/>",
    "storage": "<rect x='16' y='30' width='68' height='40' rx='4' fill='#dfe6ef' stroke='#8a99ad' stroke-width='2'/><circle cx='50' cy='50' r='13' fill='none' stroke='#2a78d6' stroke-width='5'/><circle cx='50' cy='50' r='3' fill='#184f95'/>",
    "gpu":     "<rect x='10' y='34' width='80' height='32' rx='3' fill='#dfe6ef' stroke='#8a99ad' stroke-width='2'/><circle cx='34' cy='50' r='11' fill='#2a78d6'/><circle cx='64' cy='50' r='11' fill='#2a78d6'/><rect x='10' y='66' width='80' height='6' fill='#8a99ad'/>",
    "monitor": "<rect x='10' y='24' width='80' height='48' rx='4' fill='#2a78d6' stroke='#8a99ad' stroke-width='2'/><rect x='42' y='72' width='16' height='10' fill='#8a99ad'/><rect x='30' y='82' width='40' height='6' rx='3' fill='#8a99ad'/>",
    "tablet":  "<rect x='26' y='16' width='48' height='68' rx='6' fill='#dfe6ef' stroke='#8a99ad' stroke-width='2'/><rect x='32' y='24' width='36' height='50' rx='2' fill='#2a78d6'/>",
    "network": "<rect x='12' y='40' width='76' height='24' rx='4' fill='#dfe6ef' stroke='#8a99ad' stroke-width='2'/><circle cx='26' cy='52' r='4' fill='#0ca30c'/><circle cx='40' cy='52' r='4' fill='#0ca30c'/><circle cx='54' cy='52' r='4' fill='#2a78d6'/><circle cx='68' cy='52' r='4' fill='#2a78d6'/>",
    "tool":    "<rect x='30' y='30' width='34' height='26' rx='4' fill='#eb6834'/><rect x='40' y='56' width='16' height='26' rx='3' fill='#184f95'/><rect x='64' y='38' width='24' height='10' rx='3' fill='#8a99ad'/>",
}


def demo_image(kind: str) -> str:
    """A small inline picture so demo rows look like the real thing."""
    art = DEMO_ART.get(kind, DEMO_ART["laptop"])
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 100 100'>"
           "<rect width='100' height='100' rx='10' fill='#f1f4f8'/>" + art + "</svg>")
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)


DEMO_ART_MAP = {'MacBook Pro 13': 'laptop', 'MacBook Air': 'laptop', 'Dell Latitude': 'laptop', 'ThinkPad T480': 'laptop', 'Sony WH-1000XM4': 'audio', 'Denon': 'audio', 'Samsung 970': 'storage', 'Synology': 'storage', 'RTX 3060': 'gpu', 'Dell U2719D': 'monitor', 'iPad Air': 'tablet', 'UniFi': 'network', 'Bosch GSB': 'tool', 'Makita DHP484': 'tool'}

DEMO_TITLES = [
    ("Laptops", "MacBook (Apple)", "MacBook Pro 13\" 2017 i5 8GB 256GB - fully working, boots to desktop", 132.0, 210.0),
    ("Laptops", "MacBook (Apple)", "Apple MacBook Air 13\" A1466 i5 8GB 128GB Ventura installed", 158.0, 265.0),
    ("Laptops", "Laptops - any brand", "Dell Latitude 7490 i5 8th gen 16GB 256GB SSD, excellent condition", 96.0, 189.0),
    ("Laptops", "ThinkPad", "Lenovo ThinkPad T480 i5 16GB 512GB - fully tested, Win 11", 141.0, 255.0),
    ("Audio", "Headphones - premium", "Sony WH-1000XM4 wireless headphones, boxed", 89.0, 175.0),
    ("Audio", "Hi-fi separates", "Denon PMA-520AE integrated amplifier, works perfectly", 84.0, 168.0),
    ("Storage", "SSDs", "Samsung 970 EVO Plus 1TB NVMe M.2 - 98% health", 34.0, 66.0),
    ("Storage", "NAS & external drives", "Synology DS218+ 2-bay NAS, no drives, fully working", 118.0, 235.0),
    ("PC components", "Graphics cards", "NVIDIA RTX 3060 Ti 8GB Founders Edition, tested working", 128.0, 218.0),
    ("Displays", "Monitors", "Dell U2719D 27\" 1440p IPS monitor with stand", 58.0, 122.0),
    ("Phones & tablets", "iPads & tablets", "iPad Air 2 64GB wifi space grey, iOS up to date", 54.0, 105.0),
    ("Networking", "Networking gear", "Ubiquiti UniFi Switch 8 POE-60W, good condition", 47.0, 98.0),
    ("Tools", "Cordless power tools", "Bosch GSB 18V-55 combi drill + 2 batteries + case", 62.0, 139.0),
    ("Tools", "Cordless power tools", "Makita DHP484 brushless combi drill body only", 66.0, 118.0),
]


def run_demo(conn, cfg) -> tuple[int, int]:
    rng = random.Random(20260814)
    watches = sorted({w for _, w, _, _, _ in DEMO_TITLES})
    for i, (group, watch, title, price, market) in enumerate(DEMO_TITLES):
        shipping = rng.choice([0.0, 0.0, 4.95, 8.50])
        total = round(price + shipping, 2)
        discount = round((1 - total / market) * 100, 1)
        rec = {
            "item_id": f"demo-{i}",
            "watch": watch,
            "group": group,
            "source": ("eBay refurb" if i in (6, 11)
                       else "eBay auction" if i in (2, 8) else "eBay"),
            "bid_count": 3 if i in (2, 8) else 0,
            "ends": ((datetime.now(timezone.utc)
                      + timedelta(hours=5 if i == 2 else 2)).isoformat(timespec="seconds")
                     if i in (2, 8) else ""),
            "country": "GB",
            "title": title,
            "price": price,
            "shipping": shipping,
            "total": total,
            "currency": "GBP",
            "free_shipping": shipping == 0.0,
            "condition": rng.choice(["Used", "Used", "Seller refurbished"]),
            # Demo rows aren't real listings, so point at the live eBay search
            # for that item - clicking still lands somewhere useful.
            "url": ("https://www.ebay.co.uk/sch/i.html?_nkw="
                    + urllib.parse.quote_plus(title.split(" - ")[0].split(",")[0])
                    + "&LH_BIN=1&LH_PrefLoc=1&_sop=10"),
            "image": demo_image(next((v for k, v in DEMO_ART_MAP.items() if k in title), "laptop")),
            "seller_name": "outlet_store" if i in (6, 11) else f"demo_seller_{i}",
            "seller_pct": rng.choice([98.5, 99.4, 100.0, 96.2]),
            "seller_score": rng.choice([12, 148, 1902, 44]),
            "location": rng.choice(["Cardiff, GB", "Bristol, GB", "Leeds, GB", "London, GB"]),
            "baseline": market,
            "discount_pct": discount,
            "flags": "low-feedback-seller" if i == 0 else ("condition-unclear" if i in (1, 10) else ""),
            "quality": "unsure" if i in (1, 10) else "working",
            "quality_why": "no condition claim either way" if i in (1, 10)
                           else "title says 'fully working'",
            "specs": parse_specs(title),
        }
        upsert_item(conn, rec)
    for watch in watches:
        base = rng.uniform(120, 320)
        for day in range(8):
            save_baseline(conn, watch, round(base * (1 + rng.uniform(-0.06, 0.06)), 2), 40, 0, 0)
    conn.commit()
    return len(DEMO_TITLES), len(DEMO_TITLES)


# --------------------------------------------------------------------------- #
# dashboard
# --------------------------------------------------------------------------- #

def expire_stale(conn, cfg) -> int:
    """
    Retire listings we haven't seen for a while.

    Items get sold. Without this the dashboard slowly fills with things that
    went days ago, and because it sorts by discount the best of them sit
    permanently at the top.
    """
    days = int(cfg.get("listing_expiry_days", 7) or 7)
    cur = conn.execute(
        "UPDATE items SET is_live=0 WHERE is_live=1 AND last_seen < ?",
        ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds"),),
    )
    conn.commit()
    if cur.rowcount:
        log(f"Retired {cur.rowcount} listing(s) not seen in {days} days.")
    return cur.rowcount


def collect_dashboard_data(conn, cfg) -> dict:
    items = [dict(r) for r in conn.execute(
        "SELECT * FROM items WHERE is_live=1 ORDER BY discount_pct DESC, total ASC"
    ).fetchall()]

    history: dict[str, list] = {}
    for row in conn.execute(
        "SELECT watch, ts, median FROM baselines ORDER BY id ASC"
    ).fetchall():
        history.setdefault(row["watch"], []).append(
            {"ts": row["ts"], "median": row["median"]}
        )

    runs = [dict(r) for r in conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT 20"
    ).fetchall()]

    groups: dict[str, list] = {}
    for i in items:
        groups.setdefault(i.get("grp") or "Other", set()).add(i["watch"])

    return {
        "generated": now_utc(),
        "currency": cfg["currency"],
        "items": items,
        "history": history,
        "runs": runs,
        "watches": sorted({i["watch"] for i in items}),
        "groups": {g: sorted(w) for g, w in sorted(groups.items())},
        "enabled_watches": sum(1 for w in cfg.get("watches", []) if w.get("enabled", True)),
        "total_watches": len(cfg.get("watches", [])),
    }


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def select_watches(cfg, names=None, group=None):
    """Work out which watches a run should scan. Returns None on a bad request."""
    watches = cfg.get("watches") or []
    if not watches:
        log("No watches configured.")
        return None

    if names:
        if isinstance(names, str):
            names = names.split(",")
        wanted = [n.strip().lower() for n in names if n.strip()]
        chosen = [w for w in watches if w["name"].lower() in wanted]
        missing = [n for n in wanted if not any(w["name"].lower() == n for w in watches)]
        if missing:
            log(f"No watch called: {', '.join(missing)}")
            return None
        return chosen  # an explicitly named watch runs even if switched off

    if group:
        if isinstance(group, str):
            group = group.split(",")
        wanted = [g.strip().lower() for g in group if g.strip()]
        chosen = [w for w in watches
                  if w.get("group", "Other").lower() in wanted and w.get("enabled", True)]
        if not chosen:
            log(f"No enabled watches in group(s): {', '.join(wanted)}")
            return None
        return chosen

    chosen = [w for w in watches if w.get("enabled", True)]
    if not chosen:
        log("Every watch is switched off - turn at least one on.")
        return None
    return chosen


# --------------------------------------------------------------------------- #
# a whole scan
# --------------------------------------------------------------------------- #

def credentials() -> tuple[str, str]:
    """API keys, from the stored credentials file or the environment."""
    from .paths import CREDS_PATH
    client_id = os.environ.get("EBAY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("EBAY_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return client_id, client_secret
    if CREDS_PATH.exists():
        try:
            data = json.loads(CREDS_PATH.read_text(encoding="utf-8"))
            return data.get("client_id", "").strip(), data.get("client_secret", "").strip()
        except (json.JSONDecodeError, OSError):
            pass
    return "", ""


def save_credentials(client_id: str, client_secret: str) -> None:
    from .paths import CREDS_PATH
    CREDS_PATH.write_text(
        json.dumps({"client_id": client_id.strip(),
                    "client_secret": client_secret.strip()}, indent=2),
        encoding="utf-8",
    )
    try:
        os.chmod(CREDS_PATH, 0o600)
    except OSError:
        pass
    if TOKEN_CACHE.exists():
        try:
            TOKEN_CACHE.unlink()  # keys changed, so the cached token is stale
        except OSError:
            pass


def scan_all(cfg, conn, *, names=None, group=None, demo=False, progress=None):
    """
    Run a full scan. `progress` is called with (done, total, watch_name).
    Returns a summary dict.
    """
    watches = [] if demo else select_watches(cfg, names=names, group=group)
    if watches is None:
        return {"ok": False, "error": "No watches selected.", "scanned": 0, "new_hits": 0}

    scanned = new_hits = 0

    if demo:
        log("Demo data - no eBay calls made.")
        scanned, new_hits = run_demo(conn, cfg)
    else:
        sites_cfg = cfg.get("sites") or {"ebay": True}
        use_ebay = bool(sites_cfg.get("ebay", True))
        use_refurb = bool(sites_cfg.get("ebay_refurbished", True))
        use_auctions = bool(sites_cfg.get("ebay_auctions", True))
        use_cex = bool(sites_cfg.get("cex", False))

        from . import sources as extra
        extra_on = {k: bool(sites_cfg.get(k, False)) for k in extra.SOURCES}

        if not (use_ebay or use_refurb or use_auctions or use_cex or any(extra_on.values())):
            return {"ok": False, "scanned": 0, "new_hits": 0,
                    "error": "Every source is switched off - turn one on in Settings."}

        # eBay needs keys; CeX does not. Without keys the eBay sources are
        # skipped for this scan rather than the whole scan refusing to run.
        client = None
        if use_ebay or use_refurb or use_auctions:
            client_id, client_secret = credentials()
            if client_id and client_secret:
                client = EbayClient(client_id, client_secret, cfg["marketplace"])
            elif use_cex or any(extra_on.values()):
                log("No eBay API keys saved - searching the shops and feeds only this time. "
                    "Add the keys in Settings for eBay and for market prices.")
                use_ebay = use_refurb = use_auctions = False
            else:
                return {"ok": False, "scanned": 0, "new_hits": 0,
                        "error": "No eBay API keys saved yet - add them in Settings."}
        cex = CexClient(cfg) if use_cex else None
        shops = {k: extra.SOURCES[k] for k, on in extra_on.items() if on and extra.SOURCES[k][1] == "shop"}
        feeds = {k: extra.SOURCES[k] for k, on in extra_on.items() if on and extra.SOURCES[k][1] == "feed"}

        active = [n for n, on in (("Buy It Now", use_ebay),
                                  ("Refurbished", use_refurb),
                                  ("auctions", use_auctions),
                                  ("CeX", use_cex)) if on]
        active += [v[0] for v in shops.values()] + [v[0] for v in feeds.values()]

        # Feeds are fetched once per scan and matched against every watch.
        feed_hits: dict[str, dict[str, list]] = {}
        for key, (label, _, fn) in feeds.items():
            try:
                records = fn(cfg)
                feed_hits[label] = extra.match_feed_to_watches(records, watches)
                log(f"[{label}] {len(records)} in the feed, "
                    f"{sum(len(v) for v in feed_hits[label].values())} match a watch")
            except extra.SourceError as exc:
                log(f"  ! {label}: {exc}")
        total = len(watches)
        log(f"Scanning {total} watch(es), UK only, via {' + '.join(active)}.")

        for i, watch in enumerate(watches, 1):
            if progress:
                progress(i - 1, total, watch["name"])
            log(f"- {watch['name']}: '{watch['query']}' up to "
                f"{cfg['currency']} {watch.get('max_price', '-')}")

            try:
                # One market median per watch, worked out once and shared by
                # every source - so it costs one API call, not one per source.
                baseline = latest_baseline(conn, watch["name"],
                                           cfg["baseline_max_age_hours"])
                if baseline is None and client is not None:
                    excludes = (list(cfg["global_exclude_terms"])
                                + list(watch.get("exclude_terms") or []))
                    baseline = compute_baseline(client, conn, watch, cfg, excludes)

                if use_ebay:
                    kept, new = scan_watch(client, conn, watch, cfg, baseline)
                    scanned += kept
                    new_hits += new

                if use_refurb:
                    kept, new = scan_watch_refurbished(client, conn, watch, cfg, baseline)
                    scanned += kept
                    new_hits += new

                if use_auctions:
                    kept, new = scan_watch_auctions(client, conn, watch, cfg, baseline)
                    scanned += kept
                    new_hits += new
            except EbayError as exc:
                log(f"  ! {exc}")
                if is_auth_error(exc):
                    return {"ok": False, "scanned": scanned, "new_hits": new_hits,
                            "error": str(exc)}

            if cex is not None:
                try:
                    kept, new = scan_watch_cex(cex, conn, watch, cfg, baseline)
                    scanned += kept
                    new_hits += new
                except CexError as exc:
                    log(f"  ! {exc}")
                    if exc.fatal:
                        log("  CeX switched off for the rest of this scan.")
                        cex = None

            for key in list(shops):
                label, _, fn = shops[key]
                try:
                    records = fn(watch, cfg)
                    if records:
                        relaxed = dict(watch)
                        relaxed["min_discount_pct"] = max(
                            0, watch.get("min_discount_pct", 0)
                            - int(cfg.get("refurbished_discount_allowance", 15) or 0))
                        kept, new = process_records(conn, relaxed, cfg, records, baseline, label)
                        scanned += kept
                        new_hits += new
                except extra.SourceError as exc:
                    log(f"  ! {label}: {exc}")
                    if exc.fatal:
                        log(f"  {label} switched off for the rest of this scan.")
                        del shops[key]

            for label, per_watch in feed_hits.items():
                hits = per_watch.get(watch["name"])
                if hits:
                    # A feed is a feed: show every match, and let the discount
                    # figure speak for itself rather than gate on it. A Reddit
                    # title rarely says "fully working", so strict watches
                    # relax to balanced here - broken is still rejected.
                    feed_watch = dict(watch, min_discount_pct=0)
                    if feed_watch.get("quality_mode", cfg.get("quality_mode")) == "strict":
                        feed_watch["quality_mode"] = "balanced"
                    kept, new = process_records(conn, feed_watch, cfg, hits, baseline, label)
                    scanned += kept
                    new_hits += new

        if progress:
            progress(total, total, "")

    if not demo:
        expire_stale(conn, cfg)

    conn.execute(
        "INSERT INTO runs (ts, watches, scanned, new_hits, note) VALUES (?,?,?,?,?)",
        (now_utc(), len(watches), scanned, new_hits, "demo" if demo else ""),
    )
    conn.commit()
    return {"ok": True, "scanned": scanned, "new_hits": new_hits,
            "watches": len(watches), "error": ""}


# --------------------------------------------------------------------------- #
# the watch catalogue
# --------------------------------------------------------------------------- #

# Junk that turns up across whole families of searches. Kept here so each watch
# stays readable and you only fix a mistake once.
JUNK = {
    "computing": ["screen", "lcd", "display panel", "digitiser", "digitizer",
                  "hinge", "hinges", "bezel", "webcam", "wifi card", "ribbon",
                  "flex cable", "fan", "heatsink", "thermal", "sticker", "badge",
                  "sleeve", "bag", "backpack", "stand", "riser", "cooling pad",
                  "docking station", "dock", "port replicator", "psu", "power supply",
                  "adapter", "adaptor", "charger", "screws", "screw set", "feet",
                  "manual", "driver disc", "recovery disc", "licence",
                  "license key", "windows key", "office key"],
    "audio": ["earpads", "ear pads", "pads only", "cushions", "headband",
              "replacement pads", "cable only", "aux cable", "case only",
              "carry case", "hard case", "stand", "hanger", "fake", "copy",
              "clone", "airpods case"],
    "storage": ["caddy", "enclosure only", "bracket", "sata cable", "screws",
                "adapter only", "sled", "rails", "tray only", "faulty sectors",
                "bad sectors", "clicking", "not detected"],
}


def _w(name, group, query, baseline_query, max_price, min_discount=40, *,
       enabled=True, min_price=10, quality="balanced", conditions=None,
       require=None, exclude=None, note="", brands=None, cpus=None,
       min_ram=0, min_storage=0, specs_required=False):
    """Build one watch entry. Keeps the catalogue below readable."""
    return {
        "name": name,
        "group": group,
        "enabled": enabled,
        "query": query,
        "baseline_query": baseline_query,
        "max_price": max_price,
        "min_price": min_price,
        "min_discount_pct": min_discount,
        "quality_mode": quality,
        "conditions": conditions or ["USED", "SELLER_REFURBISHED", "CERTIFIED_REFURBISHED"],
        "require_terms": require or [],
        "exclude_terms": exclude or [],
        "sort": "newlyListed",
        "result_limit": 100,
        "note": note,
        # Spec filters - see spec_check(). Empty means "don't care".
        "brands": brands or [],
        "cpus": cpus or [],
        "min_ram_gb": min_ram,
        "min_storage_gb": min_storage,
        "specs_required": specs_required,
    }


WATCH_CATALOGUE = [
    # ---- Laptops ---------------------------------------------------------- #
    _w("Laptops - any brand", "Laptops",
       "laptop i5 OR i7 OR ryzen OR ultrabook", "laptop i5 8gb ssd", 130, 45,
       min_price=30, quality="strict",
       require=["laptop"],
       exclude=JUNK["computing"] + ["celeron", "pentium", "atom", "chromebook",
                                    "emmc", "windows 7", "vista", "netbook"],
       note="Broad sweep. Strict mode because cheap laptops are usually cheap for a reason."),
    _w("MacBook (Apple)", "Laptops",
       "macbook", "macbook pro 13 i5", 200, 40,
       min_price=30, quality="strict",
       require=["macbook"],
       exclude=JUNK["computing"] + ["a1181", "2008", "2009", "2010", "2011",
                                    "core 2 duo", "skin", "cover", "hub"],
       note="Pre-2012 models are e-waste - excluded by year."),
    _w("ThinkPad", "Laptops",
       "thinkpad t480 OR t490 OR x1 carbon OR t14", "thinkpad t480 i5 16gb", 150, 40,
       min_price=30, quality="strict",
       require=["thinkpad"],
       exclude=JUNK["computing"] + ["t400", "t410", "t420", "t430", "x220", "x230"],
       note="Best value-to-reliability ratio in used laptops."),
    _w("Dell business laptops", "Laptops",
       "dell latitude OR precision OR xps laptop", "dell latitude 7490 i5", 140, 40,
       min_price=30, quality="strict",
       require=["dell"],
       exclude=JUNK["computing"] + ["celeron", "e6410", "e6420", "e6430"],
       note=""),
    _w("Gaming laptops", "Laptops",
       "gaming laptop gtx OR rtx", "gaming laptop rtx 3060", 320, 40,
       enabled=False, min_price=80, quality="strict",
       require=["laptop"],
       exclude=JUNK["computing"] + ["gtx 950", "gtx 960", "gtx 1050"],
       note="Off by default - these rarely go cheap and often run hot."),

    # ---- Audio ------------------------------------------------------------ #
    _w("Headphones - premium", "Audio",
       "sony wh-1000xm4 OR wh-1000xm5 OR bose quietcomfort OR sennheiser momentum",
       "sony wh-1000xm4", 95, 45,
       exclude=JUNK["audio"], note=""),
    _w("Earbuds", "Audio",
       "airpods pro OR sony wf-1000xm4 OR galaxy buds pro", "airpods pro 2nd gen", 70, 45,
       exclude=JUNK["audio"] + ["left only", "right only", "single earbud",
                                "one earbud", "charging case only"],
       note="Single-bud listings are the main trap here - excluded."),
    _w("Hi-fi separates", "Audio",
       "integrated amplifier OR av receiver OR cd player hifi",
       "denon OR marantz integrated amplifier", 120, 45,
       enabled=False, min_price=25,
       exclude=JUNK["audio"] + ["remote only", "speaker only", "no remote"],
       note="Off by default - heavy, usually collection only."),
    _w("Speakers - portable & smart", "Audio",
       "sonos OR jbl charge OR ue boom OR bose soundlink", "sonos one", 85, 45,
       exclude=JUNK["audio"] + ["grille only", "mount", "bracket"], note=""),

    # ---- Storage ---------------------------------------------------------- #
    _w("SSDs", "Storage",
       "samsung 970 OR 980 OR 990 evo OR crucial mx500 OR wd black sn770 ssd",
       "samsung 980 1tb nvme", 55, 40,
       min_price=10, conditions=["USED", "NEW", "SELLER_REFURBISHED"],
       require=["ssd"],
       exclude=JUNK["storage"] + ["128gb", "120gb", "240gb", "256gb"],
       note="Sub-500GB excluded - not worth the postage."),
    _w("Hard drives - desktop & NAS", "Storage",
       "wd red OR seagate ironwolf OR toshiba n300 hard drive",
       "wd red 4tb nas hard drive", 70, 40,
       min_price=10, require=["tb"],
       exclude=JUNK["storage"] + ["500gb", "1tb", "green"],
       note="4TB+ only. Always check SMART power-on hours when it arrives."),
    _w("NAS & external drives", "Storage",
       "synology OR qnap nas OR external hard drive 4tb", "synology ds220+", 140, 40,
       min_price=20,
       exclude=JUNK["storage"] + ["ds115", "ds116", "no psu"],
       note=""),
    _w("Memory & RAM", "Storage",
       "ddr4 16gb OR 32gb desktop OR sodimm memory", "ddr4 16gb 3200 desktop ram", 40, 40,
       enabled=False, min_price=8, conditions=["USED", "NEW"],
       require=["ddr4"], exclude=["ddr3", "ddr2", "server", "ecc reg", "rdimm"],
       note="Off by default - cheap enough new that real bargains are rare."),

    # ---- PC components ---------------------------------------------------- #
    _w("Graphics cards", "PC components",
       "rtx 3060 OR rtx 3070 OR rtx 4060 OR rx 6700 graphics card",
       "rtx 3060 12gb graphics card", 170, 40,
       min_price=40, quality="strict",
       exclude=JUNK["computing"] + ["gtx 1050", "gtx 1060", "gt 710", "gt 1030",
                                    "mining", "mined", "no fans"],
       note="Strict mode - ex-mining cards are the classic trap."),
    _w("Mini PCs & SFF desktops", "PC components",
       "optiplex micro OR thinkcentre tiny OR intel nuc OR prodesk mini",
       "optiplex 5060 micro i5", 110, 40,
       min_price=25, quality="strict",
       exclude=JUNK["computing"] + ["barebones", "celeron"],
       note="Excellent little home-server and media-box candidates."),

    # ---- Displays & peripherals ------------------------------------------- #
    _w("Monitors", "Displays",
       "27 inch monitor 1440p OR ultrawide monitor OR 4k monitor",
       "dell 27 inch 1440p monitor", 90, 45,
       min_price=25, quality="strict",
       exclude=JUNK["computing"] + ["dead pixel", "dead pixels", "backlight bleed",
                                    "burn in", "burn-in", "no stand"],
       note="Postage is the killer here - watch for collection-only."),
    _w("Keyboards & mice", "Displays",
       "mechanical keyboard OR logitech mx master OR keychron",
       "keychron k2 mechanical keyboard", 45, 45,
       enabled=False, min_price=12,
       exclude=["keycaps", "keycap set", "switches only", "membrane", "rubber dome"],
       note="Off by default."),

    # ---- Phones & tablets ------------------------------------------------- #
    _w("iPads & tablets", "Phones & tablets",
       "ipad OR galaxy tab", "ipad air 64gb wifi", 120, 40,
       min_price=25, quality="strict",
       exclude=JUNK["computing"] + ["case", "folio", "screen protector",
                                    "stylus", "pencil", "ipad 2", "ipad 3", "ipad 4"],
       note="iCloud-locked units are caught by the global blocklist."),
    _w("Phones", "Phones & tablets",
       "iphone 12 OR iphone 13 OR pixel 7 OR galaxy s22", "iphone 12 128gb unlocked",
       180, 40, enabled=False, min_price=40, quality="strict",
       exclude=JUNK["computing"] + ["case", "cover", "screen protector", "cracked back",
                                    "network locked", "on ee", "on o2", "on vodafone"],
       note="Off by default - highest scam rate of any category. Turn on if you want it."),

    # ---- Networking & smart home ------------------------------------------ #
    _w("Networking gear", "Networking",
       "ubiquiti unifi OR mikrotik OR managed switch poe", "unifi switch 8 poe", 80, 45,
       min_price=15,
       exclude=JUNK["computing"] + ["cloud key gen1", "no poe injector"],
       note=""),
    _w("Smart home", "Networking",
       "philips hue OR tado OR nest thermostat OR shelly", "philips hue starter kit", 55, 45,
       min_price=12,
       exclude=["bulb only", "single bulb", "no bridge"],
       note=""),

    # ---- Tools ------------------------------------------------------------ #
    _w("Cordless power tools", "Tools",
       "makita OR dewalt OR bosch professional cordless drill OR multi tool",
       "makita 18v combi drill", 70, 45,
       min_price=15, conditions=["USED", "NEW", "SELLER_REFURBISHED"],
       exclude=["battery only", "charger only", "case only", "toy", "kids",
                "empty case", "bag only", "clone", "replica"],
       note="Body-only listings are genuine bargains if you already have batteries."),
    _w("Hand & garden tools", "Tools",
       "makita OR bosch hedge trimmer OR mitre saw OR planer", "bosch mitre saw", 80, 45,
       enabled=False, min_price=15,
       exclude=["blade only", "blades only", "handle only"],
       note="Off by default."),

    # ---- Cameras & other tech --------------------------------------------- #
    _w("Cameras & lenses", "Cameras",
       "canon eos OR nikon dslr OR sony alpha camera", "canon eos 750d body", 130, 45,
       enabled=False, min_price=30, quality="strict",
       exclude=["lens cap", "strap", "bag only", "battery only", "body cap",
                "fungus", "haze", "scratched glass", "shutter fault"],
       note="Off by default - shutter count matters more than price."),
    _w("Retro & handheld gaming", "Cameras",
       "steam deck OR nintendo switch OR retro console", "nintendo switch console", 140, 40,
       enabled=False, min_price=25, quality="strict",
       exclude=["joy con only", "joy-con only", "dock only", "game only",
                "drift", "joycon drift", "no charger"],
       note="Off by default. Joy-Con drift is the thing to watch for."),

    # ---- added in 2.1 ----------------------------------------------------- #
    _w("Surface & 2-in-1s", "Laptops",
       "microsoft surface pro OR surface laptop OR yoga 2-in-1",
       "microsoft surface pro 7 i5", 160, 40,
       enabled=False, min_price=40, quality="strict",
       exclude=JUNK["computing"] + ["type cover only", "pen only", "surface rt",
                                    "surface 2", "surface 3"],
       note="Off by default - Surface RT models are useless, excluded by name."),
    _w("Soundbars", "Audio",
       "sonos beam OR samsung soundbar OR yamaha soundbar", "sonos beam gen 2", 110, 45,
       min_price=25,
       exclude=JUNK["audio"] + ["remote only", "sub only", "subwoofer only",
                                "wall bracket", "no remote"],
       note="Big drops when people upgrade TVs. Check the sub is included."),
    _w("Turntables & hi-fi kit", "Audio",
       "technics turntable OR rega planar OR audio technica lp", "audio technica lp120",
       130, 45, enabled=False, min_price=30,
       exclude=JUNK["audio"] + ["stylus only", "needle only", "cartridge only",
                                "belt only", "lid only", "dust cover"],
       note="Off by default - heavy and easily damaged in post."),
    _w("DACs & headphone amps", "Audio",
       "fiio OR schiit OR topping dac OR headphone amplifier", "fiio dac amp", 75, 45,
       enabled=False, min_price=15, exclude=JUNK["audio"],
       note="Off by default - a niche, but bargains are common."),
    _w("CPUs", "PC components",
       "intel i5 OR i7 cpu OR ryzen 5 OR ryzen 7 processor", "ryzen 5 5600 cpu", 85, 40,
       min_price=15, conditions=["USED", "NEW"],
       exclude=JUNK["computing"] + ["cooler only", "fan only", "bent pins",
                                    "no pins", "delidded", "engineering sample"],
       note="Bent pins are the classic write-off - excluded by name."),
    _w("Desktop PCs", "PC components",
       "gaming pc OR desktop computer i5 OR i7 tower", "gaming pc i5 gtx", 220, 40,
       enabled=False, min_price=50, quality="strict",
       exclude=JUNK["computing"] + ["case only", "no gpu", "no ram", "no hdd",
                                    "office pc", "celeron", "pentium"],
       note="Off by default - postage on a tower usually kills the deal."),
    _w("TVs", "Displays",
       "43 inch OR 50 inch OR 55 inch smart tv oled OR qled", "50 inch 4k smart tv",
       200, 50, enabled=False, min_price=50, quality="strict",
       exclude=JUNK["computing"] + ["stand only", "remote only", "cracked screen",
                                    "lines on screen", "no picture", "for parts"],
       note="Off by default - almost always collection only, and screens crack in transit."),
    _w("Projectors", "Displays",
       "epson projector OR benq projector OR portable projector", "epson full hd projector",
       120, 45, enabled=False, min_price=25, quality="strict",
       exclude=JUNK["computing"] + ["lamp only", "bulb only", "no lamp", "low lamp",
                                    "lamp hours", "800x600", "svga"],
       note="Off by default. Lamp hours matter more than price - always ask."),
    _w("Smartwatches & fitness", "Phones & tablets",
       "apple watch OR garmin OR fitbit sense", "apple watch series 6", 110, 40,
       min_price=20, quality="strict",
       exclude=JUNK["computing"] + ["strap only", "band only", "charger only",
                                    "screen protector", "case only", "icloud"],
       note="Strap-only listings are the main noise here."),
    _w("E-readers", "Phones & tablets",
       "kindle paperwhite OR kobo clara OR onyx boox", "kindle paperwhite", 55, 40,
       min_price=12, quality="strict",
       exclude=JUNK["computing"] + ["cover only", "case only", "screen protector",
                                    "ads", "special offers", "registered"],
       note="Watch for accounts still registered to the seller."),
    _w("Raspberry Pi & SBCs", "PC components",
       "raspberry pi 4 OR pi 5 OR orange pi OR odroid", "raspberry pi 4 4gb", 55, 40,
       min_price=10, conditions=["USED", "NEW"],
       exclude=JUNK["computing"] + ["case only", "heatsink only", "zero w",
                                    "pi 2", "pi 3", "hat only"],
       note="Great for a home server. Pi 4 4GB+ is the sweet spot."),
    _w("Servers & homelab", "PC components",
       "dell poweredge OR hp proliant OR mini server", "dell poweredge t30", 160, 45,
       enabled=False, min_price=40, quality="strict",
       exclude=JUNK["computing"] + ["rails only", "caddy only", "no drives",
                                    "chassis only", "no ram"],
       note="Off by default - loud, power-hungry, but very cheap for the specs."),
    _w("Dashcams & action cams", "Cameras",
       "gopro hero OR nextbase dashcam OR insta360", "gopro hero 9", 95, 45,
       min_price=20, quality="strict",
       exclude=["mount only", "case only", "battery only", "housing only",
                "no battery", "screen only", "fake", "copy"],
       note="Handy for the Polo. Check the battery holds charge."),
    _w("Drones", "Cameras",
       "dji mini OR dji mavic OR drone with camera", "dji mini 2", 180, 45,
       enabled=False, min_price=40, quality="strict",
       exclude=["propellers only", "props only", "battery only", "controller only",
                "case only", "toy", "crashed", "no controller"],
       note="Off by default. Crashed units are common - excluded by name."),
    _w("Robot vacuums", "Home tech",
       "roborock OR dyson OR shark robot vacuum", "roborock s5 max", 110, 45,
       min_price=25, quality="strict",
       exclude=["brush only", "filter only", "dock only", "no dock", "no charger",
                "battery only", "spares"],
       note="Batteries and brushes are cheap to replace; docks are not."),
    _w("Coffee machines", "Home tech",
       "sage barista OR gaggia classic OR delonghi espresso", "gaggia classic pro",
       130, 45, enabled=False, min_price=30, quality="strict",
       exclude=["portafilter only", "basket only", "descale", "limescale",
                "leaking", "no pressure", "spares"],
       note="Off by default. Gaggia Classics are endlessly repairable - a good punt."),
    _w("Nail guns & compressors", "Tools",
       "nail gun OR brad nailer OR air compressor", "dewalt brad nailer 18ga", 95, 45,
       min_price=20, conditions=["USED", "NEW", "SELLER_REFURBISHED"],
       exclude=["nails only", "hose only", "fittings only", "toy", "spares"],
       note="Worth having for the panelling - a second-hand brad nailer pays for itself."),
    _w("Laser levels & measuring", "Tools",
       "bosch laser level OR dewalt laser level OR laser measure",
       "bosch green laser level", 70, 45,
       min_price=15, conditions=["USED", "NEW", "SELLER_REFURBISHED"],
       exclude=["mount only", "bracket only", "target only", "tripod only",
                "no battery", "red beam" ],
       note="Green beam is far easier to see indoors - red is excluded."),
    _w("Socket sets & car tools", "Tools",
       "halfords advanced socket set OR torque wrench OR noco jump starter",
       "halfords advanced socket set", 60, 45,
       min_price=10, conditions=["USED", "NEW", "SELLER_REFURBISHED"],
       exclude=["case only", "empty case", "single socket", "one socket", "spares"],
       note="Halfords Advanced sets are lifetime-guaranteed even second-hand."),

    # ---- added in 2.4: beyond tech ---------------------------------------- #
    _w("Consoles - PS5, Xbox, Switch", "Games & media",
       "ps5 console OR playstation 5 OR xbox series x OR nintendo switch oled console",
       "ps5 console disc edition", 220, 40,
       min_price=60, quality="strict",
       exclude=["controller only", "game only", "box only", "skin", "stand", "no controller",
                "no power supply", "banned", "disc drive fault", "hdmi fault", "no hdmi"],
       note="Banned or HDMI-faulty consoles are the trap - excluded by name."),
    _w("Controllers & accessories", "Games & media",
       "dualsense controller OR xbox wireless controller OR switch pro controller",
       "dualsense controller", 30, 40,
       min_price=8,
       exclude=["drift", "stick drift", "shell only", "thumbsticks", "grips", "case only",
                "charging dock only", "faceplate", "buttons only"],
       note="Stick drift is the one thing to check - excluded by name."),
    _w("Games - Switch & PS5", "Games & media",
       "nintendo switch game OR ps5 game", "ps5 game", 25, 40,
       enabled=False, min_price=5, conditions=["USED", "NEW"],
       exclude=["case only", "empty case", "download code", "code only", "digital",
                "no game", "manual only", "insert only"],
       note="Off by default - cheap enough that the postage decides it."),
    _w("LEGO sets", "Games & media",
       "lego set OR lego technic OR lego star wars OR lego icons", "lego technic set", 90, 40,
       min_price=15, conditions=["USED", "NEW"],
       exclude=["minifigure only", "minifigures", "minifig", "instructions only", "box only",
                "incomplete", "parts only", "bulk", "job lot", "1kg", "2kg", "random",
                "compatible", "not lego"],
       note="Incomplete sets and 'compatible' bricks are the traps - excluded by name."),
    _w("Board games", "Games & media",
       "board game OR catan OR ticket to ride OR wingspan OR gloomhaven", "catan board game", 35, 45,
       enabled=False, min_price=8,
       exclude=["missing pieces", "incomplete", "expansion only", "replacement", "parts only"],
       note="Off by default. Always ask if it's complete."),

    _w("Vacuums - Dyson & Shark", "Home & garden",
       "dyson v8 OR v10 OR v11 OR v15 OR shark cordless vacuum", "dyson v11 cordless vacuum", 120, 45,
       min_price=25, quality="strict",
       exclude=["battery only", "head only", "filter only", "tool only", "attachment",
                "no battery", "spares", "wand only", "motorhead only", "dock only"],
       note="Batteries die - a working claim matters more here than most."),
    _w("Air fryers & kitchen", "Home & garden",
       "ninja air fryer OR ninja foodi OR instant pot OR tefal actifry", "ninja air fryer dual zone", 60, 45,
       min_price=15, conditions=["USED", "NEW", "SELLER_REFURBISHED"],
       exclude=["basket only", "lid only", "drawer only", "tray only", "accessories",
                "plate only", "rack only"],
       note=""),
    _w("Stand mixers & coffee grinders", "Home & garden",
       "kitchenaid mixer OR kenwood chef OR sage grinder OR baratza", "kitchenaid artisan mixer", 150, 45,
       min_price=30, quality="strict",
       exclude=["bowl only", "attachment only", "beater", "cover only", "spares", "hook only"],
       note=""),
    _w("Pressure washers & mowers", "Home & garden",
       "karcher OR nilfisk pressure washer OR cordless lawnmower OR robot mower",
       "karcher k4 pressure washer", 90, 45,
       min_price=20,
       exclude=["hose only", "lance only", "nozzle only", "no motor", "blade only", "spares",
                "grass box only", "battery only", "charger only"],
       note="Often collection only - check before getting excited."),
    _w("Heaters & dehumidifiers", "Home & garden",
       "meaco dehumidifier OR dehumidifier 12l OR 20l OR oil filled radiator OR dyson hot cool",
       "meaco dehumidifier 12l", 70, 45,
       min_price=15,
       exclude=["filter only", "remote only", "tank only", "spares"],
       note="Valleys damp - a dehumidifier pays for itself. Prices dip in spring."),
    _w("Office chairs & desks", "Home & garden",
       "herman miller OR steelcase OR ergonomic office chair OR standing desk",
       "herman miller aeron chair", 200, 45,
       enabled=False, min_price=40,
       exclude=["arm only", "arms only", "base only", "wheels only", "castors", "cylinder",
                "frame only", "top only", "spares"],
       note="Off by default - nearly always collection only, but ex-office Aerons go for a fraction of new."),

    _w("Bikes", "Sport & outdoors",
       "hybrid bike OR mountain bike OR gravel bike OR road bike", "specialized sirrus hybrid bike", 250, 45,
       enabled=False, min_price=60, quality="strict",
       exclude=["frame only", "frameset", "wheel only", "wheels", "forks", "saddle", "pedals",
                "helmet", "stand", "rack", "kids", "childs", "child's", "balance bike",
                "20 inch", "24 inch", "12 inch", "16 inch"],
       note="Off by default - collection only, and stolen bikes are a real risk. Ask for proof of purchase."),
    _w("E-scooters & e-bikes", "Sport & outdoors",
       "xiaomi electric scooter OR pure electric scooter OR e-bike OR electric bike",
       "xiaomi electric scooter pro", 250, 45,
       enabled=False, min_price=60, quality="strict",
       exclude=["battery only", "charger only", "tyre", "tube", "spares", "no battery",
                "kids", "toy", "hoverboard"],
       note="Off by default - e-scooters are still not legal on UK public roads, and battery health is unknowable from a listing."),
    _w("Gym & fitness kit", "Sport & outdoors",
       "adjustable dumbbells OR kettlebell OR concept2 rower OR exercise bike OR olympic barbell",
       "bowflex adjustable dumbbells", 120, 45,
       min_price=20,
       exclude=["single dumbbell", "one dumbbell", "collars only", "mat only", "plates only",
                "handle only", "spares"],
       note="Heavy, so mostly collection - but January resolutions go cheap by March."),
    _w("Camping & hiking", "Sport & outdoors",
       "vango tent OR 4 man tent OR osprey rucksack OR down sleeping bag OR trangia",
       "vango 4 man tent", 80, 45,
       min_price=15,
       exclude=["pegs only", "poles only", "footprint only", "carpet only", "porch only",
                "rain cover only", "spares"],
       note=""),
    _w("Golf clubs", "Sport & outdoors",
       "taylormade OR callaway OR ping driver OR irons set", "taylormade driver", 120, 45,
       enabled=False, min_price=25,
       exclude=["headcover", "head cover only", "grip", "grips", "shaft only", "single iron",
                "cover only", "left handed", "junior"],
       note="Off by default. Left-handed excluded - flip that in Specs & words if you are."),

    _w("Guitars", "Music",
       "fender OR gibson OR epiphone OR yamaha OR squier guitar", "fender player stratocaster", 200, 45,
       enabled=False, min_price=40, quality="strict",
       exclude=["strap", "strings", "case only", "gig bag only", "pickup only", "neck only",
                "body only", "pedal", "toy", "3/4 size", "1/2 size", "junior"],
       note="Off by default. A guitar with a twisted neck is firewood - ask about the neck and action."),
    _w("Keyboards & pianos", "Music",
       "digital piano OR yamaha keyboard OR casio keyboard OR roland keyboard",
       "yamaha p45 digital piano", 200, 45,
       enabled=False, min_price=30, quality="strict",
       exclude=["stand only", "pedal only", "cover only", "adapter only", "toy", "kids",
                "keys only", "dead keys", "sticky keys"],
       note="Off by default - heavy, usually collection."),
    _w("DJ & studio kit", "Music",
       "pioneer dj controller OR focusrite scarlett OR studio monitors OR audio technica mic",
       "pioneer ddj-400", 120, 45,
       enabled=False, min_price=25,
       exclude=JUNK["audio"] + ["stand only", "cable", "cover only", "dust cover", "spares"],
       note="Off by default."),

    _w("Watches - Seiko, Casio, Tissot", "Watches & fashion",
       "seiko OR casio g-shock OR tissot OR citizen watch", "seiko 5 automatic", 90, 45,
       min_price=15, quality="strict",
       exclude=["strap only", "bracelet only", "band only", "link", "links", "box only",
                "bezel only", "dial only", "movement only", "replica", "homage", "fake",
                "not running", "needs battery", "needs service", "parts", "mod"],
       note="Replicas and 'homages' are everywhere - excluded by name, but look at the photos."),
    _w("Trainers", "Watches & fashion",
       "nike OR adidas OR new balance trainers uk 9", "new balance 574 uk 9", 45, 45,
       enabled=False, min_price=10, conditions=["USED", "NEW"],
       exclude=["laces", "insoles", "box only", "kids", "junior", "infant", "replica", "rep",
                "reps", "unauthorised", "custom"],
       note="Off by default, and 'uk 9' is baked into the query - change it to your size in Specs & words."),
    _w("Sunglasses", "Watches & fashion",
       "ray-ban OR oakley sunglasses", "ray-ban wayfarer", 50, 45,
       enabled=False, min_price=10,
       exclude=["case only", "lenses only", "replacement lenses", "arm only", "replica",
                "fake", "style", "inspired"],
       note="Off by default - the replica rate is the highest of anything in here."),

    _w("Pokemon & trading cards", "Collectables",
       "pokemon booster box OR elite trainer box OR pokemon cards sealed",
       "pokemon elite trainer box", 60, 40,
       enabled=False, min_price=10, conditions=["NEW"],
       exclude=["proxy", "custom", "fake", "reprint", "bulk", "random", "mystery", "opened",
                "empty", "resealed", "code cards"],
       note="Off by default - resealed boxes are a known scam. New only, and still look hard."),

    _w("Roof boxes & car kit", "Car",
       "thule roof box OR roof bars OR boot liner OR dash cam hardwire kit", "thule roof box", 80, 45,
       min_price=10,
       exclude=["key only", "keys only", "clips only", "bracket only", "parts", "spares",
                "feet only", "fitting kit only"],
       note="For the Polo. Roof boxes go cheap after the summer holidays."),
]


STARTER_CONFIG = {
    "marketplace": "EBAY_GB",
    "currency": "GBP",
    "poll_interval_minutes": 40,
    "open_dashboard_on_new_hits": False,
    "min_seller_feedback_pct": 90.0,
    "min_seller_feedback_score": 5,
    "baseline_sample_size": 100,
    "baseline_max_age_hours": 12,
    "quality_mode": "balanced",
    "dark": True,
    "global_exclude_terms": DEFAULT_CONFIG["global_exclude_terms"],
    "working_terms": DEFAULT_CONFIG["working_terms"],
    "trusted_conditions": DEFAULT_CONFIG["trusted_conditions"],
    "banned_conditions": DEFAULT_CONFIG["banned_conditions"],
    "import_tells": IMPORT_TELLS,
    "auction_ending_within_hours": 12,
    "refurbished_discount_allowance": 15,
    "cex_grades": DEFAULT_CONFIG["cex_grades"],
    "cex_delivery_charge": DEFAULT_CONFIG["cex_delivery_charge"],
    "cex_local_stores": DEFAULT_CONFIG["cex_local_stores"],
    "local_towns": DEFAULT_CONFIG["local_towns"],
    "shop_cache_hours": 6,
    "cashconverters_pages": 2,
    "hukd_tags": [],
    "sites": dict(DEFAULT_CONFIG["sites"]),
    "watches": WATCH_CATALOGUE,
}


