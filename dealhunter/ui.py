"""The app's interface, as one self-contained page served from localhost."""

from . import theme

_PAGE = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>eBay Deal Hunter</title>
<style>
  /* House palette (dealhunter/theme.py). Dark is the default; the Light/Dark
     button, Ctrl+D and the saved "dark" setting switch data-theme at runtime. */
  :root, :root[data-theme="dark"] {
    color-scheme: dark;
    __DARK_VARS__
    --shadow: none;
  }
  :root[data-theme="light"] {
    color-scheme: light;
    __LIGHT_VARS__
    --shadow: 0 1px 2px rgba(11,11,11,0.05), 0 8px 24px rgba(11,11,11,0.04);
  }
  ::selection { background: var(--sel); color: var(--text); }

  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 14px; line-height: 1.45; -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1280px; margin: 0 auto; padding: 20px 20px 60px; }

  /* ---- top bar ---- */
  header {
    position: sticky; top: 0; z-index: 20; background: var(--bg);
    border-bottom: 1px solid var(--border); margin: 0 -20px 18px; padding: 14px 20px 0;
  }
  .titlerow { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  h1 { font-size: 18px; margin: 0; letter-spacing: -0.01em; }
  .spacer { flex: 1; }
  .status { color: var(--dim); font-size: 13px; display: flex; align-items: center; gap: 7px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dim); flex: none; }
  .dot.live { background: var(--good); animation: pulse 1.4s ease-in-out infinite; }
  .dot.err { background: var(--bad); }
  @keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: 0.35 } }

  button {
    font-family: inherit; font-size: 13px; cursor: pointer; border-radius: 8px;
    border: 1px solid var(--field-border); background: var(--panel);
    color: var(--text); padding: 7px 13px;
  }
  button:hover:not(:disabled) { border-color: var(--accent); background: var(--sel); }
  button:focus-visible, input:focus-visible, select:focus-visible {
    outline: 2px solid var(--accent); outline-offset: 1px; border-color: var(--accent);
  }
  button:disabled { opacity: 0.5; cursor: default; }
  button.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-text); font-weight: 500; }
  button.primary:hover:not(:disabled) { filter: brightness(1.08); background: var(--accent); color: var(--accent-text); }
  button.danger:hover { border-color: var(--bad); color: var(--bad); }

  .tabs { display: flex; gap: 2px; margin: 14px 0 0; }
  .tab {
    border: none; border-bottom: 2px solid transparent; background: none;
    border-radius: 0; padding: 9px 14px; font-size: 14px; color: var(--dim);
  }
  .tab:hover:not(:disabled) { background: none; color: var(--text); }
  .tab[aria-selected="true"] { color: var(--text); border-bottom-color: var(--accent); font-weight: 500; }

  /* ---- progress ---- */
  .progress { height: 2px; background: var(--border); margin: 0 -20px; }
  .progress > div { height: 100%; background: var(--accent); width: 0; transition: width 0.3s ease; }

  /* ---- tiles ---- */
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .tile { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 13px 15px; box-shadow: var(--shadow); }
  .tile .label { color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  .tile .value { font-size: 26px; font-weight: 600; margin-top: 3px; letter-spacing: -0.02em; }
  .tile .note { color: var(--dim); font-size: 12px; }

  /* ---- controls ---- */
  .controls { display: flex; gap: 9px; flex-wrap: wrap; align-items: center; margin-bottom: 14px; }
  .chip { border-radius: 999px; padding: 5px 13px; }
  .chip[aria-pressed="true"], .chip[aria-pressed="true"]:hover:not(:disabled) {
    background: var(--accent); border-color: var(--accent); color: var(--accent-text); }
  .chip .count { opacity: 0.65; margin-left: 5px; font-variant-numeric: tabular-nums; }
  input[type="search"], input[type="text"], input[type="password"], input[type="number"], select {
    padding: 8px 11px; border-radius: 8px; border: 1px solid var(--field-border);
    background: var(--field); color: var(--field-text); caret-color: var(--accent);
    font-family: inherit; font-size: 13px;
  }
  input::placeholder { color: var(--dim); opacity: 0.8; }
  input[type="search"] { flex: 1; min-width: 180px; }
  select { cursor: pointer; }
  .rowlabel { color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }

  /* ---- table ---- */
  table { width: 100%; border-collapse: separate; border-spacing: 0; background: var(--panel);
          border: 1px solid var(--border); border-radius: 12px; overflow: hidden; box-shadow: var(--shadow); }
  th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
       color: var(--dim); font-weight: 600; padding: 10px 12px;
       border-bottom: 1px solid var(--border); cursor: pointer; white-space: nowrap; user-select: none; }
  th:hover { color: var(--text); }
  th .arrow { opacity: 0.5; font-size: 10px; }
  td { padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  tbody tr:hover { background: var(--hint); }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .meta { color: var(--dim); font-size: 12px; }
  a.title { color: var(--text); text-decoration: none; font-weight: 500; cursor: pointer; }
  a.title:hover { text-decoration: underline; color: var(--accent); }

  .thumb { width: 60px; height: 60px; object-fit: cover; border-radius: 8px;
           border: 1px solid var(--border); background: var(--bg); display: block; cursor: pointer; }
  .thumb.ph { display: flex; align-items: center; justify-content: center; color: var(--dim); font-size: 9px; text-align: center; }

  .bar-wrap { display: flex; align-items: center; gap: 8px; min-width: 130px; }
  .bar-track { flex: 1; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; background: var(--accent); }
  .bar-label { font-variant-numeric: tabular-nums; font-size: 13px; min-width: 40px; text-align: right; }

  .flag { display: inline-block; font-size: 11px; padding: 0 7px; border-radius: 999px; margin-left: 5px;
          border: 1px solid var(--border); color: var(--dim); white-space: nowrap; }
  .flag.warn { border-color: var(--warn); color: var(--warn); }
  .flag.crit { border-color: var(--bad); color: var(--bad); }
  .src { display: inline-block; font-size: 11px; padding: 0 6px; border-radius: 4px; margin-right: 6px;
         border: 1px solid var(--border); color: var(--dim); }
  .src.ebayauction { border-color: var(--warn); color: var(--warn); }
  .src.ebayrefurb { border-color: var(--good); color: var(--good); }
  .src.cex { border-color: var(--bad); color: var(--bad); }
  .src.backmarket, .src.musicmagpie, .src.cashconverters { border-color: var(--good); color: var(--good); }
  .src.hotukdeals, .src.rhardwareswapuk { border-color: var(--warn); color: var(--warn); }

  /* ---- cards / panels ---- */
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
          padding: 15px 17px; box-shadow: var(--shadow); margin-bottom: 12px; }
  .card h3 { margin: 0 0 3px; font-size: 14px; font-weight: 600; }
  .card .cap { color: var(--dim); font-size: 12px; margin-bottom: 10px; }
  .charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: 12px; margin-top: 22px; }
  .empty { padding: 44px 20px; text-align: center; color: var(--dim); }

  /* ---- watches ---- */
  .wgroup { margin-bottom: 8px; }
  .wgroup > h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;
                 color: var(--dim); margin: 20px 0 8px; }
  .wrow { display: grid; grid-template-columns: 44px 1fr auto; gap: 12px; align-items: start;
          padding: 12px 14px; border-bottom: 1px solid var(--border); }
  .wrow:last-child { border-bottom: none; }
  .wname { font-weight: 500; }
  .wquery { color: var(--dim); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-word; }
  .wnote { color: var(--dim); font-size: 12px; margin-top: 3px; }
  .wfields { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
  .wfields label { font-size: 11px; color: var(--dim); display: flex; flex-direction: column; gap: 3px; }
  .wfields input, .wfields select { width: 92px; }

  .toggle { position: relative; width: 38px; height: 22px; flex: none; padding: 0; border-radius: 999px;
            background: var(--border); border: 1px solid var(--border); transition: background 0.15s; }
  .toggle::after { content: ""; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px;
                   border-radius: 50%; background: var(--text); box-shadow: 0 1px 2px rgba(0,0,0,0.25);
                   transition: transform 0.15s; }
  .toggle[aria-pressed="true"], .toggle[aria-pressed="true"]:hover { background: var(--accent); border-color: var(--accent); }
  .toggle[aria-pressed="true"]::after { transform: translateX(16px); background: var(--accent-text); }

  .links { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
  .specs { display: none; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px;
           margin-top: 10px; padding: 12px; border: 1px solid var(--border); border-radius: 10px;
           background: var(--bg); }
  .specs.open { display: grid; }
  .specs label { font-size: 11px; color: var(--dim); display: flex; flex-direction: column; gap: 3px; }
  .specs input, .specs select { width: 100%; }
  .specs .wide { grid-column: 1 / -1; }
  .specs .hint { grid-column: 1 / -1; font-size: 12px; color: var(--dim); }
  .spec { color: var(--dim); }
  .linkbtn { font-size: 12px; padding: 5px 11px; }
  .linkbtn.caution { border-color: var(--warn); color: var(--warn); }

  /* ---- settings ---- */
  .field { display: flex; flex-direction: column; gap: 5px; margin-bottom: 14px; max-width: 460px; }
  .field label { font-size: 13px; font-weight: 500; }
  .field .hint { color: var(--dim); font-size: 12px; }
  .ok { color: var(--good); font-size: 13px; }
  .err { color: var(--bad); font-size: 13px; }
  pre.log { background: var(--code); border: 1px solid var(--border); border-radius: 8px;
            padding: 12px; font-size: 12px; max-height: 300px; overflow: auto; margin: 0;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; }
  .banner { border-radius: 10px; padding: 12px 15px; margin-bottom: 14px; font-size: 13px;
            border: 1px solid var(--warn); background: var(--hint); }
  .banner.bad { border-color: var(--bad); }
  footer { margin-top: 28px; color: var(--dim); font-size: 12px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="titlerow">
      <h1>eBay Deal Hunter</h1>
      <span class="status"><span class="dot" id="dot"></span><span id="statusText">Starting…</span></span>
      <span class="spacer"></span>
      <button id="btnScan" class="primary">Scan now</button>
      <button id="btnAuto" class="chip" aria-pressed="false">Auto</button>
      <button id="btnTheme" title="Switch between light and dark (Ctrl+D)">Light</button>
      <button id="btnQuit" class="danger" hidden title="Stop the app - it has no window of its own to close">Quit</button>
    </div>
    <div class="tabs" role="tablist">
      <button class="tab" role="tab" data-tab="deals" aria-selected="true">Deals</button>
      <button class="tab" role="tab" data-tab="feeds" aria-selected="false">Feeds</button>
      <button class="tab" role="tab" data-tab="watches" aria-selected="false">Watches</button>
      <button class="tab" role="tab" data-tab="settings" aria-selected="false">Settings</button>
    </div>
    <div class="progress"><div id="progBar"></div></div>
  </header>

  <div id="banner"></div>

  <section id="panel-deals">
    <div class="card" id="feedNote" hidden>
      <h3>Deal feeds</h3>
      <div class="cap">HotUKDeals posts and r/hardwareswapuk sales that match a watch. These are not
        the used market: a HotUKDeals price is a new item from a shop, and a Reddit post is a private
        person with no buyer protection. Everything matching is shown — the discount figure, where
        there is one, is against the used-market median. Which feeds run is set under Settings.</div>
    </div>
    <div class="tiles" id="tiles"></div>
    <div class="controls">
      <span class="rowlabel">Category</span><span id="groupChips" style="display:inline-flex;gap:8px;flex-wrap:wrap"></span>
    </div>
    <div class="controls">
      <input type="search" id="q" placeholder="Filter by title, seller or location…">
      <select id="watchSel"><option value="all">All watches</option></select>
      <select id="srcSel"><option value="all">All sites</option></select>
      <button class="chip" id="btnWorking" aria-pressed="false">Confirmed working only</button>
    </div>
    <div id="tableHost"></div>
    <div class="charts" id="charts"></div>
  </section>

  <section id="panel-watches" hidden>
    <div class="card">
      <h3>What to hunt for</h3>
      <div class="cap">Switch watches on or off, and adjust the price cap and how far
        under market something has to be before it shows up. Changes save straight away.</div>
      <div class="controls">
        <input type="search" id="wq" placeholder="Find a watch…">
        <button id="btnAllOn">Turn all on</button>
        <button id="btnAllOff">Turn all off</button>
      </div>
    </div>
    <div id="watchList"></div>
  </section>

  <section id="panel-settings" hidden>
    <div class="card">
      <h3>eBay API keys</h3>
      <div class="cap">Free from developer.ebay.com — you want the <strong>Production</strong>
        keyset, not Sandbox. Stored only on this machine. CeX needs no keys; without these,
        eBay is skipped and CeX finds are shown without a market comparison.</div>
      <div class="field">
        <label for="cid">App ID (Client ID)</label>
        <input type="text" id="cid" placeholder="Yourname-appname-PRD-xxxxxxxxx-xxxxxxxx" autocomplete="off" spellcheck="false">
      </div>
      <div class="field">
        <label for="csec">Cert ID (Client Secret)</label>
        <input type="password" id="csec" placeholder="PRD-xxxxxxxxxxxx-xxxx-xxxx-xxxx" autocomplete="off">
      </div>
      <button class="primary" id="btnSaveKeys">Save keys</button>
      <button id="btnOpenDev">Open developer.ebay.com</button>
      <span id="keyMsg"></span>
    </div>

    <div class="card">
      <h3>Where to search</h3>
      <div class="cap">Everything stays UK-only regardless — no import fees.</div>
      <div id="siteToggles"></div>
      <div class="meta" style="margin-top:10px">
        Sites that can't be searched from here — Vinted (bot-blocked), Facebook Marketplace
        (needs a login), Gumtree, Back Market, musicMagpie and the rest — appear as
        one-click search buttons on each watch instead. Scraping them would break within
        weeks and breaches their terms; a link that opens the right search does not.
      </div>
    </div>

    <div class="card">
      <h3>Scanning</h3>
      <div class="field">
        <label for="interval">Automatic scan every (minutes)</label>
        <input type="number" id="interval" min="5" max="1440" step="5">
        <span class="hint">Only applies while "Auto" is switched on in the toolbar.</span>
      </div>
      <div class="field">
        <label for="qmode">Default condition strictness</label>
        <select id="qmode">
          <option value="strict">Strict — only listings that say they work</option>
          <option value="balanced">Balanced — reject broken, allow unclear</option>
          <option value="loose">Loose — everything not explicitly broken</option>
        </select>
        <span class="hint">Individual watches can override this.</span>
      </div>
      <div class="field">
        <label for="fbpct">Minimum seller feedback %</label>
        <input type="number" id="fbpct" min="0" max="100" step="1">
      </div>
      <div class="field">
        <label for="fbscore">Minimum seller feedback count</label>
        <input type="number" id="fbscore" min="0" max="100000" step="1">
      </div>
      <div class="field">
        <label for="saveDir">Save to</label>
        <div class="controls" style="margin-bottom:0">
          <input type="text" id="saveDir" style="flex:1;min-width:180px" autocomplete="off" spellcheck="false">
          <button id="btnBrowseDir" title="Pick a folder">Browse…</button>
        </div>
        <span class="hint">Where saved snapshots go. Empty means your Downloads folder.</span>
      </div>
      <button class="primary" id="btnSaveSettings">Save settings</button>
      <span id="setMsg"></span>
    </div>

    <div class="card">
      <h3>Activity</h3>
      <pre class="log" id="logBox"></pre>
      <div class="controls" style="margin-top:12px;margin-bottom:0">
        <button id="btnDemo">Load demo data</button>
        <button id="btnExport" title="Save a read-only copy of the dashboard as one HTML file">Save snapshot</button>
        <button class="danger" id="btnClear">Clear all saved listings</button>
        <span id="exportMsg"></span>
      </div>
      <div class="meta" id="paths" style="margin-top:10px"></div>
    </div>
  </section>

  <footer>
    <strong>UK only.</strong> Every listing is located in Great Britain and ships within it,
    so no import duty, VAT handling or customs fees apply. Prices are item + postage.
    "Under market" compares against the trimmed median of comparable live listings, not
    sold prices. Sanity-check anything before buying.
  </footer>
</div>

<script>
const TOKEN = "__TOKEN__";
let DATA = { items: [], history: {}, groups: {}, watches: [], watch_config: [],
             settings: {}, status: {}, currency: "GBP" };
let activeTab = "deals", activeGroup = "all", activeWatch = "all", activeSource = "all";
let onlyWorking = false, sortKey = "discount_pct", sortDir = -1;
let keysDirty = false;

const $ = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = v => (DATA.currency === "GBP" ? "£" : DATA.currency + " ") + Number(v || 0).toFixed(2);

async function api(path, body) {
  // A saved-out copy of this page has its data baked in and no server behind it.
  if (typeof STATIC_DATA !== "undefined") {
    if (path.startsWith("/api/data")) return STATIC_DATA;
    if (path.startsWith("/api/status")) return STATIC_DATA.status || {};
    return { ok: false, error: "This is a saved preview - open the app to change anything." };
  }
  const opts = { headers: { "X-Session-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path + (path.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(TOKEN), opts);
  let out = null;
  try { out = await res.json(); } catch (e) { out = null; }
  if (!res.ok && !(out && (out.error || out.detail))) {
    // 500 with a message is fine - callers show it. Anything else is a real failure.
    throw new Error("Server replied " + res.status + " for " + path);
  }
  return out === null ? {} : out;
}

// Links must be handed to the real browser: inside the app's own window a
// normal link either does nothing or replaces the app itself.
async function openExternal(url) {
  if (!url) return;
  if (typeof STATIC_DATA !== "undefined") { window.open(url, "_blank"); return; }
  try {
    const res = await api("/api/open", { url });
    if (res && res.error) window.open(url, "_blank");
  } catch (e) { window.open(url, "_blank"); }
}

function since(iso) {
  if (!iso) return "never";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return mins + "m ago";
  const hrs = Math.floor(mins / 60);
  return hrs < 24 ? hrs + "h ago" : Math.floor(hrs / 24) + "d ago";
}

/* ----------------------------------------------------------- deals tab -- */

function tiles() {
  const items = DATA.items.filter(i => isFeed(i) === (activeTab === "feeds"));
  const dayAgo = Date.now() - 86400000;
  const fresh = items.filter(i => new Date(i.first_seen).getTime() > dayAgo);
  const best = items.reduce((a, b) => (b.discount_pct > (a ? a.discount_pct : -999) ? b : a), null);
  const working = items.filter(i => i.quality === "working");
  const on = (DATA.watch_config || []).filter(w => w.enabled !== false).length;
  const rows = [
    { l: "Listings tracked", v: items.length, n: on + " of " + (DATA.watch_config || []).length + " watches on" },
    { l: "Confirmed working", v: working.length, n: (items.length - working.length) + " with unclear condition" },
    { l: "Found last 24h", v: fresh.length, n: fresh.length ? "newest " + since(fresh.reduce((a, b) => (a.first_seen > b.first_seen ? a : b)).first_seen) : "nothing new yet" },
    { l: "Best discount", v: best ? Math.round(best.discount_pct) + "%" : "–",
      n: best ? fmt(best.total) + " vs " + fmt(best.baseline) : "no baseline yet" },
  ];
  $("tiles").innerHTML = rows.map(r =>
    `<div class="tile"><div class="label">${r.l}</div><div class="value">${r.v}</div><div class="note">${r.n}</div></div>`).join("");
}

function chips() {
  const groups = ["all"].concat(Object.keys(DATA.groups || {}));
  $("groupChips").innerHTML = groups.map(g => {
    const n = g === "all" ? DATA.items.length : DATA.items.filter(i => (i.grp || "Other") === g).length;
    return `<button class="chip" data-g="${esc(g)}" aria-pressed="${g === activeGroup}">` +
           `${g === "all" ? "Everything" : esc(g)}<span class="count">${n}</span></button>`;
  }).join("");
  $("groupChips").querySelectorAll(".chip").forEach(c => c.onclick = () => {
    activeGroup = c.dataset.g; activeWatch = "all"; chips(); table(); charts();
  });

  const inGroup = activeGroup === "all" ? DATA.watches : (DATA.groups[activeGroup] || []);
  $("watchSel").innerHTML = `<option value="all">All watches${activeGroup === "all" ? "" : " in " + esc(activeGroup)}</option>` +
    inGroup.map(w => `<option value="${esc(w)}"${w === activeWatch ? " selected" : ""}>${esc(w)}</option>`).join("");

  const sources = Array.from(new Set(DATA.items.filter(i => isFeed(i) === (activeTab === "feeds")).map(i => i.source || "eBay"))).sort();
  $("srcSel").innerHTML = `<option value="all">All sites</option>` +
    sources.map(s => `<option value="${esc(s)}"${s === activeSource ? " selected" : ""}>${esc(s)}</option>`).join("");
  $("srcSel").hidden = sources.length < 2;
}

const isFeed = i => ((DATA.settings && DATA.settings.feed_sources) || []).includes(i.source);

function visibleRows() {
  const q = ($("q").value || "").toLowerCase();
  return DATA.items.filter(i => {
    if (isFeed(i) !== (activeTab === "feeds")) return false;
    if (activeGroup !== "all" && (i.grp || "Other") !== activeGroup) return false;
    if (activeWatch !== "all" && i.watch !== activeWatch) return false;
    if (activeSource !== "all" && (i.source || "eBay") !== activeSource) return false;
    if (onlyWorking && i.quality !== "working") return false;
    if (!q) return true;
    return (i.title + " " + i.seller_name + " " + i.location).toLowerCase().includes(q);
  }).sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    if (typeof x === "number" && typeof y === "number") return (x - y) * sortDir;
    return String(x).localeCompare(String(y)) * sortDir;
  });
}

const COLS = [
  { k: "image", l: "", nosort: true },
  { k: "title", l: "Listing" },
  { k: "condition", l: "Condition" },
  { k: "total", l: "Total", num: true },
  { k: "baseline", l: "Market", num: true },
  { k: "discount_pct", l: "Under market", num: true },
  { k: "seller_score", l: "Seller", num: true },
  { k: "first_seen", l: "Seen" },
];

function endsIn(iso) {
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  if (mins <= 0) return "now";
  if (mins < 60) return "in " + mins + "m";
  const hrs = Math.round(mins / 60);
  return hrs < 48 ? "in " + hrs + "h" : "in " + Math.round(hrs / 24) + "d";
}

function qualityChip(r) {
  const why = esc(r.quality_why || "");
  if (r.quality === "working") return `<span title="${why}" style="color:var(--good)">✓ says it works</span>`;
  if (r.quality === "unsure") return `<span title="${why}" style="color:var(--warn)">? condition unclear</span>`;
  return "";
}

function flagBadges(flags) {
  if (!flags) return "";
  return flags.split("|").filter(Boolean).map(f => {
    if (f === "too-good-to-be-true") return `<span class="flag crit" title="Far below market — check for scams, wrong model or parts-only">⚠ check carefully</span>`;
    if (f === "low-feedback-seller") return `<span class="flag warn" title="Seller has little feedback history">new seller</span>`;
    if (f === "postage-heavy") return `<span class="flag" title="Postage costs more than the item">postage heavy</span>`;
    if (f === "spec-unclear") return `<span class="flag warn" title="The listing doesn't state a spec this watch asks for (RAM, storage or CPU) — check before buying">spec unclear</span>`;
    return "";
  }).join("");
}

function table() {
  const rows = visibleRows(), host = $("tableHost");
  if (!rows.length) {
    host.innerHTML = `<div class="card empty">Nothing matching yet.<br>
      <span class="meta">Press <strong>Scan now</strong>, or loosen a watch on the Watches tab.</span></div>`;
    return;
  }
  const maxDisc = Math.max(40, ...rows.map(r => r.discount_pct));
  const head = COLS.map(c => `<th data-k="${c.k}" class="${c.num ? "num" : ""}">${c.l}` +
    (c.nosort ? "" : (sortKey === c.k ? ` <span class="arrow">${sortDir < 0 ? "▾" : "▴"}</span>` : "")) + `</th>`).join("");

  const body = rows.map((r, idx) => {
    const pct = Math.max(0, Math.min(100, (r.discount_pct / maxDisc) * 100));
    const img = r.image
      ? `<img class="thumb" src="${esc(r.image)}" alt="" loading="lazy" referrerpolicy="no-referrer"
           data-i="${idx}" onerror="this.outerHTML='<div class=&quot;thumb ph&quot;>no image</div>'">`
      : `<div class="thumb ph">no image</div>`;
    const disc = r.baseline
      ? `<div class="bar-wrap"><div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
         <span class="bar-label">${Math.round(r.discount_pct)}%</span></div>`
      : `<span class="meta">no baseline</span>`;
    const src = (r.source || "eBay");
    return `<tr>
      <td>${img}</td>
      <td><a class="title" data-i="${idx}" href="${esc(r.url)}" target="_blank"
             rel="noopener" title="${esc(r.url)}">${esc(r.title)}</a>${flagBadges(r.flags)}
        <div class="meta"><span class="src ${src.toLowerCase().replace(/[^a-z0-9]/g, "")}">${esc(src)}${
          r.bid_count ? " · " + r.bid_count + (r.bid_count === 1 ? " bid" : " bids") : ""}${
          r.ends ? " · ends " + endsIn(r.ends) : ""}</span>${esc(r.grp || "Other")} ›
        ${esc(r.watch)} · ${esc(r.location || "UK")}${r.free_shipping ? " · free postage"
          : (r.shipping ? " · +" + fmt(r.shipping) + " postage" : "")}</div></td>
      <td>${esc(r.condition)}<div class="meta">${qualityChip(r)}</div>${
        r.specs ? `<div class="meta spec" title="Specs as stated by the listing">${esc(r.specs)}</div>` : ""}</td>
      <td class="num">${fmt(r.total)}</td>
      <td class="num">${r.baseline ? fmt(r.baseline) : "–"}</td>
      <td>${disc}</td>
      <td class="num">${r.seller_score || 0}<div class="meta">${r.seller_pct || 0}%</div></td>
      <td>${since(r.first_seen)}</td></tr>`;
  }).join("");

  host.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  host.querySelectorAll("th[data-k]").forEach(th => th.onclick = () => {
    const k = th.dataset.k;
    if (k === "image") return;
    if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = -1; }
    table();
  });
  host.querySelectorAll("[data-i]").forEach(el => el.onclick = (ev) => {
    const row = rows[Number(el.dataset.i)];
    if (!row) return;
    // Hand it to the real browser. The href stays on the anchor so the link can
    // still be copied, and so this page works if it's ever saved out as a file.
    if (typeof STATIC_DATA === "undefined") { ev.preventDefault(); openExternal(row.url); }
  });
}

function sparkline(points, w, h) {
  if (points.length < 2) return `<div class="meta">Not enough history yet.</div>`;
  const vals = points.map(p => p.median);
  const min = Math.min(...vals), max = Math.max(...vals);
  const pad = (max - min) * 0.15 || 1, lo = min - pad, hi = max + pad;
  const x = i => 4 + (i / (points.length - 1)) * (w - 8);
  const y = v => h - 14 - ((v - lo) / (hi - lo)) * (h - 26);
  const d = points.map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p.median).toFixed(1)).join(" ");
  const last = points[points.length - 1];
  return `<svg width="100%" viewBox="0 0 ${w} ${h}" role="img" aria-label="Market median over time">
    <line x1="4" y1="${h - 12}" x2="${w - 4}" y2="${h - 12}" stroke="var(--field-border)" stroke-width="1"/>
    <path d="${d}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${x(points.length - 1).toFixed(1)}" cy="${y(last.median).toFixed(1)}" r="4"
      fill="var(--accent)" stroke="var(--panel)" stroke-width="2"/></svg>`;
}

function charts() {
  const host = $("charts");
  let keys = Object.keys(DATA.history || {});
  if (activeGroup !== "all") {
    const inGroup = new Set(DATA.groups[activeGroup] || []);
    keys = keys.filter(k => inGroup.has(k));
  }
  if (activeWatch !== "all") keys = keys.filter(k => k === activeWatch);
  if (!keys.length) { host.innerHTML = ""; return; }
  host.innerHTML = keys.map(k => {
    const pts = DATA.history[k], last = pts[pts.length - 1], first = pts[0];
    const delta = first.median ? ((last.median - first.median) / first.median) * 100 : 0;
    return `<div class="card"><h3>${esc(k)} — market median</h3>
      <div class="cap">${fmt(last.median)} now${pts.length > 1 ?
        " · " + (delta >= 0 ? "+" : "") + delta.toFixed(1) + "% since first scan" : ""}</div>
      ${sparkline(pts, 300, 92)}</div>`;
  }).join("");
}

/* --------------------------------------------------------- watches tab -- */

function specSummary(w) {
  const bits = [];
  if ((w.brands || []).length) bits.push(w.brands.join("/"));
  if ((w.cpus || []).length) bits.push(w.cpus.join("/"));
  if (w.min_ram_gb) bits.push(w.min_ram_gb + "GB+ RAM");
  if (w.min_storage_gb) bits.push((w.min_storage_gb >= 1024 ? (w.min_storage_gb / 1024) + "TB" : w.min_storage_gb + "GB") + "+ storage");
  return bits.join(" · ");
}

function watchList() {
  const filter = ($("wq").value || "").toLowerCase();
  const groups = {};
  (DATA.watch_config || []).forEach(w => {
    if (filter && !(w.name + " " + w.query + " " + (w.group || "")).toLowerCase().includes(filter)) return;
    (groups[w.group || "Other"] = groups[w.group || "Other"] || []).push(w);
  });
  const host = $("watchList");
  if (!Object.keys(groups).length) { host.innerHTML = `<div class="card empty">No watches match.</div>`; return; }

  host.innerHTML = Object.keys(groups).sort().map(g => `
    <div class="wgroup"><h2>${esc(g)}</h2><div class="card" style="padding:0">
    ${groups[g].map(w => `
      <div class="wrow" data-name="${esc(w.name)}">
        <button class="toggle" aria-pressed="${w.enabled !== false}" data-act="toggle" title="Switch this watch on or off"></button>
        <div>
          <div class="wname">${esc(w.name)}</div>
          <div class="wquery">${esc(w.query)}</div>
          ${w.note ? `<div class="wnote">${esc(w.note)}</div>` : ""}
          <div class="links" data-links="${esc(w.name)}">
            <button class="linkbtn" data-act="specs">${specSummary(w) ? "Specs: " + esc(specSummary(w)) : "Specs & words…"}</button>
            <button class="linkbtn" data-act="links">Search other sites…</button>
          </div>
          <div class="links" data-linkbox hidden></div>
          <div class="specs" data-specs>
            <label>Brands (any of)<input type="text" data-s="brands" value="${esc((w.brands || []).join(", "))}" placeholder="lenovo, dell"></label>
            <label>CPU (any of)<input type="text" data-s="cpus" value="${esc((w.cpus || []).join(", "))}" placeholder="i5, i7, ryzen 5, m1"></label>
            <label>Min RAM (GB)<input type="number" min="0" max="4096" step="4" data-s="min_ram_gb" value="${w.min_ram_gb || 0}"></label>
            <label>Min storage (GB)<input type="number" min="0" max="1000000" step="64" data-s="min_storage_gb" value="${w.min_storage_gb || 0}"></label>
            <label>If a spec isn't stated<select data-s="specs_required">
              <option value="0"${w.specs_required ? "" : " selected"}>Keep it, flag "spec unclear"</option>
              <option value="1"${w.specs_required ? " selected" : ""}>Drop it</option>
            </select></label>
            <label class="wide">Search query (eBay syntax: A OR B)<input type="text" data-s="query" value="${esc(w.query || "")}"></label>
            <label class="wide">Market baseline query (what a typical listing is called)<input type="text" data-s="baseline_query" value="${esc(w.baseline_query || "")}" placeholder="same as the search query if empty"></label>
            <label class="wide">Must include (all of)<input type="text" data-s="require_terms" value="${esc((w.require_terms || []).join(", "))}" placeholder="laptop"></label>
            <label class="wide">Must not include (any of)<input type="text" data-s="exclude_terms" value="${esc((w.exclude_terms || []).join(", "))}" placeholder="celeron, chromebook"></label>
            <div class="hint">Comma-separated, whole words, case doesn't matter. Empty means "don't care". RAM and storage are read
              off eBay titles ("16GB RAM 512GB SSD", "8GB/256GB"); CeX states them outright. Brand and CPU are matched against
              the title, or CeX's own attributes. Saves as you go.</div>
          </div>
        </div>
        <div class="wfields">
          <label>Max £<input type="number" min="1" max="100000" step="5" value="${w.max_price || 100}" data-f="max_price"></label>
          <label>Min £<input type="number" min="0" max="100000" step="5" value="${w.min_price || 0}" data-f="min_price"></label>
          <label>Under mkt %<input type="number" min="0" max="95" step="5" value="${w.min_discount_pct || 0}" data-f="min_discount_pct"></label>
          <label>Condition<select data-f="quality_mode">
            <option value="strict"${w.quality_mode === "strict" ? " selected" : ""}>Strict</option>
            <option value="balanced"${(w.quality_mode || "balanced") === "balanced" ? " selected" : ""}>Balanced</option>
            <option value="loose"${w.quality_mode === "loose" ? " selected" : ""}>Loose</option>
          </select></label>
          <button data-act="scanone" title="Scan just this watch now">Scan</button>
        </div>
      </div>`).join("")}
    </div></div>`).join("");

  host.querySelectorAll(".wrow").forEach(row => {
    const name = row.dataset.name;
    row.querySelector('[data-act="toggle"]').onclick = async (e) => {
      const btn = e.currentTarget;
      const next = btn.getAttribute("aria-pressed") !== "true";
      btn.setAttribute("aria-pressed", String(next));
      await api("/api/watch", { name, enabled: next });
      const w = DATA.watch_config.find(x => x.name === name);
      if (w) w.enabled = next;
      tiles();
    };
    row.querySelectorAll("[data-f]").forEach(input => {
      input.onchange = async () => {
        const payload = { name };
        payload[input.dataset.f] = input.type === "number" ? Number(input.value) : input.value;
        const res = await api("/api/watch", payload);
        if (!res.ok) { alert(res.error || "Could not save that."); refresh(); }
        else Object.assign(DATA.watch_config.find(x => x.name === name) || {}, res.watch || {});
      };
    });
    row.querySelector('[data-act="specs"]').onclick = () => {
      row.querySelector("[data-specs]").classList.toggle("open");
    };
    row.querySelectorAll("[data-s]").forEach(input => {
      input.onchange = async () => {
        const payload = { name };
        const f = input.dataset.s;
        payload[f] = f === "specs_required" ? input.value === "1"
                   : input.type === "number" ? Number(input.value) : input.value;
        const res = await api("/api/watch", payload);
        if (!res.ok) { alert(res.error || "Could not save that."); return; }
        const w = DATA.watch_config.find(x => x.name === name);
        if (w) Object.assign(w, res.watch || {});
        if (f === "query") row.querySelector(".wquery").textContent = res.watch ? res.watch.query : input.value;
        const btn = row.querySelector('[data-act="specs"]');
        if (btn && w) btn.textContent = specSummary(w) ? "Specs: " + specSummary(w) : "Specs & words…";
      };
    });
    row.querySelector('[data-act="scanone"]').onclick = async () => {
      await api("/api/scan", { watch: [name] });
      activeTab = "deals"; showTab(); poll();
    };
    row.querySelector('[data-act="links"]').onclick = async (e) => {
      const box = row.querySelector("[data-linkbox]");
      box.hidden = false;
      const res = await api("/api/links?watch=" + encodeURIComponent(name));
      box.innerHTML = (res.links || []).map(l =>
        `<button class="linkbtn${l.caution ? " caution" : ""}" data-url="${esc(l.url)}"
          title="${esc(l.why)}">${esc(l.name)}${l.caution ? " ⚠" : ""} ↗</button>`).join("")
        + `<div class="wnote" style="width:100%">Hover each for what it is good for.
           ⚠ means no buyer protection — worth searching, but that is where the scams are.</div>`;
      box.querySelectorAll("[data-url]").forEach(b => b.onclick = () => openExternal(b.dataset.url));
    };
  });
}

/* -------------------------------------------------------- settings tab -- */

function fillSettings() {
  const s = DATA.settings || {};
  if (!keysDirty) {
    $("cid").placeholder = s.has_keys ? "•••••••• saved" : "Yourname-appname-PRD-xxxxxxxxx-xxxxxxxx";
    $("csec").placeholder = s.has_keys ? "•••••••• saved" : "PRD-xxxxxxxxxxxx-xxxx-xxxx-xxxx";
  }
  // A scan finishing mid-edit used to overwrite whatever was being typed.
  const focus = document.activeElement;
  const editing = focus && $("panel-settings").contains(focus) && /^(INPUT|SELECT)$/.test(focus.tagName);
  if (!editing) {
    $("interval").value = s.poll_interval_minutes ?? 20;
    $("qmode").value = s.quality_mode || "balanced";
    $("fbpct").value = s.min_seller_feedback_pct ?? 90;
    $("fbscore").value = s.min_seller_feedback_score ?? 5;
    $("saveDir").value = s.save_dir || "";
  }
  $("saveDir").placeholder = s.save_dir_default || "Downloads";
  $("paths").textContent = "Version " + (s.version || "") + " · data stored in " + (s.data_dir || "");
  $("btnQuit").hidden = !s.browser_mode;

  const sites = s.sites || { ebay: true };
  $("siteToggles").innerHTML = [
    { k: "ebay", n: "eBay UK — Buy It Now",
      d: "The main source. Private and trade sellers, judged on condition wording." },
    { k: "ebay_refurbished", n: "eBay UK — Refurbished",
      d: "eBay's own graded programme: Certified, Excellent, Very Good and Good. Only qualified sellers and brand outlets can list here and every item carries a warranty, so the condition guesswork is skipped. Priced higher than a private sale, so the discount bar drops 15 points to account for the warranty." },
    { k: "ebay_auctions", n: "eBay UK — auctions ending soon",
      d: "Auctions closing within the next 12 hours, priced on the current bid rather than the start price. This is where things genuinely go under value — but the price can still climb before it ends." },
    { k: "backmarket", n: "Back Market",
      d: "Graded refurbished tech (Fair / Good / Excellent) with a 12-month minimum warranty and 30-day returns — the safest place on the list. Searched through the index its own site uses; no keys. Treated like eBay Refurbished for the discount bar." },
    { k: "musicmagpie", n: "musicMagpie",
      d: "Refurbished phones, laptops, consoles and media, 12-month warranty, free delivery. Searched through its store's own search service; no keys. Cheapest in-stock grade is shown." },
    { k: "cashconverters", n: "Cash Converters",
      d: "High-street pawn stock, tested in store, listed nationally. Collection-only items are dropped unless the store is in your local_towns (config.json); posted items carry their postage in the total. Condition is the shop's 2–5 rating where given." },
    { k: "hukd", n: "HotUKDeals — feed",
      d: "The site's new and hot RSS feeds, matched against your watches and shown on the Feeds tab. New items from shops, not the used market — useful for spotting when new undercuts used. Add tag feeds as hukd_tags in config.json." },
    { k: "reddit_hws", n: "r/hardwareswapuk — feed",
      d: "Private sales posted to Reddit, read through its public listing, shown on the Feeds tab. No buyer protection at all — PayPal Goods & Services or nothing. Off by default; press Test to see whether Reddit is answering from this machine." },
    { k: "cex", n: "CeX — online stock",
      d: "Searched through the stock index CeX's own website uses. No keys needed. Every box is tested, graded A/B/C and carries CeX's 24-month warranty, so the condition guesswork is skipped and the discount bar drops 15 points, as for eBay Refurbished. Only stock that can be bought online is shown; local stores that also have it are named on the row. Add CeX's delivery charge as cex_delivery_charge in config.json if you want totals to include it." },
  ].map(s2 => `
    <div class="wrow" style="grid-template-columns:44px 1fr auto;border:none;padding:8px 0">
      <button class="toggle" aria-pressed="${!!sites[s2.k]}" data-site="${s2.k}"></button>
      <div><div class="wname">${s2.n}</div><div class="wnote">${s2.d}</div>
        <div class="wnote" id="test-${s2.k}"></div></div>
      <button data-test="${s2.k}">Test</button>
    </div>`).join("");

  $("siteToggles").querySelectorAll("[data-site]").forEach(b => b.onclick = async () => {
    const next = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", String(next));
    const res = await api("/api/sites", { [b.dataset.site]: next });
    if (!res.ok) {
      b.setAttribute("aria-pressed", String(!next));
      alert(res.error || "Keep at least one site switched on.");
    } else if (DATA.settings) DATA.settings.sites = res.sites || DATA.settings.sites;
  });

  $("siteToggles").querySelectorAll("[data-test]").forEach(b => b.onclick = async () => {
    const key = b.dataset.test, out = $("test-" + key);
    b.disabled = true; out.textContent = "Testing…"; out.className = "wnote";
    const res = await api("/api/test-site", { site: key });
    b.disabled = false;
    out.className = res.ok ? "ok" : "err";
    out.textContent = res.detail || (res.ok ? "Connected." : "Failed.");
  });
}

/* ------------------------------------------------------------- shell --- */

function showTab() {
  document.querySelectorAll(".tab").forEach(t =>
    t.setAttribute("aria-selected", String(t.dataset.tab === activeTab)));
  ["deals", "watches", "settings"].forEach(t => $("panel-" + t).hidden = (t !== activeTab));
  if (activeTab === "feeds") { $("panel-deals").hidden = false; tiles(); chips(); table(); charts(); }
  if (activeTab === "deals") { tiles(); chips(); table(); charts(); }
  $("feedNote").hidden = activeTab !== "feeds";
  $("charts").hidden = activeTab === "feeds";
  if (activeTab === "watches") watchList();
  if (activeTab === "settings") fillSettings();
}

function applyStatus(st) {
  const scanning = st.scanning;
  $("btnScan").disabled = scanning;
  $("btnScan").textContent = scanning ? "Scanning…" : "Scan now";
  $("btnAuto").setAttribute("aria-pressed", String(!!st.auto));
  $("dot").className = "dot" + (scanning ? " live" : (st.last_error ? " err" : ""));

  let text;
  if (scanning) {
    const p = st.progress || {};
    text = p.total ? `Scanning ${p.done}/${p.total}${p.watch ? " — " + p.watch : ""}` : "Scanning…";
    $("progBar").style.width = p.total ? (p.done / p.total * 100) + "%" : "12%";
  } else {
    $("progBar").style.width = "0";
    const r = st.last_result;
    text = st.last_error ? "Problem: " + st.last_error
      : (r ? `Last scan ${since(st.last_run)} — ${r.new_hits} new, ${r.scanned} matching`
           : "Ready — press Scan now");
    if (!st.last_error && st.auto && st.next_auto_in != null)
      text += ` · next in ${Math.ceil(st.next_auto_in / 60)}m`;
  }
  $("statusText").textContent = text;

  $("logBox").textContent = (st.log || []).join("\n");
  $("logBox").scrollTop = $("logBox").scrollHeight;

  const b = $("banner");
  if (typeof STATIC_DATA !== "undefined") return;   // snapshot keeps its own notice
  if (st.last_error) {
    b.innerHTML = `<div class="banner bad"><strong>Scan problem.</strong> ${esc(st.last_error)}</div>`;
  } else if (DATA.settings && DATA.settings.has_keys === false) {
    b.innerHTML = `<div class="banner"><strong>No eBay API keys yet.</strong>
      CeX can be scanned without them, but eBay listings and the market comparison
      need them — about ten minutes to get from developer.ebay.com, under Settings.
      "Load demo data" shows how it looks in the meantime.</div>`;
  } else b.innerHTML = "";
}

async function refresh() {
  let data;
  try {
    data = await api("/api/data");
    if (data.error) throw new Error(data.error);
  } catch (e) {
    $("statusText").textContent = "Problem: " + e.message;
    $("dot").className = "dot err";
    $("banner").innerHTML = `<div class="banner bad"><strong>The app could not load its data.</strong> ${esc(e.message)}</div>`;
    return;
  }
  DATA = data;
  if (data.settings && "dark" in data.settings) setTheme(!!data.settings.dark, false);
  $("btnQuit").hidden = !(data.settings && data.settings.browser_mode);
  tiles(); chips(); table(); charts();
  if (activeTab === "watches") watchList();
  if (activeTab === "settings") fillSettings();
  applyStatus(data.status || {});
}

let wasScanning = false;
async function poll() {
  try {
    const st = await api("/api/status");
    applyStatus(st);
    if (wasScanning && !st.scanning) await refresh();
    wasScanning = st.scanning;
  } catch (e) { /* app closing */ }
}

/* wiring */
$("btnScan").onclick = async () => {
  try { await api("/api/scan", {}); } catch (e) { $("statusText").textContent = "Problem: " + e.message; }
  poll();
};
$("btnAuto").onclick = async () => {
  const on = $("btnAuto").getAttribute("aria-pressed") !== "true";
  applyStatus(await api("/api/auto", { on }));
};
function setTheme(dark, persist) {
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  $("btnTheme").textContent = dark ? "Light" : "Dark";
  if (persist && typeof STATIC_DATA === "undefined") {
    if (DATA.settings) DATA.settings.dark = dark;
    api("/api/settings", { dark }).catch(() => { /* the choice still applies for this session */ });
  }
}
function toggleTheme() { setTheme(document.documentElement.getAttribute("data-theme") !== "dark", true); }
$("btnTheme").onclick = toggleTheme;
document.addEventListener("keydown", e => {
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "d") {
    e.preventDefault(); toggleTheme();
  }
});
document.querySelectorAll(".tab").forEach(t => t.onclick = () => { activeTab = t.dataset.tab; showTab(); });
$("q").oninput = table;
$("wq").oninput = watchList;
$("watchSel").onchange = e => { activeWatch = e.target.value; table(); charts(); };
$("srcSel").onchange = e => { activeSource = e.target.value; table(); };
$("btnWorking").onclick = e => {
  onlyWorking = !onlyWorking;
  e.currentTarget.setAttribute("aria-pressed", String(onlyWorking));
  table();
};
["cid", "csec"].forEach(id => $(id).oninput = () => { keysDirty = true; });
$("btnSaveKeys").onclick = async () => {
  const msg = $("keyMsg");
  const res = await api("/api/credentials", { client_id: $("cid").value, client_secret: $("csec").value });
  if (res.ok) {
    msg.className = "ok"; msg.textContent = " Saved. Press Scan now.";
    $("cid").value = ""; $("csec").value = ""; keysDirty = false; refresh();
  } else { msg.className = "err"; msg.textContent = " " + (res.error || "Could not save."); }
};
$("btnOpenDev").onclick = () => openExternal("https://developer.ebay.com/my/keys");
$("btnSaveSettings").onclick = async () => {
  const msg = $("setMsg");
  const res = await api("/api/settings", {
    poll_interval_minutes: Number($("interval").value),
    quality_mode: $("qmode").value,
    min_seller_feedback_pct: Number($("fbpct").value),
    min_seller_feedback_score: Number($("fbscore").value),
    save_dir: $("saveDir").value.trim(),
  });
  msg.className = res.ok ? "ok" : "err";
  msg.textContent = res.ok ? " Saved." : " " + (res.error || "Could not save.");
  setTimeout(() => { msg.textContent = ""; }, 2500);
  if (res.ok) refresh();
};
$("btnQuit").onclick = async () => {
  if (!confirm("Stop eBay Deal Hunter? Any scan in progress is abandoned.")) return;
  try { await api("/api/quit", {}); } catch (e) { /* server already gone */ }
  document.body.innerHTML = '<div class="wrap"><div class="card empty">eBay Deal Hunter has stopped. You can close this tab.</div></div>';
};
$("btnBrowseDir").onclick = async () => {
  // Native folder picker when the app has its own window; in a browser tab
  // there is none, so the typed path is the way.
  const res = await api("/api/browse-dir", {});
  if (res.ok && res.path) $("saveDir").value = res.path;
  else if (res.error && res.error !== "cancelled") $("saveDir").focus();
};
$("btnExport").onclick = async () => {
  const msg = $("exportMsg");
  msg.className = ""; msg.textContent = " Saving…";
  const res = await api("/api/export", {});
  msg.className = res.ok ? "ok" : "err";
  msg.textContent = res.ok ? " Saved to " + res.path : " " + (res.error || "Could not save.");
};
$("btnDemo").onclick = async () => { await api("/api/scan", { demo: true }); activeTab = "deals"; showTab(); poll(); };
$("btnClear").onclick = async () => {
  if (!confirm("Remove every saved listing? Watches and settings are kept.")) return;
  await api("/api/clear"); refresh();
};
$("btnAllOn").onclick = async () => { await setAll(true); };
$("btnAllOff").onclick = async () => { await setAll(false); };
async function setAll(on) {
  for (const w of DATA.watch_config || []) {
    if ((w.enabled !== false) !== on) { await api("/api/watch", { name: w.name, enabled: on }); w.enabled = on; }
  }
  watchList(); tiles();
}

showTab();
refresh();
setInterval(poll, 2000);
</script>
</body>
</html>
"""

PAGE = (_PAGE.replace("__DARK_VARS__", theme.css_vars(True))
             .replace("__LIGHT_VARS__", theme.css_vars(False)))
