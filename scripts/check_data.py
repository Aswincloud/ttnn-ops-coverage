#!/usr/bin/env python3
"""CI data-integrity gate for the TTNN Ops Coverage dashboard.

Validates the per-board sources of truth (eltwise_support_matrix_<board>.csv)
and the generated payload (public/data.js) — the invariants we otherwise verify
by hand on every push:

  1. Every board CSV RFC-parses; each row has the same column count as the header.
  2. The `pcc` column (when present) is numeric-or-empty — never malformed.
  3. `python3 process.py` runs clean and writes public/data.js.
  4. For each present board, window.DASH.boards[<board>].statusCounts sums to
     meta.total == that board's parsed row count (nothing silently dropped or
     double-counted during classification).

Exits non-zero with a clear message on the first failure. Runnable locally:
    python3 scripts/check_data.py
"""
import csv
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Per-board root CSVs: eltwise_support_matrix_<board>.csv. The trailing "_" in the
# glob excludes any legacy bare eltwise_support_matrix.csv.
CSV_GLOB = "eltwise_support_matrix_*.csv"
CSV_PREFIX = "eltwise_support_matrix_"
DATA_JS = ROOT / "public" / "data.js"


def fail(msg: str) -> "None":
    print(f"FAIL  {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"ok    {msg}")


def _board_of(path: Path) -> str:
    """eltwise_support_matrix_n150.csv -> n150 (same derivation as process.py)."""
    return path.name[len(CSV_PREFIX):-len(".csv")]


# --- 1 + 2: per-board source-CSV shape + pcc column -----------------------
def check_csvs() -> "dict[str, int]":
    paths = sorted(ROOT.glob(CSV_GLOB))
    if not paths:
        fail(f"no {CSV_GLOB} found under {ROOT}")
    # Pin the exact schema. process.py reads several columns by INDEX, so a
    # silently-inserted/reordered column (e.g. the bcast column added at
    # position 5) would shift every later field off-by-one and mis-classify
    # every row while still reconciling on counts. Catch that here.
    EXPECTED = ["op", "dtype", "layout", "mem", "bcast",
                "accepted", "pcc_or_reason", "input_range", "pcc", "ulp"]
    board_rows: "dict[str, int]" = {}
    for csv_path in paths:
        board = _board_of(csv_path)
        if not board:
            fail(f"{csv_path.name}: could not derive a board name")
        with csv_path.open(newline="") as f:
            rd = csv.reader(f)
            header = next(rd, None)
            if not header:
                fail(f"{csv_path.name} is empty (no header)")
            ncol = len(header)
            if header != EXPECTED:
                fail(f"{csv_path.name} header mismatch.\n     expected: {','.join(EXPECTED)}"
                     f"\n     got:      {','.join(header)}")
            pcc_i = header.index("pcc")
            rows = 0
            bad_pcc = 0
            for n, r in enumerate(rd, start=2):  # line 2 = first data row
                if len(r) != ncol:
                    fail(f"{csv_path.name} line {n}: {len(r)} columns, expected {ncol} "
                         f"(header: {','.join(header)})")
                rows += 1
                v = r[pcc_i].strip()
                if v:
                    try:
                        float(v)
                    except ValueError:
                        bad_pcc += 1
                        if bad_pcc <= 3:
                            print(f"      line {n}: non-numeric pcc {v!r}")
            if bad_pcc:
                fail(f"{csv_path.name} has {bad_pcc} malformed pcc value(s)")
        board_rows[board] = rows
        ok(f"{csv_path.name}: {rows} rows, {ncol} columns, consistent, pcc numeric-or-empty")
    ok(f"boards present: {', '.join(sorted(board_rows))}")
    return board_rows


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


# --- 4: data.js reconciles to each board's row count ----------------------
def check_payload(board_rows: "dict[str, int]") -> None:
    text = DATA_JS.read_text()
    m = re.search(r"window\.DASH\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        fail("public/data.js: could not find `window.DASH = {...}`")
    try:
        dash = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        fail(f"public/data.js: window.DASH is not valid JSON ({e})")

    boards = dash.get("boards")
    if not isinstance(boards, dict) or not boards:
        fail("data.js: missing/empty boards object")
    default_board = dash.get("defaultBoard")
    if default_board not in boards:
        fail(f"data.js: defaultBoard {default_board!r} not in boards {sorted(boards)}")

    # Every board CSV must produce a board payload and vice versa.
    if set(boards) != set(board_rows):
        fail(f"data.js: boards {sorted(boards)} != source CSVs {sorted(board_rows)}")

    for board, csv_rows in sorted(board_rows.items()):
        b = boards[board]
        sc = b.get("statusCounts")
        meta = b.get("meta", {})
        if not isinstance(sc, dict):
            fail(f"data.js[{board}]: missing statusCounts object")
        ssum = sum(sc.values())
        total = meta.get("total")
        if total is None:
            fail(f"data.js[{board}]: meta.total is missing")
        if ssum != total:
            fail(f"data.js[{board}]: statusCounts sum {ssum} != meta.total {total}")
        if total != csv_rows:
            fail(f"data.js[{board}]: meta.total {total} != CSV row count {csv_rows}")
        nrows = len(b.get("rows", []))
        if nrows != csv_rows:
            fail(f"data.js[{board}]: rows[] length {nrows} != CSV row count {csv_rows}")
        ok(f"data.js[{board}] reconciles: statusCounts sum == meta.total == rows == "
           f"{csv_rows}  {sc}")


def main() -> None:
    print("== data integrity ==")
    board_rows = check_csvs()
    build()
    check_payload(board_rows)
    print("== all data checks passed ==")


if __name__ == "__main__":
    main()
