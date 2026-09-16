"""
The other places the app can search, beyond eBay and CeX.

Every function here returns records in the same shape core.normalise() makes,
so the UK check, condition gates, spec filters, scoring and storage in
core.process_records() apply unchanged. Two kinds:

  SHOPS  - Back Market, musicMagpie, Cash Converters. Searched per watch, like
           CeX, through the endpoints their own websites use (all answered a
           plain request with no key or login in September 2026). Tested,
           graded stock with a returns policy, so they are treated like eBay
           Refurbished: condition trusted, discount bar lowered by the
           refurbished allowance.

  FEEDS  - HotUKDeals (RSS) and r/hardwareswapuk (Reddit's public JSON). There
           is no search, so each feed is fetched once per scan and every item
           is matched against every enabled watch. They land on the Feeds tab
           rather than in the main table: a HotUKDeals post is a new-item
           price, not a used listing, and a Reddit post is a person, not a
           shop.

Shop results are cached in memory for `shop_cache_hours` (default 6), so an
automatic scan every 40 minutes does not hit three shops with a few hundred
requests each time - they only change slowly.

None of these is a published API. If one changes shape, its Test button on
the Settings tab says so, and that source is skipped until it is fixed -
nothing else in the app is affected.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from xml.etree import ElementTree

from .core import (CEX_USER_AGENT, CexError, EbayError, _open, cex_queries, money,
                   parse_specs, title_has_all)

BROWSER_HEADERS = {
    "User-Agent": CEX_USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
}


class SourceError(CexError):
    """Same semantics as CexError: `fatal` means skip this source for the rest
    of the scan rather than failing on every watch."""


def _get_json(url: str, *, data: bytes | None = None, headers: dict | None = None,
              label: str = "site", timeout: int = 30):
    req = urllib.request.Request(url, data=data, headers={**BROWSER_HEADERS, **(headers or {})})
    try:
        return _open(req, timeout=timeout, label=label)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise SourceError(f"{label} refused the request (HTTP {exc.code}): {detail}",
                          code=exc.code, fatal=exc.code in (401, 403, 429)) from exc
    except EbayError as exc:
        raise SourceError(str(exc), fatal=exc.fatal) from exc


def _get_text(url: str, *, label: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={**BROWSER_HEADERS,
                                               "Accept": "application/rss+xml, text/xml, */*"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise SourceError(f"{label} refused the request (HTTP {exc.code}).",
                              code=exc.code, fatal=exc.code in (401, 403, 429)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == 2:
                raise SourceError(f"Network problem reaching {label}: "
                                  f"{getattr(exc, 'reason', exc)}", fatal=True) from exc
            time.sleep(2)


def _base_record(item_id: str, title: str, price: float, url: str, *, shipping: float = 0.0,
                 condition: str, image: str = "", seller: str, location: str = "GB",
                 why: str, categories: str = "", specs: dict | None = None,
                 trusted: bool = True) -> dict:
    price = money(price)
    shipping = money(shipping)
    return {
        "country": "GB", "bid_count": 0, "is_auction": False, "ends": "",
        "item_id": item_id, "title": title.strip(), "price": price, "shipping": shipping,
        "total": round(price + shipping, 2), "currency": "GBP",
        "free_shipping": shipping == 0.0, "condition": condition, "url": url,
        "image": image, "seller_name": seller, "seller_pct": 100.0 if trusted else 0.0,
        "seller_score": 0, "location": location, "buying_options": "FIXED_PRICE",
        "categories": categories, "trusted_source": trusted, "quality_why": why,
        "specs": specs if specs is not None else parse_specs(title),
    }


def _local(cfg: dict, text: str) -> str:
    towns = cfg.get("local_towns") or cfg.get("cex_local_stores") or []
    return next((t for t in towns if t.lower() in (text or "").lower()), "")


# In-memory cache for shop searches: (source, query, floor, cap) -> (ts, records)
_CACHE: dict[tuple, tuple[float, list[dict]]] = {}


def _cached(source: str, watch: dict, cfg: dict, fetch):
    key = (source, watch.get("query", ""), watch.get("min_price") or 0, watch.get("max_price") or 0)
    ttl = float(cfg.get("shop_cache_hours", 6) or 0) * 3600
    hit = _CACHE.get(key)
    if hit and ttl and time.time() - hit[0] < ttl:
        return [dict(r, specs=dict(r.get("specs") or {})) for r in hit[1]]
    records = fetch()
    _CACHE[key] = (time.time(), records)
    return [dict(r, specs=dict(r.get("specs") or {})) for r in records]


# --------------------------------------------------------------------------- #
# Back Market
# --------------------------------------------------------------------------- #

BACKMARKET_SEARCH = "https://search.backmarket.co.uk/1/indexes/{index}/query"
BACKMARKET_INDEX = "prod_index_backbox_model_price_asc_en-gb"


def search_backmarket(watch: dict, cfg: dict) -> list[dict]:
    """Back Market's Algolia index, via the proxy on its own domain. The proxy
    adds the credentials itself - a request with no key at all is answered."""
    return _cached("backmarket", watch, cfg, lambda: _backmarket(watch, cfg))


def _backmarket(watch: dict, cfg: dict) -> list[dict]:
    index = cfg.get("backmarket_index") or BACKMARKET_INDEX
    numeric = []
    if watch.get("min_price"):
        numeric.append(f"price>={int(watch['min_price'])}")
    if watch.get("max_price"):
        numeric.append(f"price<={int(watch['max_price'])}")
    seen, out = set(), []
    for q in cex_queries(watch["query"]):
        body = json.dumps({"query": q, "hitsPerPage": min(int(watch.get("result_limit", 100)), 200),
                           "distinct": 1, "numericFilters": numeric,
                           "attributesToHighlight": []}).encode("utf-8")
        payload = _get_json(BACKMARKET_SEARCH.format(index=index), data=body,
                            headers={"Content-Type": "application/json",
                                     "Origin": "https://www.backmarket.co.uk",
                                     "Referer": "https://www.backmarket.co.uk/"},
                            label="Back Market")
        hits = payload.get("hits") if isinstance(payload, dict) else None
        if hits is None:
            raise SourceError("Back Market's search gave an unexpected reply.", fatal=True)
        for hit in hits:
            if int(hit.get("stockRaw") or 0) <= 0:
                continue
            lid = str(hit.get("listingID") or hit.get("id") or "")
            if not lid or lid in seen:
                continue
            seen.add(lid)
            link = (hit.get("link_grade_v2") or {}).get("href") or ""
            if link.startswith("/"):
                link = "https://www.backmarket.co.uk" + link
            grade = hit.get("backbox_grade_label") or "Refurbished"
            warranty = int(hit.get("warranty") or 0) or 12
            rec = _base_record(
                f"bm-{lid}", hit.get("title") or "", hit.get("price") or 0, link,
                condition=f"Back Market - {grade}", image=hit.get("image1") or "",
                seller="Back Market", location="Back Market (UK delivery)",
                why=f"{grade} - Back Market refurbished, {warranty}-month warranty, 30-day returns",
                categories=hit.get("category_3") or "")
            if hit.get("brand_clean"):
                rec["specs"]["brand"] = str(hit["brand_clean"])
            out.append(rec)
        time.sleep(0.2)
    return out


# --------------------------------------------------------------------------- #
# musicMagpie
# --------------------------------------------------------------------------- #

MUSICMAGPIE_SEARCH = "https://search.musicmagpie.co.uk/api//search"
MUSICMAGPIE_PRODUCT = "https://www.musicmagpie.co.uk/store/products/{slug}/"
MUSICMAGPIE_IMAGES = "https://www.musicmagpie.co.uk/store"


def search_musicmagpie(watch: dict, cfg: dict) -> list[dict]:
    """The search service behind the musicMagpie store. Each product carries
    its variants (one per condition grade); the cheapest one in stock wins."""
    return _cached("musicmagpie", watch, cfg, lambda: _musicmagpie(watch, cfg))


def _musicmagpie(watch: dict, cfg: dict) -> list[dict]:
    seen, out = set(), []
    cap = watch.get("max_price")
    floor = watch.get("min_price") or 0
    for q in cex_queries(watch["query"]):
        url = MUSICMAGPIE_SEARCH + "?" + urllib.parse.urlencode(
            {"Query": q, "MaxResults": min(int(watch.get("result_limit", 100)), 100)})
        payload = _get_json(url, label="musicMagpie",
                            headers={"Origin": "https://www.musicmagpie.co.uk",
                                     "Referer": "https://www.musicmagpie.co.uk/store/"})
        docs = payload.get("docs") if isinstance(payload, dict) else None
        if docs is None:
            raise SourceError("musicMagpie's search gave an unexpected reply.", fatal=True)
        for doc in docs:
            pid = str(doc.get("id") or "")
            if not pid or pid in seen:
                continue
            best = None
            for v in doc.get("variants") or []:
                if not v.get("in_stock") or int(v.get("total_on_hand") or 0) <= 0:
                    continue
                price = money(v.get("price"))
                if price <= 0 or (cap and price > cap) or price < floor:
                    continue
                if best is None or price < best[0]:
                    grade = next((o.get("name") for o in v.get("option_values") or []
                                  if o.get("option_type_name") == "condition"), "") or ""
                    best = (price, grade)
            if best is None:
                continue
            seen.add(pid)
            images = (doc.get("master") or {}).get("images") or []
            image = images[0].get("small_url", "") if images else ""
            if image.startswith("/"):
                image = MUSICMAGPIE_IMAGES + image
            grade = (best[1].replace("_", " ").title() or "Refurbished")
            props = {p.get("property_name"): p.get("value") for p in doc.get("product_properties") or []}
            rec = _base_record(
                f"mm-{pid}", doc.get("name") or "", best[0],
                MUSICMAGPIE_PRODUCT.format(slug=doc.get("slug") or pid),
                condition=f"musicMagpie - {grade}", image=image, seller="musicMagpie",
                location="musicMagpie (free UK delivery)",
                why=f"{grade} - musicMagpie refurbished, 12-month warranty")
            if props.get("Brand Name"):
                rec["specs"]["brand"] = str(props["Brand Name"])
            out.append(rec)
        time.sleep(0.2)
    return out


# --------------------------------------------------------------------------- #
# Cash Converters
# --------------------------------------------------------------------------- #

CASHCONVERTERS_SEARCH = "https://www.cashconverters.co.uk/c3api/search/results"
CASHCONVERTERS_SITE = "https://www.cashconverters.co.uk"


def search_cashconverters(watch: dict, cfg: dict) -> list[dict]:
    """Cash Converters' own listing API - 24 a page, newest first. Store stock
    marked collection-only is skipped unless the store is one of your
    `local_towns`, because a bargain in Torquay is not a bargain."""
    return _cached("cashconverters", watch, cfg, lambda: _cashconverters(watch, cfg))


def _cashconverters(watch: dict, cfg: dict) -> list[dict]:
    seen, out = set(), []
    cap = watch.get("max_price")
    floor = watch.get("min_price") or 0
    pages = int(cfg.get("cashconverters_pages", 2) or 2)
    for q in cex_queries(watch["query"]):
        for page in range(1, pages + 1):
            url = CASHCONVERTERS_SEARCH + "?" + urllib.parse.urlencode(
                {"Sort": "newest", "page": page, "query": q})
            payload = _get_json(url, label="Cash Converters",
                                headers={"Referer": CASHCONVERTERS_SITE + "/shop"})
            value = (payload or {}).get("Value") if isinstance(payload, dict) else None
            if not isinstance(value, dict):
                raise SourceError("Cash Converters' search gave an unexpected reply.", fatal=True)
            items = ((value.get("ProductList") or {}).get("ProductListItems")) or []
            for it in items:
                code = str(it.get("Code") or "")
                if not code or code in seen:
                    continue
                price = money(it.get("Sp"))
                if price <= 0 or (cap and price > cap) or price < floor:
                    continue
                store = it.get("StoreNameWithState") or ""
                label = (it.get("ShippingLabel") or "").lower()
                local = _local(cfg, store)
                if "pickup" in label and not local:
                    continue
                seen.add(code)
                shipping = 0.0 if ("free" in label or "pickup" in label) else money(it.get("ShippingCost"))
                cond = str(it.get("Condition") or "")
                cond_txt = f"condition {cond}/5" if cond.isdigit() and cond != "0" else "condition not stated"
                rec = _base_record(
                    f"cc-{code}", it.get("Title") or "", price,
                    CASHCONVERTERS_SITE + (it.get("Url") or ""), shipping=shipping,
                    condition=f"Cash Converters - {cond_txt}",
                    image=it.get("AbsoluteImageUrl") or "", seller="Cash Converters",
                    location=f"Cash Converters {store}" + (" - local, can collect" if local else ""),
                    why=f"Cash Converters shop stock, {cond_txt}, tested in store, returns policy applies",
                    categories=it.get("ItemType") or "")
                brand = str(it.get("Brand") or "")
                if brand and brand.lower() not in ("macbook", "unbranded", "other"):
                    rec["specs"]["brand"] = brand
                out.append(rec)
            if len(items) < 24:
                break
            time.sleep(0.3)
    return out


# --------------------------------------------------------------------------- #
# feeds: fetched once per scan, matched against every watch
# --------------------------------------------------------------------------- #

PRICE_RE = re.compile(r"£\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")


def _price_in(text: str) -> float:
    m = PRICE_RE.search(text or "")
    return money(m.group(1).replace(",", "")) if m else 0.0


HUKD_FEEDS = ["https://www.hotukdeals.com/rss/new", "https://www.hotukdeals.com/rss/hot"]


def fetch_hotukdeals(cfg: dict) -> list[dict]:
    """HotUKDeals' RSS. Each item's description opens with '<strong>£price -
    merchant</strong>' and a thumbnail, which is all that's needed. Extra
    feeds can be added as `hukd_tags` in config.json (e.g. "laptop")."""
    feeds = list(cfg.get("hukd_feeds") or HUKD_FEEDS)
    for tag in cfg.get("hukd_tags") or []:
        feeds.append(f"https://www.hotukdeals.com/rss/tag/{urllib.parse.quote(str(tag))}")
    seen, out = set(), []
    for url in feeds:
        xml = _get_text(url, label="HotUKDeals")
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            raise SourceError(f"HotUKDeals feed wasn't XML ({exc}) - it may be blocking "
                              "non-browser requests.", fatal=True) from exc
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            title = html.unescape(item.findtext("title") or "").strip()
            if not link or not title:
                continue
            m = re.search(r"-(\d+)/?$", link)
            did = m.group(1) if m else link
            if did in seen:
                continue
            seen.add(did)
            desc = html.unescape(item.findtext("description") or "")
            price = _price_in(desc)
            mm = re.search(r"<strong>[^<]*?-\s*([^<]+)</strong>", desc)
            merchant = mm.group(1).strip() if mm else ""
            img = re.search(r'<img[^>]+src="([^"]+)"', desc)
            rec = _base_record(
                f"hukd-{did}", title, price, link,
                condition="New - " + (merchant or "deal"), image=img.group(1) if img else "",
                seller=merchant or "HotUKDeals",
                location=f"HotUKDeals - {merchant}" if merchant else "HotUKDeals",
                why="a community-posted deal on a new item; the price is what the poster saw",
                categories=item.findtext("category") or "")
            out.append(rec)
        time.sleep(0.3)
    return out


REDDIT_HWS = "https://www.reddit.com/r/hardwareswapuk/new.json?limit=100&raw_json=1"
REDDIT_UA = "ebay-deal-hunter/2.5 (personal desktop app; read-only)"


def fetch_reddit_hws(cfg: dict) -> list[dict]:
    """r/hardwareswapuk through Reddit's public JSON. Posts look like
    '[UK-CDF] [H] ThinkPad T480 [W] PayPal' - the [H] part is what is for
    sale; the price is usually in the body. Posts with no price are skipped
    (they can't be scored). No buyer protection here - it's a person."""
    url = cfg.get("reddit_hws_url") or REDDIT_HWS
    payload = _get_json(url, headers={"User-Agent": REDDIT_UA, "Accept": "application/json"},
                        label="Reddit")
    children = (((payload or {}).get("data") or {}).get("children")) if isinstance(payload, dict) else None
    if children is None:
        raise SourceError("Reddit gave an unexpected reply - it may be blocking this client.",
                          fatal=True)
    out = []
    for child in children:
        d = child.get("data") or {}
        title = html.unescape(d.get("title") or "")
        if d.get("stickied") or "[h]" not in title.lower():
            continue
        flair = (d.get("link_flair_text") or "").lower()
        if any(w in flair for w in ("closed", "sold", "buying", "wanted")):
            continue
        have = re.search(r"\[h\](.*?)(\[w\]|$)", title, flags=re.I | re.S)
        have_txt = (have.group(1) if have else title).strip(" -:")
        if not have_txt or re.fullmatch(r"(paypal|cash|bank transfer|money|£|local cash)+[\s/,&+]*",
                                        have_txt, re.I):
            continue                     # they *have* money and *want* an item
        body = html.unescape(d.get("selftext") or "")
        price = _price_in(body) or _price_in(title)
        if price <= 0:
            continue
        loc = re.match(r"\[([A-Z]{2,3}-[A-Z0-9]+)\]", title)
        thumb = d.get("thumbnail") or ""
        if not thumb.startswith("http"):
            thumb = ""
        rec = _base_record(
            f"rhws-{d.get('id')}", have_txt, price,
            "https://www.reddit.com" + (d.get("permalink") or ""),
            condition="Used - private seller", image=thumb, seller=f"u/{d.get('author', '')}",
            location=f"r/hardwareswapuk {loc.group(1) if loc else ''}".strip(),
            why="a private sale on Reddit - no buyer protection; pay by PayPal Goods & Services only",
            trusted=False)
        rec["no_feedback"] = True
        out.append(rec)
    return out


def match_feed_to_watches(records: list[dict], watches: list[dict]) -> dict[str, list[dict]]:
    """Give each feed item to every enabled watch whose query it satisfies.

    A watch query like 'thinkpad t480 OR t490' matches when all the words of
    any one alternative appear in the title, whole-word. Global excludes and
    the watch's own spec/word filters are applied later by process_records.
    """
    per_watch: dict[str, list[dict]] = {}
    for watch in watches:
        alts = [a.split() for a in cex_queries(watch["query"])]
        hits = [dict(rec, specs=dict(rec.get("specs") or {}))
                for rec in records
                if any(title_has_all(rec["title"], words) for words in alts if words)]
        if hits:
            per_watch[watch["name"]] = hits
    return per_watch


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #

# key -> (label, kind, function). kind: "shop" searches per watch; "feed" is
# fetched once per scan and matched. Order is the order on the Settings tab.
SOURCES = {
    "backmarket":     ("Back Market",      "shop", search_backmarket),
    "musicmagpie":    ("musicMagpie",      "shop", search_musicmagpie),
    "cashconverters": ("Cash Converters",  "shop", search_cashconverters),
    "hukd":           ("HotUKDeals",       "feed", fetch_hotukdeals),
    "reddit_hws":     ("r/hardwareswapuk", "feed", fetch_reddit_hws),
}

FEED_SOURCE_LABELS = [label for label, kind, _ in SOURCES.values() if kind == "feed"]


def test_source(key: str, cfg: dict) -> tuple[bool, str]:
    """One live call, for the Settings tab's Test button. Bypasses the cache."""
    label, kind, fn = SOURCES[key]
    if kind == "shop":
        probe = {"name": "test", "query": "macbook", "max_price": 5000, "min_price": 0,
                 "result_limit": 5}
        found = fn(probe, dict(cfg, shop_cache_hours=0))
        if not found:
            return False, f"{label} answered, but the test search found nothing in stock."
        return True, (f"Connected - {len(found)} test results, e.g. "
                      f"{found[0]['title'][:50]} at £{found[0]['total']:.2f}")
    found = fn(cfg)
    if not found:
        return False, f"{label} answered, but nothing came back."
    return True, f"Connected - {len(found)} items in the feed, newest: {found[0]['title'][:50]}"
