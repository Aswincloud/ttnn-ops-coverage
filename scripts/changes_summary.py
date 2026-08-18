#!/usr/bin/env python3
"""Summarise what changed in the support matrix since the previous run.

Emits ONE JSON object on stdout describing each present board's diff against its
previous dated snapshot, plus a ready-to-post Slack `mrkdwn` body:

    {"changed": true, "total": 18, "text": "...", "mrkdwn": "...", "boards": [...]}

The diff itself is NOT reimplemented here — this reuses process.py's
compute_changes(), the exact same function that builds the dashboard's "Changes"
payload, so a Slack alert can never disagree with what the dashboard shows.

`changed` is true when any board has at least one improved / regressed / new /
removed / statusChange / shifted config. The daily workflow branches on it to
decide whether to notify at all.

We format the Slack body HERE rather than in the workflow's jq, because building a
multi-board, multi-op mrkdwn string in bash means hand-rolling JSON around op names
and TT_FATAL text — json.dumps escapes it correctly and for free.

Always prints valid JSON and exits 0 (even with zero changes, one board, or no
boards at all), so callers branch on `.changed`, never on an exit code.

Runnable locally:
    python3 scripts/changes_summary.py | jq .
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# process.py resolves CSV_GLOB and HISTORY_DIR *relatively*, so it only finds the
# boards and their history when the cwd is the repo root.
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import process  # noqa: E402  (import must follow the sys.path/chdir setup above)

DASHBOARD = "https://ttnn-ops-coverage.aswincloud.com/"

# compute_changes() summary keys in ATTENTION order — worst first. Mirrors
# process.py's op_weight() ranking so the message leads with regressions rather
# than with the good news. (Note the summary calls this kind "shifted" while the
# per-op counts call it "shift"; only the summary keys are needed here.)
SUMMARY_KINDS = [
    ("regressed",    ":red_circle:",               "regressed"),
    ("removed",      ":wastebasket:",              "removed"),
    ("statusChange", ":arrows_counterclockwise:",  "status-change"),
    ("new",          ":new:",                      "new"),
    ("improved",     ":large_green_circle:",       "improved"),
    ("shifted",      ":chart_with_upwards_trend:", "shifted"),
]

TOP_OPS = 5           # ops listed per board
# compute_changes() truncates its ranked byOp list (process.py:258 -> by_op[:60]),
# so len(byOp) is a FLOOR on the ops touched, not the true count. When we hit the
# cap we render "60+ ops" rather than a flat "60", which would badly under-report a
# sweeping change (e.g. 2026-07-02 -> 07-03 touched ~every op, not 60).
# Keep in sync with that slice in process.py.
BYOP_CAP = 60
BOARD_LABELS = process.BOARD_LABELS


def board_label(board):
    return BOARD_LABELS.get(board, board.upper())


def summarise_board(board, csv_path):
    """One board's diff, flattened for the notifier."""
    c = process.compute_changes(board, csv_path)
    summary = {k: int(c["summary"].get(k, 0)) for k, _e, _l in SUMMARY_KINDS}
    total = sum(summary.values())

    top = []
    for o in c["byOp"][:TOP_OPS]:
        counts = o["counts"]
        top.append({
            "op": o["op"],
            "total": sum(counts.values()),
            # flag ops that got WORSE so the message can mark them
            "worse": bool(counts.get("regressed", 0) or counts.get("removed", 0)),
        })

    return {
        "board": board,
        "label": board_label(board),
        "baseline": c["baseline"],
        "current": c["current"],
        "total": total,
        "summary": summary,
        "opsTouched": len(c["byOp"]),
        "opsCapped": len(c["byOp"]) >= BYOP_CAP,
        "topOps": top,
    }


def counts_line(summary):
    """`:red_circle: 2 regressed · :large_green_circle: 11 improved` — non-zero only."""
    parts = [f"{emoji} {summary[key]} {label}"
             for key, emoji, label in SUMMARY_KINDS if summary.get(key)]
    return " · ".join(parts)


def board_block(b):
    """The mrkdwn lines for one board."""
    label = f"*{b['label']}*"
    if b["baseline"] is None:
        return f"{label} · _no baseline snapshot yet_"
    span = f"{b['baseline']} → {b['current']}"
    if b["total"] == 0:
        return f"{label} · {span} · _no changes_"

    n_ops = b["opsTouched"]
    ops_count = f"{n_ops}+" if b["opsCapped"] else str(n_ops)
    lines = [f"{label} · {span} · *{b['total']}* "
             f"change{'' if b['total'] == 1 else 's'} "
             f"across {ops_count} op{'' if n_ops == 1 else 's'}",
             f"        {counts_line(b['summary'])}"]
    if b["topOps"]:
        ops = " · ".join(
            # :warning: marks an op carrying a regression/removal
            f"`{o['op']}` ({o['total']}){' :warning:' if o['worse'] else ''}"
            for o in b["topOps"]
        )
        more = b["opsTouched"] - len(b["topOps"])
        if more > 0:
            ops += f" · _+{more} more_"
        lines.append(f"        top ops: {ops}")
    return "\n".join(lines)


def one_line_text(boards, total):
    """Plain-text fallback — this is what Slack shows in push/preview."""
    changed = [b for b in boards if b["total"]]
    if not changed:
        return "Support matrix: no changes vs the previous run"
    per = ", ".join(f"{b['label']} {b['total']}" for b in changed)
    detail = counts_line(
        # merge the changed boards' summaries for the headline breakdown
        {key: sum(b["summary"].get(key, 0) for b in changed)
         for key, _e, _l in SUMMARY_KINDS}
    )
    # strip the emoji out of the fallback line — plain text only
    for _k, emoji, _l in SUMMARY_KINDS:
        detail = detail.replace(emoji + " ", "")
    return (f"Support matrix changed — {total} "
            f"change{'' if total == 1 else 's'} ({per}) — {detail}")


def main():
    boards = [summarise_board(b, p) for b, p in process.discover_boards()]
    total = sum(b["total"] for b in boards)

    out = {
        "changed": total > 0,
        "total": total,
        "text": one_line_text(boards, total),
        # Boards with 0 changes are still shown: "P100a · no changes" is useful
        # context — it says the other board held steady, rather than staying silent.
        "mrkdwn": "\n".join(board_block(b) for b in boards),
        "dashboard": DASHBOARD,
        "boards": boards,
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
