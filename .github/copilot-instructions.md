# Copilot instructions — ttnn-ops-coverage

## Code review scope

Do **not** review generated support-matrix data files. These are machine-produced
snapshots, not hand-written code.

Skip:

- `eltwise_support_matrix_*.csv` — the current per-board generated matrices (e.g. `_n150`, `_p100a`)
- `history/**/*.csv` — dated per-board matrix snapshots (under `history/workflow/`)

Do continue to review everything else normally, **including** `package.json`
and `package-lock.json`.
