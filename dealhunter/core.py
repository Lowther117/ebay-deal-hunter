"""
eBay Deal Hunter - scanning engine.

Pure standard library. Knows nothing about the GUI: it finds listings, judges
their condition, scores them against the UK market, and stores the results.
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

from .paths import CONFIG_PATH, DB_PATH, TOKEN_CACHE

EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"

USER_AGENT = "ebay-deal-hunter/2.0 (personal use)"

# Replaced by the app so log lines reach the UI as well as the console.
LOG_SINK = None


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
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
    "poll_interval_minutes": 20,
    "open_dashboard_on_new_hits": False,
    "min_seller_feedback_pct": 90.0,
    "min_seller_feedback_score": 5,
    "baseline_sample_size": 100,
    "baseline_max_age_hours": 12,
    "listing_expiry_days": 7,
    "quality_mode": "balanced",  # strict | balanced | loose
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
    "sites": {
        "ebay": True,
        "ebay_refurbished": True,
        "ebay_auctions": True,
    },
    "watches": [],
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log(f"No config.json found at {CONFIG_PATH} - writing a starter one.")
        CONFIG_PATH.write_text(json.dumps(STARTER_CONFIG, indent=2), encoding="utf-8")
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return cfg


# --------------------------------------------------------------------------- #
# eBay API client
# --------------------------------------------------------------------------- #

class EbayError(RuntimeError):
    pass


def is_auth_error(exc: Exception) -> bool:
    """Bad or expired keys - worth stopping the whole scan for."""
    text = str(exc).lower()
    return ("401" in text or "403" in text or "token" in text
            or "invalid_client" in text or "unauthorized" in text)


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
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise EbayError(
                f"Could not get an eBay token (HTTP {exc.code}). "
                f"Check EBAY_CLIENT_ID / EBAY_CLIENT_SECRET are your *production* keys. "
                f"eBay said: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise EbayError(f"Network problem reaching eBay: {exc.reason}") from exc

        self._token = payload["access_token"]
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
                with urllib.request.urlopen(req, timeout=45) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                if exc.code == 429:
                    raise EbayError("eBay rate limit hit - back off and try later.") from exc
                raise EbayError(f"eBay search failed (HTTP {exc.code}): {detail}") from exc
            except urllib.error.URLError as exc:
                raise EbayError(f"Network problem reaching eBay: {exc.reason}") from exc

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
    low = title.lower()
    return all(term.lower().strip() in low for term in required if term.strip())


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
    "ship from china", "from china", "from usa", "from us", "from hong kong",
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
    quality_why   TEXT
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
               bid_count=?, ends=? WHERE item_id=?""",
            (rec["title"], rec["price"], rec["shipping"], rec["total"], rec["condition"],
             rec["seller_pct"], rec["seller_score"], rec["baseline"], rec["discount_pct"],
             ts, rec["flags"], rec.get("quality", ""), rec.get("quality_why", ""),
             rec["url"], rec["image"], int(rec.get("bid_count") or 0),
             rec.get("ends", ""), rec["item_id"]),
        )
        return False

    conn.execute(
        """INSERT INTO items (item_id, watch, grp, source, country, title, price,
           shipping, total, currency, free_shipping, condition, url, image,
           seller_name, seller_pct, seller_score, location, baseline, discount_pct,
           first_seen, last_seen, is_live, flags, quality, quality_why,
           bid_count, ends)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)""",
        (rec["item_id"], rec["watch"], rec.get("group", "Other"),
         rec.get("source", "eBay"), rec.get("country", "GB"), rec["title"], rec["price"], rec["shipping"],
         rec["total"], rec["currency"], int(rec["free_shipping"]), rec["condition"],
         rec["url"], rec["image"], rec["seller_name"], rec["seller_pct"],
         rec["seller_score"], rec["location"], rec["baseline"], rec["discount_pct"],
         ts, ts, rec["flags"], rec.get("quality", ""), rec.get("quality_why", ""),
         int(rec.get("bid_count") or 0), rec.get("ends", "")),
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
    p10 = vals[int(len(vals) * 0.10)]
    p90 = vals[min(len(vals) - 1, int(len(vals) * 0.90))]
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
        if rec["total"] > 0:
            totals.append(rec["total"])

    if len(totals) < 5:
        log(f"  ! baseline for '{name}': only {len(totals)} clean comparables - skipping score")
        return None

    median, p10, p90, n = trimmed_stats(totals)
    save_baseline(conn, name, median, n, p10, p90)
    log(f"  baseline for '{name}': median {cfg['currency']} {median:.2f} from {n} listings")
    return median


def scan_watch(client, conn, watch, cfg) -> tuple[int, int]:
    name = watch["name"]
    excludes = list(cfg["global_exclude_terms"]) + list(watch.get("exclude_terms") or [])
    required = watch.get("require_terms") or []
    min_disc = watch.get("min_discount_pct", 0)
    min_pct = watch.get("min_seller_feedback_pct", cfg["min_seller_feedback_pct"])
    min_score = watch.get("min_seller_feedback_score", cfg["min_seller_feedback_score"])
    mode = watch.get("quality_mode", cfg.get("quality_mode", "balanced"))

    log(f"- {name}: '{watch['query']}' up to {cfg['currency']} {watch.get('max_price', '-')}")
    baseline = compute_baseline(client, conn, watch, cfg, excludes)

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
    for rec in records:
        if not rec.get("item_id"):
            continue

        ok_uk, uk_why = uk_ok(rec, cfg)
        if not ok_uk:
            non_uk += 1
            continue

        if rec.get("trusted_source"):
            # A shop that tests and warranties its stock has already answered
            # the condition question - don't second-guess it on wording alone.
            verdict, why = "working", rec.get("quality_why", f"{source} tested stock")
        else:
            verdict, why = assess_quality(rec, watch, cfg, excludes)
        if not quality_allows(verdict, mode):
            rejected += 1
            continue
        if required and not title_has_all(rec["title"], required):
            continue
        if cap and rec["total"] > cap:
            continue
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
        if rec["seller_score"] < 25:
            flags.append("low-feedback-seller")
        if rec["shipping"] > rec["price"]:
            flags.append("postage-heavy")
        if verdict == "unsure":
            flags.append("condition-unclear")

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
        f"{non_uk} non-UK | {new_hits} new")
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

        client_id, client_secret = credentials()
        if not client_id or not client_secret:
            return {"ok": False, "scanned": 0, "new_hits": 0,
                    "error": "No eBay API keys saved yet - add them in Settings."}
        client = EbayClient(client_id, client_secret, cfg["marketplace"])

        active = [n for n, on in (("Buy It Now", use_ebay),
                                  ("Refurbished", use_refurb),
                                  ("auctions", use_auctions)) if on]
        if not active:
            return {"ok": False, "scanned": 0, "new_hits": 0,
                    "error": "Every source is switched off - turn one on in Settings."}
        total = len(watches)
        log(f"Scanning {total} watch(es), UK only, via {' + '.join(active)}.")

        for i, watch in enumerate(watches, 1):
            if progress:
                progress(i - 1, total, watch["name"])

            try:
                if use_ebay:
                    kept, new = scan_watch(client, conn, watch, cfg)
                    scanned += kept
                    new_hits += new

                # Every source after the first reuses the market median the Buy
                # It Now pass worked out, so it costs one API call, not two.
                baseline = latest_baseline(conn, watch["name"],
                                           cfg["baseline_max_age_hours"])
                if baseline is None and (use_refurb or use_auctions):
                    excludes = (list(cfg["global_exclude_terms"])
                                + list(watch.get("exclude_terms") or []))
                    baseline = compute_baseline(client, conn, watch, cfg, excludes)

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
       require=None, exclude=None, note=""):
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
]


STARTER_CONFIG = {
    "marketplace": "EBAY_GB",
    "currency": "GBP",
    "poll_interval_minutes": 20,
    "open_dashboard_on_new_hits": False,
    "min_seller_feedback_pct": 90.0,
    "min_seller_feedback_score": 5,
    "baseline_sample_size": 100,
    "baseline_max_age_hours": 12,
    "quality_mode": "balanced",
    "global_exclude_terms": DEFAULT_CONFIG["global_exclude_terms"],
    "working_terms": DEFAULT_CONFIG["working_terms"],
    "trusted_conditions": DEFAULT_CONFIG["trusted_conditions"],
    "banned_conditions": DEFAULT_CONFIG["banned_conditions"],
    "import_tells": IMPORT_TELLS,
    "auction_ending_within_hours": 12,
    "refurbished_discount_allowance": 15,
    "sites": {"ebay": True, "ebay_refurbished": True, "ebay_auctions": True},
    "watches": WATCH_CATALOGUE,
}


