#!/usr/bin/env python3
"""Transform the per-board eltwise support matrices into a compact data.js.

Each board has its own root CSV `eltwise_support_matrix_<board>.csv` (e.g.
`eltwise_support_matrix_n150.csv`, `eltwise_support_matrix_p100a.csv`) and its
own dated history under `history/workflow/eltwise_support_matrix_<board>_*.csv`.
The daily updater overwrites each board's root CSV every run and also drops a
dated copy in history/workflow/, so a board's newest history snapshot always
equals its root CSV — which compute_changes() relies on.

We build one flat payload per PRESENT board and emit them nested:

    window.DASH = { boards: { n150: {…}, p100a: {…} }, defaultBoard, boardOrder }

Each per-board object is the exact flat 16-key schema the dashboard renders;
app.js resolves the active board and reads that object as before. Only boards
whose root CSV exists are emitted, so P100a is simply absent until its first run.
"""
import csv, re, json, os, glob, datetime, sys
from collections import defaultdict, Counter

# Per-board root CSVs live at the repo root as eltwise_support_matrix_<board>.csv.
# The trailing "_" in the glob excludes any legacy bare `eltwise_support_matrix.csv`.
CSV_GLOB = "eltwise_support_matrix_*.csv"
CSV_PREFIX = "eltwise_support_matrix_"
OUT = "public/data.js"
HISTORY_DIR = os.path.join("history", "workflow")   # dated per-board snapshots

# Board display order preference; present boards are filtered to this, unknowns append.
BOARD_ORDER_PREF = ["n150", "p100a"]

# --- status taxonomy ------------------------------------------------------
# code -> (label, short, palette-role)
STATUS = ["PASS", "PCC_FAIL", "NO_GOLDEN", "SKIP", "ERROR", "NOT_IN_TTNN"]
S_IDX = {s: i for i, s in enumerate(STATUS)}

num_re = re.compile(r"^-?\d*\.?\d+$")
failval_re = re.compile(r"^fail\(([-\d.]+)\)$")
info_re = re.compile(r"info:\s*\|\s*(.*?)\s*(?:\||$)", re.S)
file_re = re.compile(r"@\s*\S+/([\w.]+:\d+)")
skip_re = re.compile(r"^skip\((.*)\)$")


def classify(accepted, p):
    """Return (status_code, short_reason)."""
    if p == "pass":
        return "PASS", "pass"
    if p == "no-golden":
        return "NO_GOLDEN", "no golden reference"
    if p == "nan":
        return "PCC_FAIL", "NaN output"
    m = skip_re.match(p)
    if m:
        return "SKIP", "skip: " + m.group(1)
    if p == "fail":
        return "PCC_FAIL", "PCC below threshold"
    m = failval_re.match(p)
    if m:
        return "PCC_FAIL", f"PCC {m.group(1)}"
    if num_re.match(p):
        return ("PASS" if accepted == "OK" else "PCC_FAIL"), f"PCC {p}"
    if p == "not in ttnn" or accepted == "NO_OP":
        return "NOT_IN_TTNN", "not implemented in ttnn"
    if "TT_FATAL" in p or "TT_THROW" in p:
        kind = "TT_FATAL" if "TT_FATAL" in p else "TT_THROW"
        loc = file_re.search(p)
        info = info_re.search(p)
        msg = (info.group(1) if info else "").strip().strip('"')
        msg = re.sub(r"\s+", " ", msg)[:90]
        loc_s = loc.group(1) if loc else ""
        short = f"{kind} {loc_s}".strip()
        if msg:
            short += f" — {msg}"
        return "ERROR", short
    # process-level crash (e.g. accepted=CRASH, reason="segfault-rc139")
    if accepted == "CRASH" or "segfault" in p.lower():
        m = re.search(r"rc(\d+)", p)
        return "ERROR", f"Segfault{f' (exit {m.group(1)})' if m else ''}"
    # fallback
    return "ERROR", re.sub(r"\s+", " ", p)[:90]


def err_signature(short):
    """Group errors into coarse families for the reason chart."""
    if not short.startswith(("TT_FATAL", "TT_THROW")):
        return short
    # keep "KIND file:line" as the signature (drops the variable backtrace tail)
    m = re.match(r"(TT_(?:FATAL|THROW) [\w.]+:\d+)", short)
    return m.group(1) if m else short


# --- ULP-error distribution -------------------------------------------------
# ULP spans 0 .. ~8e10, so linear buckets are useless (one giant bar at 0).
# Bucket on a log-ish scale instead. ULP is float-only (bf4/int rows are blank).
ULP_EDGES = [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 1024, float("inf")]
ULP_LABELS = ["0", "≤1", "≤2", "≤4", "≤8", "≤16", "≤32", "≤64", "≤128", "≤256", "≤1K", ">1K"]


def ulp_bucket(x):
    """Index into ULP_LABELS for a ULP value. 0 is its own exact bucket; the rest
    are 'first edge the value is <= '. Anything above 1024 lands in '>1K'."""
    if x <= 0:
        return 0
    for i in range(1, len(ULP_EDGES) - 1):
        if x <= ULP_EDGES[i]:
            return i
    return len(ULP_LABELS) - 1


def intern(v, store, idx):
    if v not in idx:
        idx[v] = len(store)
        store.append(v)
    return idx[v]


# --- dim aggregation in chart-friendly shape ------------------------------
def dim_obj(d):
    out = []
    for val, c in d.items():
        out.append({"value": val, **{s: c[s] for s in STATUS}, "total": sum(c.values())})
    # stable ordering
    out.sort(key=lambda x: -x["total"])
    return out


# --- run-to-run comparison ("what changed") --------------------------------
# Diff a board's current matrix (its root CSV) against its previous dated
# snapshot in history/workflow/. Reuses classify() so both sides bucket identically.
FAIL_STATES = {"PCC_FAIL", "ERROR", "NOT_IN_TTNN", "SKIP"}


def _to_float(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_matrix(path):
    """Path -> {(op,dt,ly,mem,bcast): {'s':status, 'pcc':float|None, 'ulp':float|None}}.
    Keys include broadcast mode so the 4 modes of a binary op are compared
    like-for-like. Skips '-' placeholder dims (NO_OP rows). 10-col schema:
    op,dtype,layout,mem,bcast,accepted,pcc_or_reason,input_range,pcc,ulp."""
    out = {}
    with open(path, newline="") as fh:
        rd = csv.reader(fh)
        next(rd, None)  # header
        for r in rd:
            if len(r) < 10 or r[1] == "-":
                continue
            status, _ = classify(r[5], r[6].strip())
            pcc = _to_float(r[8])
            ulp = _to_float(r[9])
            # keep the raw pcc_or_reason so the changes modal can show WHY a
            # config flipped (the TT_FATAL text for an ERR, the fail verdict for
            # a PCC fail). Only meaningful for non-PASS outcomes.
            out[(r[0], r[1], r[2], r[3], r[4])] = {"s": status, "pcc": pcc, "ulp": ulp, "r": r[6].strip()}
    return out


def _date_from(path):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    return m.group(1) if m else ""


def diff_kind(a, b):
    """Change kind for baseline `a` -> current `b` (both {'s','pcc','ulp'}),
    or None if nothing meaningful changed."""
    if a["s"] != b["s"]:
        if b["s"] == "PASS":
            return "improved"
        if a["s"] == "PASS":
            return "regressed"
        return "statusChange"
    # same status -> flag a meaningful numeric move (pcc by >=0.01 or ULP bucket)
    if a["pcc"] is not None and b["pcc"] is not None and abs(a["pcc"] - b["pcc"]) >= 0.01:
        return "shift"
    if a["ulp"] is not None and b["ulp"] is not None and ulp_bucket(a["ulp"]) != ulp_bucket(b["ulp"]):
        return "shift"
    return None


def compute_changes(board, root_csv):
    """Build the `changes` payload for one board: its current root CSV vs the
    previous dated snapshot in history/workflow/. Returns baseline=None when
    there aren't two snapshots to compare (e.g. a board's first run)."""
    dated = sorted(glob.glob(os.path.join(HISTORY_DIR, f"{CSV_PREFIX}{board}_*.csv")),
                   key=_date_from)
    base = {"baseline": None, "current": "current",
            "summary": {k: 0 for k in ("improved", "regressed", "new", "removed", "statusChange", "shifted")},
            "byOp": []}
    if len(dated) < 2:
        return base
    # newest dated file == current root CSV; baseline is the previous run
    base["current"] = _date_from(dated[-1]) or "current"
    base["baseline"] = _date_from(dated[-2]) or None
    try:
        cur = parse_matrix(root_csv)
        prev = parse_matrix(dated[-2])
    except OSError:
        return base

    per_op = defaultdict(lambda: {"items": [], "counts": Counter()})
    SUM = base["summary"]
    for key in set(cur) | set(prev):
        op, dt, ly, mem, bcast = key
        a, b = prev.get(key), cur.get(key)
        if a is None:
            kind = "new"; SUM["new"] += 1
            frm, to = None, b
        elif b is None:
            kind = "removed"; SUM["removed"] += 1
            frm, to = a, None
        else:
            kind = diff_kind(a, b)
            if kind is None:
                continue
            SUM["shifted" if kind == "shift" else kind] += 1
            frm, to = a, b
        rec = per_op[op]
        rec["counts"][kind] += 1
        # cap stored items per op; still count everything in the summary
        if len(rec["items"]) < 20:
            def _side(x):
                if x is None:
                    return None
                s = {"s": x["s"], "pcc": x["pcc"], "ulp": x["ulp"]}
                # carry the reason only for non-PASS outcomes (an ERR's TT_FATAL
                # text or a fail verdict) — that's what the hover explains. PASS
                # rows carry no useful reason. Trim to keep the payload lean.
                if x["s"] != "PASS" and x.get("r"):
                    s["r"] = x["r"][:400]
                return s
            rec["items"].append({"dt": dt, "ly": ly, "mem": mem, "bcast": bcast,
                                 "kind": kind, "from": _side(frm), "to": _side(to)})

    # rank ops: regressions first, then new/removed/changes, cap the list
    def op_weight(c):
        return (c["regressed"], c["removed"], c["statusChange"], c["new"], c["shift"], c["improved"])

    by_op = []
    for op, rec in per_op.items():
        c = rec["counts"]
        total_items = sum(c.values())
        by_op.append({
            "op": op,
            "counts": {k: c.get(k, 0) for k in ("improved", "regressed", "new", "removed", "statusChange", "shift")},
            "items": rec["items"],
            "more": max(0, total_items - len(rec["items"])),
        })
    by_op.sort(key=lambda o: op_weight(o["counts"]), reverse=True)
    base["byOp"] = by_op[:60]
    return base


# Board display labels for the cross-board Compare view (falls back to upper()).
BOARD_LABELS = {"n150": "N150", "p100a": "P100a"}


def _cmp_side(x):
    """One board's outcome for the Compare view, in the chgSide shape the frontend
    renders. None when the config is absent on that board. Carries the reason only
    for non-PASS outcomes (an ERR's TT_FATAL text / a fail verdict), trimmed."""
    if x is None:
        return None
    s = {"s": x["s"], "pcc": x["pcc"], "ulp": x["ulp"]}
    if x["s"] != "PASS" and x.get("r"):
        s["r"] = x["r"][:400]
    return s


def compute_compare(board_a, csv_a, board_b, csv_b):
    """Cross-board diff for the CURRENT data: every (op,dtype,layout,mem,bcast)
    config whose outcome differs between two boards. Neutral, both-ways — each
    differing config carries board a's side and board b's side; no baseline /
    improved / regressed framing. Reuses parse_matrix + diff_kind's threshold so
    a config counts as "differing" when the status differs, one side is missing,
    or there's a meaningful numeric move (pcc Δ>=0.01 or ULP-bucket change)."""
    try:
        A = parse_matrix(csv_a)
        B = parse_matrix(csv_b)
    except OSError:
        return None

    _KINDS = ("onlyA", "onlyB", "statusDiff", "numericDiff")
    per_op = defaultdict(lambda: {"items": [], "count": 0,
                                  "counts": {k: 0 for k in _KINDS}})
    summary = {"onlyA": 0, "onlyB": 0, "statusDiff": 0, "numericDiff": 0}
    for key in set(A) | set(B):
        op, dt, ly, mem, bcast = key
        a, b = A.get(key), B.get(key)
        if a is None:
            kind = "onlyB"
        elif b is None:
            kind = "onlyA"
        elif a["s"] != b["s"]:
            kind = "statusDiff"
        else:
            # same status on both boards — only a meaningful numeric move counts.
            k = diff_kind(a, b)
            if k != "shift":
                continue
            kind = "numericDiff"
        summary[kind] += 1
        rec = per_op[op]
        rec["count"] += 1
        rec["counts"][kind] += 1
        # `kind` rides on each item so the front-end summary chips can filter rows.
        if len(rec["items"]) < 20:
            rec["items"].append({"dt": dt, "ly": ly, "mem": mem, "bcast": bcast,
                                 "kind": kind, "a": _cmp_side(a), "b": _cmp_side(b)})

    by_op = []
    for op, rec in per_op.items():
        by_op.append({"op": op, "count": rec["count"], "counts": rec["counts"],
                      "items": rec["items"],
                      "more": max(0, rec["count"] - len(rec["items"]))})
    # most-differing ops first
    by_op.sort(key=lambda o: o["count"], reverse=True)

    return {
        "a": board_a, "b": board_b,
        "aLabel": BOARD_LABELS.get(board_a, board_a.upper()),
        "bLabel": BOARD_LABELS.get(board_b, board_b.upper()),
        "summary": summary,
        "byOp": by_op[:60],
    }


def build_board(board, csv_path):
    """Parse one board's root CSV and return its flat 16-key dashboard payload
    (the exact schema app.js renders). All accumulators are local so two boards
    never cross-contaminate."""
    rows = []                      # compact [opIdx, dtIdx, lyIdx, memIdx, statusIdx, reasonIdx, pcc|null, ulp|null, inputIdx, bcastIdx]
    ops, dts, lys, mems = [], [], [], []
    oI, dI, lI, mI = {}, {}, {}, {}
    reasons, rI = [], {}
    inputs, inI = [], {}            # interned input-range strings (only ~7 distinct)
    bcasts, bcI = [], {}            # interned broadcast modes: none / scalar / row / col

    status_counts = Counter()
    dim_counts = {"dtype": defaultdict(Counter), "layout": defaultdict(Counter),
                  "mem": defaultdict(Counter), "bcast": defaultdict(Counter)}
    op_counts = defaultdict(Counter)
    err_families = Counter()
    err_sample = {}
    ulp_overall = Counter()                       # bucket -> count, all float dtypes
    ulp_by_dtype = defaultdict(Counter)           # dtype -> bucket -> count

    with open(csv_path, newline="") as f:
        rd = csv.reader(f)
        next(rd)  # header
        # 10-col schema: op,dtype,layout,mem,bcast,accepted,pcc_or_reason,input_range,pcc,ulp
        for r in rd:
            if len(r) < 10:
                continue
            op, dt, ly, mem, bcast, accepted = r[0], r[1], r[2], r[3], r[4], r[5]
            p = r[6].strip()
            status, short = classify(accepted, p)

            # numeric Pearson correlation (CSV col 9, added by the probe). Empty for
            # FAIL/no-golden rows where PCC is undefined -> null. Rounded to 4dp to keep
            # the payload small; the matrix hover surfaces it.
            pcc = None
            if r[8].strip():
                try:
                    pcc = round(float(r[8]), 4)
                except ValueError:
                    pcc = None

            # max per-element ULP error (CSV col 10). Float-only; blank otherwise.
            # Keep the raw value for the matrix hover AND bucket it (overall +
            # per-dtype) for the accuracy distribution chart. Round to keep the
            # payload small: 2dp under 100, integer above (ULP can reach ~8e10).
            ulp = None
            if r[9].strip():
                try:
                    uval = float(r[9])
                    ulp = round(uval, 2) if uval < 100 else round(uval)
                    bi = ulp_bucket(uval)
                    ulp_overall[bi] += 1
                    ulp_by_dtype[dt][bi] += 1
                except ValueError:
                    ulp = None

            # input value range fed to the tensors (CSV col 8). Constant per
            # (op,dtype); only ~7 distinct strings, so intern and store the index.
            inp = r[7].strip()
            ini = intern(inp, inputs, inI) if inp else -1

            opi = intern(op, ops, oI)
            dti = intern(dt, dts, dI)
            lyi = intern(ly, lys, lI)
            memi = intern(mem, mems, mI)
            ri = intern(short, reasons, rI)
            bci = intern(bcast, bcasts, bcI)
            si = S_IDX[status]
            rows.append([opi, dti, lyi, memi, si, ri, pcc, ulp, ini, bci])

            status_counts[status] += 1
            if dt != "-":
                dim_counts["dtype"][dt][status] += 1
            if ly != "-":
                dim_counts["layout"][ly][status] += 1
            if mem != "-":
                dim_counts["mem"][mem][status] += 1
            if bcast != "-":
                dim_counts["bcast"][bcast][status] += 1
            op_counts[op][status] += 1
            if status == "ERROR":
                sig = err_signature(short)
                err_families[sig] += 1
                err_sample.setdefault(sig, short)

    # --- per-op leaderboard ---------------------------------------------------
    op_rows = []
    for op, c in op_counts.items():
        total = sum(c.values())
        runnable = total - c["SKIP"] - c["NOT_IN_TTNN"]
        passes = c["PASS"]
        pr = (passes / runnable) if runnable else None
        op_rows.append({
            "op": op, "total": total,
            "PASS": c["PASS"], "PCC_FAIL": c["PCC_FAIL"], "NO_GOLDEN": c["NO_GOLDEN"],
            "SKIP": c["SKIP"], "ERROR": c["ERROR"], "NOT_IN_TTNN": c["NOT_IN_TTNN"],
            "passRate": round(pr, 4) if pr is not None else None,
        })
    op_rows.sort(key=lambda x: (x["passRate"] if x["passRate"] is not None else 2, -x["ERROR"]))

    err_top = [{"sig": s, "count": n, "sample": err_sample[s]} for s, n in err_families.most_common(14)]

    # --- ULP distribution payload: bucket labels + overall counts + per-dtype ---
    # Only float dtypes appear (those with any ULP value). Shipped as parallel count
    # arrays aligned to `labels` so the chart just maps index -> bar height.
    ulp_dtypes = [d for d in dts if d != "-" and ulp_by_dtype.get(d)]
    ulp_dist = {
        "labels": ULP_LABELS,
        "overall": [ulp_overall.get(i, 0) for i in range(len(ULP_LABELS))],
        "total": sum(ulp_overall.values()),
        "byDtype": {
            d: [ulp_by_dtype[d].get(i, 0) for i in range(len(ULP_LABELS))]
            for d in ulp_dtypes
        },
    }

    changes = compute_changes(board, csv_path)

    return {
        "meta": {
            "total": len(rows),
            "ops": len(ops),
            "dtypes": [d for d in dts if d != "-"],
            "layouts": [l for l in lys if l != "-"],
            "mems": [m for m in mems if m != "-"],
            "bcasts": [b for b in bcasts if b != "-"],
            # build/refresh time — set when CF Workers Builds regenerates this file
            "generatedUTC": datetime.datetime.now(datetime.timezone.utc)
                .replace(microsecond=0).isoformat(),
            "generated": datetime.datetime.now(datetime.timezone.utc)
                .strftime("%Y-%m-%d %H:%M UTC"),
        },
        "statusList": STATUS,
        "statusCounts": {s: status_counts[s] for s in STATUS},
        "dims": {k: dim_obj(v) for k, v in dim_counts.items()},
        "ops": ops, "dts": dts, "lys": lys, "mems": mems, "bcasts": bcasts,
        "reasons": reasons,
        "inputs": inputs,
        "rows": rows,
        "opLeaderboard": op_rows,
        "errFamilies": err_top,
        "ulpDist": ulp_dist,
        "changes": changes,
    }


def discover_boards():
    """Find present per-board root CSVs -> [(board, path)] in display order.
    Board name is the CSV basename minus the shared prefix and .csv suffix."""
    found = {}
    for path in glob.glob(CSV_GLOB):
        name = os.path.basename(path)[len(CSV_PREFIX):-len(".csv")]
        if name:                       # guard against a stray bare-name match
            found[name] = path
    ordered = [b for b in BOARD_ORDER_PREF if b in found]
    ordered += sorted(b for b in found if b not in BOARD_ORDER_PREF)
    return [(b, found[b]) for b in ordered]


# --- live README badges (derived 100% from the CSV, never hand-edited) -------
# Shields "endpoint" JSON: the README points img.shields.io/endpoint?url=… at
# these, so the badge numbers always reflect the source CSV. Written into public/ so
# they ship to the live domain; gitignored like data.js (a build artifact).
# Badges reflect the DEFAULT board so the README's fixed shields URLs stay stable.
def write_badges(rows, status_counts, ops):
    badge_dir = os.path.join("public", "badges")
    os.makedirs(badge_dir, exist_ok=True)
    total = len(rows)
    sc = status_counts
    pass_rate = (sc.get("PASS", 0) / total * 100) if total else 0.0
    grp = lambda n: f"{n:,}"  # noqa: E731 — thousands separator
    badges = {
        "configs":  {"label": "configs",   "message": grp(total),          "color": "3b82f6"},
        "ops":      {"label": "ops",        "message": grp(len(ops)),       "color": "3b82f6"},
        "passrate": {"label": "pass rate",  "message": f"{pass_rate:.1f}%", "color": "10b981"},
        "pass":     {"label": "pass",       "message": grp(sc.get("PASS", 0)),     "color": "10b981"},
        "pccfail":  {"label": "pcc fail",   "message": grp(sc.get("PCC_FAIL", 0)), "color": "f59e0b"},
        "error":    {"label": "error",      "message": grp(sc.get("ERROR", 0)),    "color": "ef4444"},
    }
    for name, body in badges.items():
        body["schemaVersion"] = 1
        with open(os.path.join(badge_dir, name + ".json"), "w") as bf:
            json.dump(body, bf, separators=(",", ":"))
    print(f"wrote {len(badges)} badges -> {badge_dir}/")


def main():
    boards = discover_boards()
    if not boards:
        sys.exit(f"error: no {CSV_GLOB} found — nothing to build")

    payloads = {}
    for board, path in boards:
        payloads[board] = build_board(board, path)
        p = payloads[board]
        print(f"[{board}] {path}: ops={p['meta']['ops']} rows={p['meta']['total']} "
              f"status={p['statusCounts']}")

    board_order = [b for b, _ in boards]
    default_board = "n150" if "n150" in payloads else board_order[0]

    # Cross-board Compare payload (top-level, board-agnostic): only when >=2 boards
    # exist. Diffs the first two boards' root CSVs so the frontend can list every
    # config that behaves differently across hardware. None -> app.js hides the button.
    compare = None
    if len(boards) >= 2:
        (ba, pa), (bb, pb) = boards[0], boards[1]
        compare = compute_compare(ba, pa, bb, pb)

    data = {"boards": payloads, "defaultBoard": default_board,
            "boardOrder": board_order, "compare": compare}

    with open(OUT, "w") as f:
        f.write("window.DASH=")
        json.dump(data, f, separators=(",", ":"))
        f.write(";")
    print(f"wrote {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB)  "
          f"boards={board_order} default={default_board}")

    # Badges track the default board only (fixed README shields URLs).
    d = payloads[default_board]
    write_badges(d["rows"], Counter(d["statusCounts"]), d["ops"])
    worst = d["opLeaderboard"][:5]
    print("worst 5 ops (default board):", [(o["op"], o["passRate"]) for o in worst])


if __name__ == "__main__":
    main()
