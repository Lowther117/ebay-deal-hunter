# eBay Deal Hunter — desktop app

Finds **working** items on eBay UK priced well under what they normally go for, and
shows them in a proper app window on your Mac and your Windows PC.

- **UK only, always** — no import duty, VAT handling or customs fees, ever
- **Condition-aware** — broken, parts-only, iCloud-locked and "case only" listings
  never reach you
- Scores every find against the **median price of comparable live listings**
- **43 watches across 10 categories**, each switchable on or off from the app
- **Three searchable sources**: eBay Buy It Now, eBay Refurbished (warrantied), and
  eBay auctions ending soon
- **Nine one-click sites**, picked for reputation: Back Market, CeX, musicMagpie,
  Amazon Warehouse, Cash Converters and more
- The engine is pure Python standard library — no database server, no cloud, nothing
  leaves your machine except the eBay API calls

---

## Quick start (5 minutes, no build)

You can run it as a script right now on either machine:

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
| `app.py` | `python app.py` | `python3 app.py` | Run from source, no build. Same window, same everything |
| `app.py --browser` | `python app.py --browser` | `python3 app.py --browser` | Same, but in a browser tab. A **Quit** button appears in the toolbar, since there is no window to close |
| `app.py --scan` / `--list` | `python app.py --scan` | `python3 app.py --scan` | Terminal only: scan once and exit, or print every watch. `--demo` fakes the results |
| `app.py selftest` | `"dist\Deal Hunter.exe" selftest` | `"dist/Deal Hunter.app/Contents/MacOS/Deal Hunter" selftest` | What this build can and cannot do; writes `dealhunter-selftest.txt`. The build scripts run it for you |
| `tools/make_preview.py` | `python tools\make_preview.py` | `python3 tools/make_preview.py` | One read-only HTML file of the current findings, to look at on another device |
| `tools/make_icons.py` | run by `build-exe.bat` | run by `build-app.command` | Draws the icon. Needs Pillow; nothing to run by hand |
| `tools/ensure_python.ps1` | run by `build-exe.bat` | — | Finds a real Python or installs one. Nothing to run by hand |
| `dealhunter.spec` | read by `build-exe.bat` | read by `build-app.command` | The PyInstaller definition of the build. Not run directly |
| `build_windows.bat` / `build_mac.sh` | — | — | The old names. They just tell you to use the two above |
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
two scripts only arrange a Python, the dependencies and the signing around it. The old
`build_mac.sh` and `build_windows.bat` now just point at their replacements.

---

## 3. Using it

**Deals** — everything found, best discount first. Filter by category, by watch, by
site, or search. Click any row to open that listing in your browser.

**Watches** — every watch with a toggle, a price cap, a minimum discount and a
condition setting. Changes save immediately. **Scan** runs just that one.
**Search other sites…** opens the same hunt on Back Market, CeX, musicMagpie, Amazon
Warehouse, Cash Converters, Gumtree or Facebook Marketplace.

**Settings** — API keys, which sites to search, scan interval, condition strictness,
seller quality floor, and a live activity log.

**Scan now** runs everything switched on. **Auto** keeps scanning on the interval for
as long as the app is open.

### What it watches

43 watches across 10 categories, 26 on out of the box. `python3 app.py --list` prints
the lot with their current state.

| Category | Watches |
|---|---|
| **Laptops** | Laptops – any brand · MacBook · ThinkPad · Dell business · Gaming *(off)* · Surface & 2-in-1s *(off)* |
| **Audio** | Headphones · Earbuds · Portable & smart speakers · Soundbars · Hi-fi separates *(off)* · Turntables *(off)* · DACs & amps *(off)* |
| **Storage** | SSDs · Hard drives & NAS drives · NAS & external · Memory & RAM *(off)* |
| **PC components** | Graphics cards · Mini PCs & SFF · CPUs · Raspberry Pi & SBCs · Desktop PCs *(off)* · Servers & homelab *(off)* |
| **Displays** | Monitors · Keyboards & mice *(off)* · TVs *(off)* · Projectors *(off)* |
| **Phones & tablets** | iPads & tablets · Smartwatches & fitness · E-readers · Phones *(off)* |
| **Networking** | Networking gear · Smart home |
| **Tools** | Cordless power tools · Nail guns & compressors · Laser levels · Hand & garden *(off)* |
| **Home tech** | Robot vacuums · Coffee machines *(off)* |
| **Cameras** | Dashcams & action cams · Cameras & lenses *(off)* · Drones *(off)* · Retro gaming *(off)* |

Things are off by default for a reason, and each carries a `note` saying why — TVs and
turntables because postage kills them, Phones because of the scam rate, Servers because
they're loud and thirsty. Two were added with the panelling in mind: a second-hand brad
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

CeX was removed in 2.2. Its listings came from the JSON endpoint its own website uses,
which is not a supported public API, and it refused our requests. The CeX *shop* is
still one of the best places to buy tested second-hand kit in the UK, so it stays as a
one-click link — that always works, because it is just a search page.

**Quick links** — Gumtree, Facebook Marketplace, Shpock, Vinted, Music Magpie, Back
Market, Cash Converters, Amazon Warehouse and Preloved have no usable public API. The app builds the equivalent search URL, with your price cap applied where
the site supports it, and opens it in your browser. Scraping them would break within
weeks, get the machine blocked, and breaches their terms; a link that opens the right
search does neither and never breaks.

No other UK resale site publishes a usable public API — that's the honest reason the
list stops at three rather than a lack of trying. If one ever does, adding it means
writing a single function that returns records in the standard shape. Everything else — the UK check, condition gates,
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

**Rate limited** — raise the scan interval in Settings. 20 minutes across ~17 watches
is well under eBay's 5,000 calls a day.

---

## What's in the box

```
app.py                  entry point - window, CLI, self-test, crash net
dealhunter/
  core.py               the engine: search, condition judging, scoring, storage
  sites.py              the curated quick-link list for other sites
  server.py             local HTTP server and JSON API
  ui.py                 the interface, one self-contained page
  paths.py              per-platform data folder
tools/
  make_icons.py         draws the app icon
  make_preview.py       exports a read-only HTML snapshot of the dashboard
  ensure_python.ps1     finds or installs a Python on Windows
dealhunter.spec         PyInstaller build definition (both platforms)
build-app.command       double-click Mac build -> dist/Deal Hunter.app
build-exe.bat           double-click Windows build -> dist\Deal Hunter.exe
```

---

*Built for my own use, in collaboration with AI (Anthropic's Claude). I described the problems, made the decisions and tested the results; Claude wrote much of the code. Shared as-is — a personal fix, not a product. No support and no warranty.*
