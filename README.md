# TTNN Ops Coverage Matrix

An interactive, zero-dependency dashboard for the **TTNN (Tenstorrent) operation test matrix** — visualizing how 259 operations behave across every `dtype × layout × memory` configuration.

Built to deploy as a **Cloudflare Workers Static Assets** site. The entire front end is hand-rolled HTML/CSS/SVG with no runtime libraries, so it loads instantly and works fully offline.

![status: pass 2,684 · error 1,580 · no-golden 834 · pcc-fail 700 · skip 322](https://img.shields.io/badge/configs-6%2C124-3b82f6) ![ops](https://img.shields.io/badge/ops-259-3b82f6) ![pass%20rate](https://img.shields.io/badge/pass%20rate-79.3%25-10b981)

---

## What it shows

The source data (`ops.csv`) is a sweep of **6,124 test configurations** — each of 259 ops run across 6 dtypes × 2 layouts × 2 memory configs. Each run's raw `pcc_or_reason` column is classified into a clean 6-status taxonomy:

| Status | Meaning |
|--------|---------|
| 🟢 **Pass** | Output matched the golden reference within PCC threshold |
| 🟠 **PCC Fail** | Ran, but numerically inaccurate (PCC below threshold / NaN) |
| 🔴 **Hard Error** | `TT_FATAL` / `TT_THROW` — crashed before producing a result |
| 🔵 **No Golden** | Ran, but no reference output to verify against |
| ⚪ **Skipped** | Config unsupported / intentionally skipped |
| ◾ **Not in TTNN** | Operation not implemented |

### Dashboard panels

- **KPI cards** — pass rate, hard errors, PCC failures, no-golden count, op total, config total
- **Result-distribution donut** — click any slice to solo that status across the table
- **Outcome by axis** — stacked pass/fail composition per dtype, layout, and memory
- **Top hard-error signatures** — the most common device assertions, grouped by `source_file:line`
- **Coverage snapshot** — how configs split between verifiable and unverifiable
- **Operation leaderboard** — every op, sortable by any column, searchable. **Click a row** to expand a `dtype × layout·mem` heatmap; **hover any cell** for the exact failure reason.

Keyboard: `/` focuses search · `Esc` clears search/solo.

---

## Project layout

```
.
├── public/            # ← deployed to Cloudflare (static assets)
│   ├── index.html     #   markup + design system (CSS)
│   ├── app.js         #   chart/table renderer (no deps)
│   └── data.js        #   generated — window.DASH payload
├── ops.csv            # source data (regenerate data.js from this)
├── process.py         # CSV → public/data.js transformer + classifier
├── wrangler.jsonc     # Cloudflare Workers static-assets config
└── package.json
```

`public/data.js` is a build artifact — regenerate it whenever `ops.csv` changes.

---

## Local development

```bash
# Regenerate the dashboard data from the CSV
python3 process.py            # → writes public/data.js

# Serve locally (any static server works)
npm run serve                 # http://localhost:8080  (binds 0.0.0.0)
#   or
npx wrangler dev              # http://localhost:8787  (emulates the edge)
```

Updating the data is just: replace `ops.csv` → run `python3 process.py` → refresh. No rebuild step for HTML/JS.

---

## Deploy to Cloudflare Workers

This repo is configured for **Workers Static Assets** (no Worker script — Cloudflare serves `public/` directly from the edge).

```bash
npm install          # pulls wrangler
npx wrangler login   # one-time, opens browser
npm run deploy       # = python3 process.py && wrangler deploy
```

After the first deploy it's live at:

```
https://ttnn-ops-coverage.<your-subdomain>.workers.dev
```

To attach a custom domain or route, add a `routes` block to `wrangler.jsonc` (see the [Workers config docs](https://developers.cloudflare.com/workers/wrangler/configuration/)).

---

## Regenerating `data.js`

`process.py` does all the heavy lifting:

1. Parses `ops.csv` (RFC-correct CSV — failure reasons contain embedded commas/newlines from C++ backtraces).
2. Classifies each row's `accepted` + `pcc_or_reason` into the 6-status taxonomy.
3. Collapses verbose `TT_FATAL`/`TT_THROW` backtraces into `KIND file:line — message` signatures and groups them.
4. Computes per-op, per-dtype, per-layout, per-memory aggregations.
5. Emits a compact `window.DASH = {…}` payload (~136 KB) to `public/data.js`.

Totals always reconcile to the row count — the script prints a status breakdown on every run.
