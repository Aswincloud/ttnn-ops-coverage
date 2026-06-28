#!/usr/bin/env python3
"""CI data-integrity gate for the TTNN Ops Coverage dashboard.

Validates the single source of truth (ops.csv) and the generated payload
(public/data.js) — the invariants we otherwise verify by hand on every push:

  1. ops.csv RFC-parses; every row has the same column count as the header.
  2. The `pcc` column (when present) is numeric-or-empty — never malformed.
  3. `python3 process.py` runs clean and writes public/data.js.
  4. window.DASH.statusCounts sums to meta.total == the parsed row count
     (nothing silently dropped or double-counted during classification).

Exits non-zero with a clear message on the first failure. Runnable locally:
    python3 scripts/check_data.py
"""
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "ops.csv"
DATA_JS = ROOT / "public" / "data.js"


def fail(msg: str) -> "None":
    print(f"FAIL  {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"ok    {msg}")


# --- 1 + 2: ops.csv shape + pcc column ------------------------------------
def check_csv() -> int:
    if not CSV.exists():
        fail(f"{CSV} does not exist")
    with CSV.open(newline="") as f:
        rd = csv.reader(f)
        header = next(rd, None)
        if not header:
            fail("ops.csv is empty (no header)")
        ncol = len(header)
        # Pin the exact schema. process.py reads several columns by INDEX, so a
        # silently-inserted/reordered column (e.g. the bcast column added at
        # position 5) would shift every later field off-by-one and mis-classify
        # every row while still reconciling on counts. Catch that here.
        EXPECTED = ["op", "dtype", "layout", "mem", "bcast",
                    "accepted", "pcc_or_reason", "input_range", "pcc", "ulp"]
        if header != EXPECTED:
            fail(f"ops.csv header mismatch.\n     expected: {','.join(EXPECTED)}"
                 f"\n     got:      {','.join(header)}")
        has_pcc = "pcc" in header
        pcc_i = header.index("pcc") if has_pcc else -1
        rows = 0
        bad_pcc = 0
        for n, r in enumerate(rd, start=2):  # line 2 = first data row
            if len(r) != ncol:
                fail(f"ops.csv line {n}: {len(r)} columns, expected {ncol} "
                     f"(header: {','.join(header)})")
            rows += 1
            if has_pcc:
                v = r[pcc_i].strip()
                if v:
                    try:
                        float(v)
                    except ValueError:
                        bad_pcc += 1
                        if bad_pcc <= 3:
                            print(f"      line {n}: non-numeric pcc {v!r}")
        if bad_pcc:
            fail(f"ops.csv has {bad_pcc} malformed pcc value(s)")
    ok(f"ops.csv: {rows} rows, {ncol} columns, consistent"
       + (", pcc numeric-or-empty" if has_pcc else " (no pcc column)"))
    return rows


# --- 3: process.py builds data.js -----------------------------------------
def build() -> None:
    res = subprocess.run([sys.executable, "process.py"],
                         cwd=ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr, file=sys.stderr)
        fail("process.py exited non-zero")
    if not DATA_JS.exists():
        fail("process.py did not write public/data.js")
    ok("process.py built public/data.js")


# --- 4: data.js reconciles to the row count -------------------------------
def check_payload(csv_rows: int) -> None:
    text = DATA_JS.read_text()
    m = re.search(r"window\.DASH\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        fail("public/data.js: could not find `window.DASH = {...}`")
    try:
        dash = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        fail(f"public/data.js: window.DASH is not valid JSON ({e})")

    sc = dash.get("statusCounts")
    meta = dash.get("meta", {})
    if not isinstance(sc, dict):
        fail("data.js: missing statusCounts object")
    ssum = sum(sc.values())
    total = meta.get("total")

    if total is None:
        fail("data.js: meta.total is missing")
    if ssum != total:
        fail(f"data.js: statusCounts sum {ssum} != meta.total {total}")
    if total != csv_rows:
        fail(f"data.js: meta.total {total} != ops.csv row count {csv_rows}")

    nrows = len(dash.get("rows", []))
    if nrows != csv_rows:
        fail(f"data.js: rows[] length {nrows} != ops.csv row count {csv_rows}")

    ok(f"data.js reconciles: statusCounts sum == meta.total == rows == "
       f"{csv_rows}  {sc}")


def main() -> None:
    print("== data integrity ==")
    csv_rows = check_csv()
    build()
    check_payload(csv_rows)
    print("== all data checks passed ==")


if __name__ == "__main__":
    main()
