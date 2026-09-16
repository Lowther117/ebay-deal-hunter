# eBay Deal Hunter — desktop app

Finds **working** items on eBay UK priced well under what they normally go for, and
shows them in a proper app window on your Mac and your Windows PC.

- **UK only, always** — no import duty, VAT handling or customs fees, ever
- **Condition-aware** — broken, parts-only, iCloud-locked and "case only" listings
  never reach you
- Scores every find against the **median price of comparable live listings**
- **68 watches across 17 categories** — tech, games, home, garden, sport, music, watches,
  collectables and the car — each switchable on or off from the app
- **Seven searchable sources**: eBay Buy It Now, eBay Refurbished, eBay auctions
  ending soon, CeX, Back Market, musicMagpie and Cash Converters — the shops all
  tested, graded stock with warranties or a returns policy
- **Two deal feeds** on their own tab: HotUKDeals and r/hardwareswapuk, matched
  against your watches
- **Ten one-click sites** for everything that can't be searched: Vinted, Gumtree,
  Facebook Marketplace, Amazon Warehouse and the rest
- The engine is pure Python standard library — no database server, no cloud, nothing
  leaves your machine except the searches themselves

---

## Quick start (5 minutes, no build)

You can run it as a script right now on either machine - double-click
**`run.command`** (Mac) or **`run.bat`** (Windows), which set up their own
`.venv` the first time, or from a terminal:

```bash
python3 app.py
```

The window opens, and **Load demo data** on the Settings tab fills it with examples so
you can see how it works before doing anything else.

To make it a real double-clickable app, see *Building* below.

---

## Which file do I use?

| File | Windows | Mac | What it is |
|---|---|---|---|
| `build-exe.bat` | double-click | — | Builds `dist\Deal Hunter.exe`. Finds or installs Python, then does everything else |
| `build-app.command` | — | double-click | Builds `dist/Deal Hunter.app`. Needs a Homebrew or python.org Python |
| `dist\Deal Hunter.exe` / `dist/Deal Hunter.app` | double-click | double-click | The finished app. Drag the .app to Applications if you like |
| `run.bat` / `run.command` | double-click | double-click | Run from source, no build. Sets up its own `.venv` the first time (installing Python on Windows if needed) |
| `app.py` | `python app.py` | `python3 app.py` | The same, from a terminal with your own Python. Same window, same everything |
| `app.py --browser` | `python app.py --browser` | `python3 app.py --browser` | Same, but in a browser tab. A **Quit** button appears in the toolbar, since there is no window to close |
| `app.py --scan` / `--list` | `python app.py --scan` | `python3 app.py --scan` | Terminal only: scan once and exit, or print every watch. `--demo` fakes the results |
| `app.py selftest` | `"dist\Deal Hunter.exe" selftest` | `"dist/Deal Hunter.app/Contents/MacOS/Deal Hunter" selftest` | What this build can and cannot do; writes `dealhunter-selftest.txt`. The build scripts run it for you |
| `tools/make_preview.py` | `python tools\make_preview.py` | `python3 tools/make_preview.py` | One read-only HTML file of the current findings, to look at on another device. Same as **Save snapshot** in the app; lands in your *Save to* folder (Downloads by default) |
| `tools/make_icons.py` | run by `build-exe.bat` | run by `build-app.command` | Draws the icon. Needs Pillow; nothing to run by hand |
| `tools/ensure_python.ps1` | run by `build-exe.bat` and `run.bat` | — | Finds a real Python or installs one. Nothing to run by hand |
| `dealhunter.spec` | read by `build-exe.bat` | read by `build-app.command` | The PyInstaller definition of the build - the single build definition, deliberately tracked in git. Not run directly |
| `requirements.txt` | `pip install -r requirements.txt` | `pip3 install -r requirements.txt` | Only for the native window (pywebview) and the icon (Pillow). The engine needs nothing |

---

## 1. Get your free eBay API keys

1. Go to <https://developer.ebay.com> and sign in with your normal eBay account.
2. Join the eBay Developers Program — free, individual account is fine.
3. Open **Application Keysets**.
4. Copy the **App ID (Client ID)** and **Cert ID (Client Secret)** from the
   **Production** keyset. Not Sandbox — Sandbox keys return an empty world.
5. In the app: **Settings → eBay API keys → Save keys**.

No approval wait, no cost. The daily limit is 5,000 calls; this app uses a few hundred.

CeX needs no keys at all. Without eBay keys the app still scans CeX, but the eBay
sources are skipped and CeX finds show *no baseline* — the market comparison comes
from eBay's live listings, so it needs the keys too.

---

## 2. Building the real app

One file to double-click on each machine. Both do the whole job — find or install a
Python, set up a build environment, install what is needed, draw the icon, run
PyInstaller against `dealhunter.spec`, then test what came out before telling you it
worked.

### On the Mac

Double-click **`build-app.command`** in Finder, or run `./build-app.command` in
Terminal. Produces **`dist/Deal Hunter.app`** — drag it to Applications.

The script clears extended attributes and ad-hoc signs the finished app. Without that
step a locally built app is killed the moment you open it on Apple silicon, so this is
not a stage to skip by running PyInstaller by hand.

First launch, macOS will still refuse it once because it isn't signed with a paid
developer certificate (£79/year). Get past it: **right-click the app → Open → Open**,
or System Settings → Privacy & Security → *Open Anyway*. After that it opens normally
forever.

It needs a Homebrew or python.org Python. Apple's `/usr/bin/python3` cannot be packaged
into an app that actually opens, so the script refuses it by name and, if that is all
the Mac has, installs one with Homebrew (installing Homebrew first if needed — that step
asks for your password once). If yours lives somewhere unusual, point the script at it:

```bash
DEALHUNTER_BUILD_PYTHON=/path/to/python3 ./build-app.command
```

### On the Windows PC

Double-click **`build-exe.bat`**. Produces **`dist\Deal Hunter.exe`** — a single file,
no installer. Right-click → Pin to Start if you want it handy.

Python is arranged automatically here: if the script cannot find a working one it
installs it for you (winget first, python.org directly when winget is unwell) — no
manual steps. First launch, SmartScreen will show *"Windows protected your PC"* for the
same unsigned reason. Click **More info → Run anyway**, once.

### When a build goes wrong

- Everything is logged to **`build-mac-log.txt`** / **`build-win-log.txt`** in this folder
- The built app runs its own self-test at the end and writes
  **`dist/dealhunter-selftest.txt`** — Python version, whether the native window
  backend is usable, where the data folder is and whether it can be written to
- If the app ever fails while starting up it leaves **`dealhunter-crash.log`** beside
  itself instead of closing silently

A packaged app has no console, so those three files are the whole story when something
misbehaves — the build scripts say PROBLEMS FOUND rather than pretending a bad build
was a good one. `dealhunter.spec` stays the single definition of what gets built; the
two scripts only arrange a Python, the dependencies and the signing around it.

---

## 3. Using it

**Deals** — everything found, best discount first. Filter by category, by watch, by
site, or search. Click any row to open that listing in your browser.

**Feeds** — HotUKDeals posts and r/hardwareswapuk sales that match a watch. Kept
apart from Deals on purpose: a HotUKDeals price is a new item from a shop, not the
used market, and a Reddit post is a private person with no buyer protection.
Everything that matches is shown, with the discount against the used-market median
where there is one — the feed is for noticing, not gating.

**Watches** — every watch with a toggle, a price cap, a minimum discount and a
condition setting. Changes save immediately. **Scan** runs just that one.
**Specs & words…** opens the spec filters for that watch: brands (any of), CPU
families (any of), minimum RAM and storage in GB, the must-include and must-not-include
word lists, and what to do when a listing doesn't state a spec — keep it with a
*spec unclear* flag (default) or drop it. RAM and storage are read off eBay titles
("16GB RAM 512GB SSD", "8GB/256GB", "RAM: 16GB"); CeX states them as attributes, so
nothing is guessed there. Brand and CPU match whole words in the title or CeX's own
brand and CPU fields. The market baseline is narrowed the same way, so a 16GB watch is
compared against 16GB machines. Each deal row shows the specs it was read as having.
**Search other sites…** opens the same hunt on Back Market, CeX, musicMagpie, Amazon
Warehouse, Cash Converters, Vinted, Gumtree or Facebook Marketplace.

**Settings** — API keys, which sites to search, scan interval, condition strictness,
seller quality floor, where saved files go (**Save to** — your Downloads folder unless
you pick another, with **Browse…** in the app window), a live activity log, and
**Save snapshot**, which writes a read-only HTML copy of the dashboard there.

**Scan now** runs everything switched on. **Auto** keeps scanning on the interval for
as long as the app is open. The window is dark by default; the **Light** / **Dark**
button in the toolbar (or **Ctrl+D**) switches, and the choice is remembered in
`config.json` as `dark`.

### What it watches

68 watches across 17 categories, 39 on out of the box. `python3 app.py --list` prints
the lot with their current state. A newer version's watches are added to an existing
install automatically (your own settings on the old ones are untouched) — the activity
log says which arrived.

| Category | Watches |
|---|---|
| **Laptops** | Laptops - any brand · MacBook (Apple) · ThinkPad · Dell business laptops · Gaming laptops *(off)* · Surface & 2-in-1s *(off)* |
| **Audio** | Headphones - premium · Earbuds · Hi-fi separates *(off)* · Speakers - portable & smart · Soundbars · Turntables & hi-fi kit *(off)* · DACs & headphone amps *(off)* |
| **Storage** | SSDs · Hard drives - desktop & NAS · NAS & external drives · Memory & RAM *(off)* |
| **PC components** | Graphics cards · Mini PCs & SFF desktops · CPUs · Desktop PCs *(off)* · Raspberry Pi & SBCs · Servers & homelab *(off)* |
| **Displays** | Monitors · Keyboards & mice *(off)* · TVs *(off)* · Projectors *(off)* |
| **Phones & tablets** | iPads & tablets · Phones *(off)* · Smartwatches & fitness · E-readers |
| **Networking** | Networking gear · Smart home |
| **Tools** | Cordless power tools · Hand & garden tools *(off)* · Nail guns & compressors · Laser levels & measuring · Socket sets & car tools |
| **Cameras** | Cameras & lenses *(off)* · Retro & handheld gaming *(off)* · Dashcams & action cams · Drones *(off)* |
| **Home tech** | Robot vacuums · Coffee machines *(off)* |
| **Games & media** | Consoles - PS5, Xbox, Switch · Controllers & accessories · Games - Switch & PS5 *(off)* · LEGO sets · Board games *(off)* |
| **Home & garden** | Vacuums - Dyson & Shark · Air fryers & kitchen · Stand mixers & coffee grinders · Pressure washers & mowers · Heaters & dehumidifiers · Office chairs & desks *(off)* |
| **Sport & outdoors** | Bikes *(off)* · E-scooters & e-bikes *(off)* · Gym & fitness kit · Camping & hiking · Golf clubs *(off)* |
| **Music** | Guitars *(off)* · Keyboards & pianos *(off)* · DJ & studio kit *(off)* |
| **Watches & fashion** | Watches - Seiko, Casio, Tissot · Trainers *(off)* · Sunglasses *(off)* |
| **Collectables** | Pokemon & trading cards *(off)* |
| **Car** | Roof boxes & car kit |

Things are off by default for a reason, and each carries a `note` saying why — TVs and
turntables because postage kills them, Phones, Trainers and Sunglasses because of the
scam and replica rate, Bikes because stolen ones are common, Servers because they're
loud and thirsty. The **Trainers** watch has a shoe size baked into its query — change
it under *Specs & words…*, where the search query itself is editable. Two were added with the panelling in mind: a second-hand brad
nailer pays for itself, and a green-beam laser level is worth having (red beams are
excluded — you can't see them indoors).

The two machines don't share anything — each keeps its own watches, database and keys.
That's usually what you want; if not, copy `config.json` between the data folders shown
at the bottom of Settings.

---

## 4. How it decides something is broken

The part that makes it usable rather than a firehose of smashed screens. Three gates:

1. **eBay's own condition field.** *For parts or not working* is rejected outright.
2. **Title blocklist**, whole-word matched, in three families:
   - dead or dying — *spares, faulty, cracked, no power, water damage, untested, as is*
   - locked and useless — *iCloud locked, activation lock, MDM locked, network locked*
   - not actually the item — *screen only, top case, logic board, empty box, replica*
3. **Positive proof it works** — *fully working, tested and working, boots, refurbished,
   excellent condition*. Negations are handled: "not fully working" doesn't count.

Each listing lands in one of three buckets, and the condition setting decides what
survives:

| Setting | Keeps |
|---|---|
| Strict | only listings that positively claim to work |
| Balanced *(default)* | working + unclear, rejects anything broken |
| Loose | everything not explicitly broken |

Rows show ✓ *says it works* or ? *condition unclear*, with the reason on hover.
Anything from eBay Refurbished skips the guesswork — it's graded and warrantied by
definition, so it is trusted rather than parsed.

---

## 5. UK only — how imports are kept out

Enforced in three places, with no override:

1. The eBay search carries `itemLocationCountry:GB` and `deliveryCountry:GB`.
2. Every result is re-checked against its own location afterwards; anything not `GB`
   is dropped and counted as `non-UK` in the log.
3. A title blocklist catches overseas sellers hiding behind UK-looking listings —
   *import, ships from China, US version, 110v, EU plug, no UK plug, customs*.

The market baseline gets the same treatment, so you're compared against UK prices.

---

## 6. Other sites

Two tiers, because sites genuinely differ:

**Searchable** — the site has a machine-readable endpoint, so its listings appear in
the table beside eBay's, judged and scored identically.

- **eBay UK — Buy It Now** — official API, fully supported, on by default.
- **eBay UK — auctions ending soon** — on by default, same API and keys. Shows only
  auctions closing within the next 12 hours, with the **current bid** rather than the
  start price, because an auction with three days left is priced at nothing and tells
  you nothing. This is where things genuinely go under value — a listing ending at 2am
  on a Tuesday with two bids. The price can still climb before it ends, so treat the
  discount as a starting point rather than a promise. Adjust the window with
  `auction_ending_within_hours` in config.json.
- **eBay UK — Refurbished** — on by default. eBay's own graded programme: Certified,
  Excellent, Very Good and Good. Only qualified sellers and brand outlets can list in
  these conditions, and every item carries a warranty (usually one to two years), so
  the condition guesswork is skipped entirely. Refurbished stock costs more than a
  private used sale, so the discount bar drops 15 points to account for the warranty —
  change that with `refurbished_discount_allowance` in config.json.

- **CeX — online stock** — on by default, back in 2.3. CeX's website searches its
  stock through Algolia, via a proxy on CeX's own domain, using a search-only key
  that every visitor's browser is handed. That key can read the index and nothing
  else, and it doesn't need a login, so the app uses it too — one small request per
  watch. Every box is tested, graded A/B/C and carries CeX's 24-month warranty, so
  it is treated like eBay Refurbished: the condition guesswork is skipped (the
  "not actually the item" words still apply, so chargers and cases for "macbook"
  are dropped), and the discount bar drops by the same 15 points. Only stock that
  can be bought online is shown; if a local store also has it, the row says so.

  Three things to know. It is the site's own search backend, not a published API:
  if CeX rotates the key, **Test** on the Settings tab says "refused", and the new
  values go in `config.json` as `cex_app_id`, `cex_api_key` and `cex_index` (they are
  in the `appsettings` call the site makes on load). CeX charges for delivery and
  the app does not know the rate — set `cex_delivery_charge` in `config.json` if you
  want totals to include it. And `cex_grades` and `cex_local_stores` are there to
  narrow grades or name your stores; the defaults are all three grades, and
  Merthyr Tydfil and Pontypridd.

  The endpoint 2.2 tried is behind Cloudflare and refuses anything that isn't a
  browser. The search proxy is what the site itself talks to for results, and it
  answered a plain request without a referrer, which is why it is worth another go.

- **Back Market** — on by default (2.5). Its site searches an Algolia index through
  a proxy on its own domain, and the proxy answers a plain request with no key at
  all. Fair / Good / Excellent grades, 12-month minimum warranty, 30-day returns.
  Treated like eBay Refurbished for the discount bar.
- **musicMagpie** — on by default (2.5). Its store's search service
  (`search.musicmagpie.co.uk`) returns JSON with every product's condition grades
  and prices; the cheapest grade in stock is shown. 12-month warranty, free delivery.
- **Cash Converters** — on by default (2.5). Its own listing API, newest first.
  Postage is added to the total; collection-only stock is dropped unless the store is
  in `local_towns` (config.json — Merthyr Tydfil, Pontypridd, Aberdare and Cardiff by
  default), because a bargain in Torquay is not a bargain. Condition is the shop's
  2–5 rating where it gives one.

  Shop results are cached in memory for `shop_cache_hours` (6) so an automatic scan
  every 40 minutes doesn't hit three shops with a few hundred requests each time.
  None of these is a published API; each has a Test button, and one that starts
  refusing is skipped for the rest of the scan while the others carry on.

**Feeds** — no search, so each is fetched once per scan and every item matched
against every enabled watch (the watch's query, whole-word, any OR-alternative; then
the watch's own excludes and spec filters). They appear on the **Feeds** tab.

- **HotUKDeals** — on by default. The site's `rss/new` and `rss/hot` feeds; add tag
  feeds (`hukd_tags: ["laptop"]` in config.json) for more depth. Price and merchant
  come from each item's summary.
- **r/hardwareswapuk** — off by default. Reddit's public listing of the subreddit;
  the `[H]` part of a post title is what's for sale and the price is read from the
  body. Posts with no price are skipped. This one could not be verified from the
  machine that built it — press Test; if Reddit is refusing, it stays off.

**Quick links** — Back Market, musicMagpie, Amazon Warehouse, Cash Converters,
Vinted, Gumtree and Facebook Marketplace. The app builds the equivalent search URL,
with your price cap applied where the site supports it, and opens it in your
browser. Scraping them would break within weeks, get the machine blocked, and
breaches their terms; a link that opens the right search does neither and never
breaks.

Two of those were looked at properly for 2.3 and don't qualify: **Vinted**'s
catalogue API sits behind DataDome, which returns a 403 block page to anything
that isn't its own site's JavaScript — even a fetch from a real browser tab on
vinted.co.uk was refused — so a Python client would be blocked within days, and
**Facebook Marketplace** shows nothing without a signed-in account. Both are the
"link that always works" case.

**Gumtree** is Cloudflare-fronted and refuses anything that isn't a browser, so it
stays a link. **Freegle** has an open API for free items near a postcode — a
different kind of thing, not built yet.

If another site turns out to have something usable, adding it means one function in
`dealhunter/sources.py` that returns records in the standard shape and one line in
its `SOURCES` table. Everything else — the UK check, condition gates, spec filters,
scoring, storage, the UI — already handles it.

---

## 7. Running from the terminal

Useful for a scheduled scan without opening the window:

```bash
python3 app.py --scan                     # scan everything switched on
python3 app.py --scan --watch "ThinkPad"  # just one
python3 app.py --scan --group Storage     # one category
python3 app.py --list                     # show all watches
python3 app.py --browser                  # skip the native window
```

macOS, scan every 30 minutes in the background:

```bash
crontab -e
*/30 * * * * cd ~/Projects/ebay-deal-hunter && /usr/bin/python3 app.py --scan
```

Windows: Task Scheduler → Create Basic Task → Daily, repeat every 30 minutes →
Start a program → `pythonw.exe`, arguments `app.py --scan`, start in the app folder.

---

## Where things live

| | macOS | Windows |
|---|---|---|
| Config, database, keys, log | `~/Library/Application Support/eBay Deal Hunter` | `%APPDATA%\eBay Deal Hunter` |

Deleting that folder resets everything. The keys file is written owner-readable only.
The app's window talks to a server bound to `127.0.0.1` and every request carries a
token generated fresh at startup, so nothing else on the machine — or the network — can
reach it.

---

## Troubleshooting

**"Could not get an eBay token (HTTP 401)"** — Sandbox keys. Use the Production keyset.

**Nothing found** — caps too tight or the discount threshold too high. Loosen
`Max £` first, then drop `Under mkt %` to 25. Then read the activity log:

```
[eBay refurb] 12 kept | 47 rejected on condition | 9 non-UK | 3 new
```

A big *rejected on condition* number means the query is pulling in parts listings —
tighten it, or relax that watch from Strict to Balanced. A big *non-UK* number means
the filter is doing its job.

**"only N clean comparables — skipping score"** — that watch's baseline query is too
narrow or too odd. It should read like a title a normal seller would write.

**Window doesn't open, app quits immediately** — run `python3 app.py --browser` from a
terminal in the app folder and read the error. It falls back to your browser rather
than failing outright, so this should be rare. In the browser there is no window to
close, so a **Quit** button appears in the toolbar — use that to stop it.

**Window shows "Starting…" and nothing else** — it will now say why in the status
line. Usually a typo in a hand-edited `config.json`; the message names the file.

**"Network problem reaching eBay"** — the scan stops at the first watch rather than
timing out on every one; it retries each call once first. Auto will try again on the
next interval.

**Rate limited** — raise the scan interval in Settings. Each watch costs about three
eBay calls per scan (the market median is cached for 12 hours), so 39 watches on is
roughly 120 calls a scan: every 40 minutes is about 4,300 a day, under the 5,000 limit;
every 20 minutes is not. Turn off what you don't care about, or lengthen the interval.
CeX calls don't count against eBay's limit.

**"CeX search refused the request (HTTP 403)"** — either CeX has rotated its search
key (see section 6 for where the new one lives) or its proxy has started refusing
non-browser requests. The scan carries on with eBay; CeX is just skipped until it
works again.

---

## What's in the box

```
app.py                  entry point - window, CLI, self-test, crash net
dealhunter/
  core.py               the engine: search, condition judging, scoring, storage
  sources.py            Back Market, musicMagpie, Cash Converters, HotUKDeals, Reddit
  sites.py              the curated quick-link list for other sites (CeX search itself is in core.py)
  server.py             local HTTP server and JSON API
  ui.py                 the interface, one self-contained page
  theme.py              the light and dark palettes (shared with my other apps)
  paths.py              per-platform data folder
tools/
  make_icons.py         draws the app icon
  make_preview.py       exports a read-only HTML snapshot of the dashboard
  ensure_python.ps1     finds or installs a Python on Windows
dealhunter.spec         PyInstaller build definition (both platforms)
build-app.command       double-click Mac build -> dist/Deal Hunter.app
build-exe.bat           double-click Windows build -> dist\Deal Hunter.exe
run.command             run from source on the Mac (makes its own .venv)
run.bat                 run from source on Windows (makes its own .venv)
```

---

*Built for my own use, in collaboration with AI (Anthropic's Claude). I described the problems, made the decisions and tested the results; Claude wrote much of the code. Shared as-is — a personal fix, not a product. No support and no warranty.*
