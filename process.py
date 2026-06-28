#!/usr/bin/env python3
"""Transform ops.csv into a compact data.js for the dashboard."""
import csv, re, json, datetime
from collections import defaultdict, Counter

SRC = "ops.csv"
OUT = "public/data.js"

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


rows = []                      # compact [opIdx, dtIdx, lyIdx, memIdx, statusIdx, reasonIdx, pcc|null, ulp|null, inputIdx]
ops, dts, lys, mems = [], [], [], []
oI, dI, lI, mI = {}, {}, {}, {}
reasons, rI = [], {}
inputs, inI = [], {}            # interned input-range strings (only ~7 distinct)

status_counts = Counter()
dim_counts = {"dtype": defaultdict(Counter), "layout": defaultdict(Counter), "mem": defaultdict(Counter)}
op_counts = defaultdict(Counter)
err_families = Counter()
err_sample = {}

# --- ULP-error distribution -------------------------------------------------
# ULP spans 0 .. ~8e10, so linear buckets are useless (one giant bar at 0).
# Bucket on a log-ish scale instead. ULP is float-only (bf4/int rows are blank).
ULP_EDGES = [0, 1, 2, 4, 8, 16, 32, 64, 128, 256, 1024, float("inf")]
ULP_LABELS = ["0", "≤1", "≤2", "≤4", "≤8", "≤16", "≤32", "≤64", "≤128", "≤256", "≤1K", ">1K"]
ulp_overall = Counter()                       # bucket -> count, all float dtypes
ulp_by_dtype = defaultdict(Counter)           # dtype -> bucket -> count


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


with open(SRC, newline="") as f:
    rd = csv.reader(f)
    next(rd)  # header
    for r in rd:
        if len(r) < 6:
            continue
        op, dt, ly, mem, accepted = r[0], r[1], r[2], r[3], r[4]
        p = r[5].strip()
        status, short = classify(accepted, p)

        # numeric Pearson correlation (CSV col 7, added by the probe). Empty for
        # FAIL/no-golden rows where PCC is undefined -> null. Rounded to 4dp to keep
        # the payload small; the matrix hover surfaces it.
        pcc = None
        if len(r) >= 8 and r[7].strip():
            try:
                pcc = round(float(r[7]), 4)
            except ValueError:
                pcc = None

        # max per-element ULP error (CSV col 9). Float-only; blank otherwise.
        # Keep the raw value for the matrix hover AND bucket it (overall +
        # per-dtype) for the accuracy distribution chart. Round to keep the
        # payload small: 2dp under 100, integer above (ULP can reach ~8e10).
        ulp = None
        if len(r) >= 9 and r[8].strip():
            try:
                uval = float(r[8])
                ulp = round(uval, 2) if uval < 100 else round(uval)
                bi = ulp_bucket(uval)
                ulp_overall[bi] += 1
                ulp_by_dtype[dt][bi] += 1
            except ValueError:
                ulp = None

        # input value range fed to the tensors (CSV col 7). Constant per
        # (op,dtype); only ~7 distinct strings, so intern and store the index.
        inp = r[6].strip() if len(r) >= 7 else ""
        ini = intern(inp, inputs, inI) if inp else -1

        opi = intern(op, ops, oI)
        dti = intern(dt, dts, dI)
        lyi = intern(ly, lys, lI)
        memi = intern(mem, mems, mI)
        ri = intern(short, reasons, rI)
        si = S_IDX[status]
        rows.append([opi, dti, lyi, memi, si, ri, pcc, ulp, ini])

        status_counts[status] += 1
        if dt != "-":
            dim_counts["dtype"][dt][status] += 1
        if ly != "-":
            dim_counts["layout"][ly][status] += 1
        if mem != "-":
            dim_counts["mem"][mem][status] += 1
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

# --- dim aggregation in chart-friendly shape ------------------------------
def dim_obj(d):
    out = []
    for val, c in d.items():
        out.append({"value": val, **{s: c[s] for s in STATUS}, "total": sum(c.values())})
    # stable ordering
    out.sort(key=lambda x: -x["total"])
    return out

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

data = {
    "meta": {
        "total": len(rows),
        "ops": len(ops),
        "dtypes": [d for d in dts if d != "-"],
        "layouts": [l for l in lys if l != "-"],
        "mems": [m for m in mems if m != "-"],
        # build/refresh time — set when CF Workers Builds regenerates this file
        "generatedUTC": datetime.datetime.now(datetime.timezone.utc)
            .replace(microsecond=0).isoformat(),
        "generated": datetime.datetime.now(datetime.timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"),
    },
    "statusList": STATUS,
    "statusCounts": {s: status_counts[s] for s in STATUS},
    "dims": {k: dim_obj(v) for k, v in dim_counts.items()},
    "ops": ops, "dts": dts, "lys": lys, "mems": mems,
    "reasons": reasons,
    "inputs": inputs,
    "rows": rows,
    "opLeaderboard": op_rows,
    "errFamilies": err_top,
    "ulpDist": ulp_dist,
}

with open(OUT, "w") as f:
    f.write("window.DASH=")
    json.dump(data, f, separators=(",", ":"))
    f.write(";")

import os
print(f"wrote {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB)")
print("status:", dict(status_counts))
print("ops:", len(ops), "rows:", len(rows), "reasons:", len(reasons))
print("worst 5 ops:", [(o['op'], o['passRate']) for o in op_rows[:5]])
