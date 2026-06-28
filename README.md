# TTNN Ops Coverage Matrix

An interactive, zero-dependency dashboard for the **TTNN (Tenstorrent) operation test matrix** — visualizing how every operation behaves across every `dtype × layout × memory` configuration, and how numerically accurate each result is.

Built to deploy as a **Cloudflare Workers Static Assets** site. The entire front end is hand-rolled HTML/CSS/SVG with no runtime libraries, so it loads instantly and works fully offline.

**Live:** https://ttnn-ops-coverage.aswincloud.com/

<!-- Badges are live: process.py emits public/badges/*.json from ops.csv on every
     build, and shields.io renders them via its endpoint API — so the numbers
     below always reflect the current data, never a hand-typed snapshot. -->
![configs](https://img.shields.io/endpoint?url=https%3A%2F%2Fttnn-ops-coverage.aswincloud.com%2Fbadges%2Fconfigs.json) ![ops](https://img.shields.io/endpoint?url=https%3A%2F%2Fttnn-ops-coverage.aswincloud.com%2Fbadges%2Fops.json) ![pass rate](https://img.shields.io/endpoint?url=https%3A%2F%2Fttnn-ops-coverage.aswincloud.com%2Fbadges%2Fpassrate.json) ![pass](https://img.shields.io/endpoint?url=https%3A%2F%2Fttnn-ops-coverage.aswincloud.com%2Fbadges%2Fpass.json) ![pcc fail](https://img.shields.io/endpoint?url=https%3A%2F%2Fttnn-ops-coverage.aswincloud.com%2Fbadges%2Fpccfail.json) ![error](https://img.shields.io/endpoint?url=https%3A%2F%2Fttnn-ops-coverage.aswincloud.com%2Fbadges%2Ferror.json)

---

## What it shows

The source data (`ops.csv`) is produced by [`eltwise_support_probe.py`](PROBE.md) — a
sweep over **every op × dtype × layout × memory configuration** (8 dtypes × 2 layouts ×
5 memory configs: interleaved `dram`/`l1` + sharded `height`/`width`/`block`). For every
config the probe records whether the op ran, whether the output matched a torch golden, the
**input range** fed to it, the **PCC** vs the golden, and the max per-element **ULP** error.
Each run's raw `pcc_or_reason` column is classified into a clean status taxonomy:

| Status | Meaning |
|--------|---------|
| 🟢 **Pass** | Output matched the golden reference within PCC threshold |
| 🟠 **PCC Fail** | Ran, but numerically inaccurate (PCC below threshold / NaN) |
| 🔴 **Hard Error** | `TT_FATAL` / `TT_THROW` — crashed before producing a result |
| 🔵 **No Golden** | Ran, but no reference output to verify against |
| ⚪ **Skipped** | Config unsupported / intentionally skipped |
| ◾ **Not in TTNN** | Operation not implemented |

PCC thresholds: `0.99` default, `0.97` for `bfloat8_b`, `0.90` for `bfloat4_b`; integer
dtypes are graded by **exact equality** (PCC shown for reference only).

### Dashboard panels

- **KPI cards** — pass rate, hard errors, PCC failures, op total, config total
- **Result-distribution donut** — click any slice to solo that status across the table
- **Outcome by axis** — stacked pass/fail composition per dtype, layout, and memory
- **Numerical accuracy (ULP)** — distribution of max per-element error in [ULP](https://en.wikipedia.org/wiki/Unit_in_the_last_place), log-bucketed; toggle between dtypes
- **Top hard-error signatures** — the most common device assertions, grouped by `source_file:line`
- **Coverage snapshot** — how configs split between verifiable and unverifiable
- **Operation leaderboard** — every op, sortable by any column, searchable. **Click a row** to expand a `dtype × layout·mem` heatmap; **hover any cell** for the exact status, input range, PCC, ULP, and failure reason.

### Run-to-run comparison

A **Changes** button diffs the current matrix against the previous dated probe snapshot
(`history/eltwise_support_matrix_YYYY-MM-DD.csv`) — surfacing which configs newly pass,
regressed, were added/removed, or had a meaningful PCC/ULP shift. The diff is computed at
**build time** in `process.py`; until two dated snapshots exist it honestly shows
"no baseline snapshot yet". See [PROBE.md](PROBE.md#daily-runs--dashboards) for the
`--dated` workflow.

### Suggest / feedback

A **Suggest** button opens a modal that POSTs to `/api/feedback` (handled by the Worker →
Resend email), for reporting a result mismatch — e.g. an op marked failed that actually works.

Keyboard: `/` focuses search · `Esc` clears search/solo or closes a modal.

---

## Project layout

```
.
├── public/                 # ← static assets served by the Worker
│   ├── index.html          #   markup + design system (CSS)
│   ├── app.js              #   chart/table renderer (no deps)
│   └── data.js             #   generated — window.DASH payload (gitignored)
├── worker/index.js         # serves assets + POST /api/feedback → Resend
├── ops.csv                 # source data (regenerate data.js from this)
├── process.py              # CSV → public/data.js transformer + classifier + run diff
├── eltwise_support_probe.py # the probe that GENERATES ops.csv (see PROBE.md)
├── history/                # dated probe snapshots (--dated); power the "Changes" diff
├── PROBE.md                # how the probe sweep works / how to run it
├── scripts/                # CI validators (check_data.py, check_code.mjs)
├── .github/workflows/ci.yml # data + code + lint gates on every push/PR
├── eslint.config.js        # flat ESLint config for the shipped JS
├── wrangler.jsonc          # Cloudflare Workers config (assets + feedback API)
└── package.json
```

`public/data.js` is a **build artifact** — it is *not* committed (gitignored). CI and
Cloudflare regenerate it from `ops.csv` on every deploy (and you regenerate it locally with
`python3 process.py`). **`ops.csv` is the single source of truth.**

---

## Continuous integration

Every push and PR runs `.github/workflows/ci.yml` — three gates that catch what Cloudflare
won't (a CSV that parses but yields wrong totals, malformed columns, broken JS, an
un-reconciling or accidentally-committed `data.js`):

| Job | Checks |
|-----|--------|
| **data integrity** | `ops.csv` shape + columns, PCC numeric-or-empty, `process.py` rebuilds and `statusCounts` sum == `meta.total` == row count |
| **code checks** | `node --check` on `app.js` + worker, boots `data.js` in a sandbox and reconciles, asserts `data.js` is not git-tracked |
| **lint** | ESLint over the shipped JS |

Run them all locally with `npm run check`.

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

Custom domain: **https://ttnn-ops-coverage.aswincloud.com/**

### Auto-deploy on push

This repo is connected to **Cloudflare Workers Builds** (CF-native Git integration —
configured in the Cloudflare dashboard, nothing required in the repo itself). On every
push to `main`, Cloudflare runs:

| Step | Command |
|------|---------|
| Build   | `npm run build`  → `python3 process.py` rebuilds `public/data.js` from `ops.csv` |
| Deploy  | `npx wrangler deploy` → ships `public/` to the edge |

So **updating the dashboard is just**: replace `ops.csv`, commit, push → live in ~a minute.
Because the build regenerates `data.js`, **`ops.csv` is the only file you ever need to touch.**

---

## Regenerating `data.js`

`process.py` does all the heavy lifting:

1. Parses `ops.csv` (RFC-correct CSV — failure reasons contain embedded commas/newlines from C++ backtraces).
2. Classifies each row's `accepted` + `pcc_or_reason` into the 6-status taxonomy.
3. Collapses verbose `TT_FATAL`/`TT_THROW` backtraces into `KIND file:line — message` signatures and groups them.
4. Computes per-op, per-dtype, per-layout, per-memory aggregations and the ULP distribution.
5. Diffs against the previous dated snapshot in `history/` to build the "Changes" payload.
6. Emits a compact `window.DASH = {…}` payload (interned strings + integer-indexed rows) to `public/data.js`.

Totals always reconcile to the row count — the script prints a status breakdown on every run.

<!-- ruleset enforcement smoke test (close me) -->
