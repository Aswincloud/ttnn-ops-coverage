# Copilot instructions — ttnn-ops-coverage

## Code review scope

Do **not** review generated support-matrix data files. These are machine-produced
snapshots, not hand-written code.

Skip:

- `eltwise_support_matrix.csv` — the current generated matrix
- `history/**/*.csv` — dated matrix snapshots
- `data/workflow/**/*.csv` — per-board matrices from the daily tt-metal pipeline

Do continue to review everything else normally, **including** `package.json`
and `package-lock.json`.
