"""
Other places to look besides eBay's main Buy It Now listings.

Sites fall into two camps, and pretending otherwise only wastes time:

  SEARCHABLE - there is a supported, machine-readable way in. Right now that
               means eBay and its Refurbished and auction listings, which the
               engine queries directly and scores like everything else.

  QUICK LINK - no usable public API. Rather than scrape (which breaks within
               weeks, gets the machine blocked, and breaches their terms), the
               app builds the equivalent search URL and opens it in the browser.
               Less clever, but it works today and it works next year.

The list below is curated by reputation, not by what is technically reachable.
A site that mostly hosts scams is not a favour to anyone.
"""

from __future__ import annotations

import re
import urllib.parse


def _clean(query: str) -> str:
    """Turn an eBay-style query into something a normal search box understands."""
    q = re.sub(r"\s+OR\s+", " ", query, flags=re.I)
    q = re.sub(r"[^\w\s.+-]", " ", q)
    return re.sub(r"\s+", " ", q).strip()


# Ordered best-reputation first. `caution` shows as a warning in the app: these
# are worth searching, but they are also where the scams are.
QUICK_LINKS = [
    {
        "name": "Back Market",
        "why": "Graded refurbs, 12-month minimum warranty and a 30-day return - "
               "the safest place on this list",
        "url": lambda q, cap: "https://www.backmarket.co.uk/en-gb/search?q="
                              + urllib.parse.quote_plus(_clean(q)),
    },
    {
        "name": "CeX",
        "why": "Tested stock with a 2-year warranty and high-street returns",
        "url": lambda q, cap: "https://uk.webuy.com/search?stext="
                              + urllib.parse.quote_plus(_clean(q)),
    },
    {
        "name": "musicMagpie",
        "why": "Refurbished tech with a 12-month warranty; owned by AO World "
               "since 2024, so there is a real company behind it",
        "url": lambda q, cap: "https://www.musicmagpie.co.uk/search?q="
                              + urllib.parse.quote_plus(_clean(q)),
    },
    {
        "name": "Amazon Warehouse",
        "why": "Returned and open-box stock, full Amazon returns policy applies",
        "url": lambda q, cap: "https://www.amazon.co.uk/s?k="
                              + urllib.parse.quote_plus(_clean(q))
                              + "&i=warehouse-deals",
    },
    {
        "name": "Cash Converters",
        "why": "High-street pawn stock, tested in store, rarely picked over online",
        "url": lambda q, cap: "https://www.cashconverters.co.uk/search?q="
                              + urllib.parse.quote_plus(_clean(q)),
    },
    {
        "name": "eBay - Buy It Now",
        "why": "The same search on the site itself, newest first",
        "url": lambda q, cap: "https://www.ebay.co.uk/sch/i.html?_nkw="
                              + urllib.parse.quote_plus(_clean(q))
                              + "&LH_BIN=1&LH_PrefLoc=1&_sop=10"
                              + (f"&_udhi={int(cap)}" if cap else ""),
    },
    {
        "name": "eBay - auctions ending",
        "why": "Auctions closing soonest, in the browser",
        "url": lambda q, cap: "https://www.ebay.co.uk/sch/i.html?_nkw="
                              + urllib.parse.quote_plus(_clean(q))
                              + "&LH_Auction=1&LH_PrefLoc=1&_sop=1"
                              + (f"&_udhi={int(cap)}" if cap else ""),
    },
    {
        "name": "Gumtree",
        "why": "Genuine local bargains, but no buyer protection at all - "
               "collect in person, pay in person, never by bank transfer",
        "caution": True,
        "url": lambda q, cap: "https://www.gumtree.com/search?search_category=all"
                              f"&q={urllib.parse.quote_plus(_clean(q))}"
                              + (f"&max_price={int(cap)}" if cap else ""),
    },
    {
        "name": "Facebook Marketplace",
        "why": "Biggest local market by volume, and the highest scam rate of "
               "anywhere here - assume nothing until you have seen it working",
        "caution": True,
        "url": lambda q, cap: "https://www.facebook.com/marketplace/search/?query="
                              + urllib.parse.quote_plus(_clean(q))
                              + (f"&maxPrice={int(cap)}" if cap else ""),
    },
]


def quick_links_for(watch: dict) -> list[dict]:
    query = watch.get("query", "")
    cap = watch.get("max_price")
    out = []
    for site in QUICK_LINKS:
        try:
            out.append({"name": site["name"], "why": site["why"],
                        "caution": bool(site.get("caution")),
                        "url": site["url"](query, cap)})
        except Exception:
            continue
    return out
