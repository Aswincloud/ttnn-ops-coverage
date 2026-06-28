# Eltwise Support Probe

`eltwise_support_probe.py` empirically maps which **configurations** every `ttnn`
eltwise op supports, and whether the result matches a torch golden reference.

For each op it sweeps every `dtype × layout × memory-config` combination, runs the
op on device, and records:
- **accepted** — did the op run without raising? (`OK` / `FAIL` / `NO_OP` / `CRASH`)
- **verdict** — does the output match the golden? (`pass` / `fail` / `nan` / a raw error)
- **input_range** — the value range fed to the inputs for that `(op, dtype)`
- **pcc** — the numeric Pearson correlation vs the golden (blank when undefined)
- **ulp** — max per-element error in ULP (float dtypes only; blank otherwise)

Results are written incrementally to `eltwise_support_matrix.csv` next to the script.

---

## Quick start

Activate the tt-metal env first (from the repo root):

```bash
export ARCH_NAME="wormhole_b0"
source python_env/bin/activate
```

Run the whole sweep in a single process (opens the device once — fastest):

```bash
python tests/ttnn/unit_tests/operations/eltwise/eltwise_support_probe.py
```

This **overwrites** `eltwise_support_matrix.csv` (writes the header, then all ops).

---

## Daily runs / dashboards

For a scheduled daily run, use `--dated` to keep a per-day snapshot:

```bash
python tests/ttnn/unit_tests/operations/eltwise/eltwise_support_probe.py --dated
```

This writes a date-stamped file under a `history/` folder next to the script:

```
history/eltwise_support_matrix_YYYY-MM-DD.csv
```

and also refreshes the stable `eltwise_support_matrix.csv` (a copy of today's run),
so a dashboard can always read one fixed "latest" path while `history/*.csv` powers
trend lines over time. Re-running on the same day overwrites that day's file.

Use `--out <path>` to write to an explicit path instead (overrides `--dated`).

Example cron line:

```bash
cd /home/ubuntu/tt-metal && export ARCH_NAME="wormhole_b0" && \
  source python_env/bin/activate && \
  python tests/ttnn/unit_tests/operations/eltwise/eltwise_support_probe.py --dated \
  >> /home/ubuntu/eltwise_probe.log 2>&1
```

---

## The axes

| Axis | Values |
|------|--------|
| dtype  | `bfloat16`, `bfloat8_b`, `bfloat4_b`, `float32`, `int32`, `uint32`, `uint16`, `uint8` |
| layout | `tile`, `rm` (row-major) |
| mem    | `dram`, `l1`, `height`, `width`, `block` |

- `dram` / `l1` are interleaved memory configs.
- `height` / `width` / `block` are **sharded** memory configs, built per-shape at
  runtime onto a single core (see `make_mem`), so they are valid on any hardware.

Default tensor shape is a single tile `1×1×32×32` (keeps the sweep fast). Ops that
need a larger tile-aligned shape are overridden in `PER_OP_SHAPE` (e.g. the GLU
family uses `1×1×32×64` because it splits the last dim in half).

Total = `299 ops × 8 dtypes × 2 layouts × 5 mems = 23,920 rows`.

---

## CSV output format

```
op,dtype,layout,mem,accepted,pcc_or_reason,input_range,pcc,ulp
add,bfloat16,tile,dram,OK,pass,[0.1..0.85],0.999987,1.000
add,uint8,tile,dram,FAIL,"TT_FATAL ... UINT8 is not supported ...",[1..49],,
acosh,float32,tile,dram,OK,pass,[1.1..5.0],0.999999,33607.000
sigmoid,int32,tile,dram,OK,fail,[1..49],,
```

| Column | Meaning |
|--------|---------|
| `accepted` | `OK` ran; `FAIL` op rejected the config; `NO_OP` name not in ttnn; `CRASH` subprocess died |
| `pcc_or_reason` | `pass` / `fail` / `fail(<pcc>)` / `nan` / `shape?` on success; full error text on `FAIL`/`CRASH` |
| `input_range` | value range fed to inputs: `[1..49]` for integers, `[lo..hi]` for floats (per-op `DOMAIN`) |
| `pcc` | numeric Pearson correlation vs golden (6 dp); blank when undefined (errored / no-golden / constant output) |
| `ulp` | max per-element error in ULP (3 dp); only for `bfloat16` / `bfloat8_b` (measured in bf16) / `float32`; blank for `bfloat4_b`, integers, and errored rows |

PCC thresholds (used only for the `pass`/`fail` verdict): `0.99` (default), `0.97`
for `bfloat8_b`, `0.90` for `bfloat4_b`. Integer dtypes are compared with **exact
equality** (the `pcc` column is still filled in for reference, but it is not what
decides the verdict). ULP is informational and does not affect the verdict.

---

## Running a subset

Subset any axis with comma-separated env vars (handy for quick checks):

```bash
# only bf16 + float32, tile layout, dram + height-sharded
PROBE_DTYPES=bfloat16,float32 PROBE_LAYOUTS=tile PROBE_MEMS=dram,height \
  python .../eltwise_support_probe.py
```

| Env var | Subsets |
|---------|---------|
| `PROBE_DTYPES` | dtype axis |
| `PROBE_LAYOUTS` | layout axis |
| `PROBE_MEMS` | mem axis |

---

## Single-op mode (and crash isolation)

```bash
# probe one op and APPEND its rows to the existing CSV
python .../eltwise_support_probe.py --op gelu

# list every op name the probe knows about
python .../eltwise_support_probe.py --list-ops
```

`--op` opens the device, probes just that op, appends to the CSV, and exits. This is
the building block for a **crash-isolated** full run: drive each op in its own
subprocess so a hard segfault only loses that one op instead of the whole sweep.

```bash
P=tests/ttnn/unit_tests/operations/eltwise/eltwise_support_probe.py
CSV=tests/ttnn/unit_tests/operations/eltwise/eltwise_support_matrix.csv
echo "op,dtype,layout,mem,accepted,pcc_or_reason,input_range,pcc,ulp" > "$CSV"
for op in $(python "$P" --list-ops); do
  python "$P" --op "$op" >/tmp/probe_op.log 2>&1 \
    || echo "$op,-,-,-,CRASH,hard-crash,,," >> "$CSV"
done
```

**Trade-off:** single-process (no `--op`) opens the device once and is far faster,
but a single hard crash aborts everything. Per-op subprocesses are slower (one
device init per op) but survive crashes. Use single-process when no config
segfaults; use the subprocess driver when probing risky/new configs.

---

## Re-running just a few ops (overwrite-in-place)

Re-probe specific ops and merge them back, keeping the latest rows:

```bash
for op in glu geglu reglu swiglu; do python "$P" --op "$op"; done
# dedupe on (op,dtype,layout,mem), keeping the last occurrence
head -1 "$CSV" > /tmp/h.csv
tail -n +2 "$CSV" | tac | awk -F, '!seen[$1","$2","$3","$4]++' | tac > /tmp/b.csv
cat /tmp/h.csv /tmp/b.csv > "$CSV"
```

---

## How verdicts are produced (internals)

- **Op categories** (`BINARY`, `TERNARY`, `REDUCTION`, `GLU`, `QUANT`,
  `COMPLEX_CONSUMERS`) decide arity and how inputs/goldens are built.
- **Modes** are inferred from the name: `_bw` → backward, trailing `_` → in-place,
  else forward.
- **Goldens** come from `ttnn.get_golden_function`. Where none exists or it rejects
  the input, the probe falls back to manual torch references
  (`MANUAL_GOLDEN`, `MANUAL_BW_GOLDEN`, `MANUAL_REDUCE`).
- **Integer dtypes of float-math ops:** if the torch golden rejects int input, the
  probe casts int→float, runs the golden, truncates back to int, then compares
  (`call_golden` / `call_bw_golden`). Backward goldens additionally set
  `requires_grad` on the float-casted inputs.
- **Domains:** ops with restricted input ranges use `DOMAIN` (e.g. `acosh`,
  `lgamma`) so inputs stay valid.
- **References are quantized** to the device dtype before comparison
  (`quantize_ref`) so PCC measures kernel error, not input-quantisation noise.

---

## Adding a new op

1. Add the name to the `OPS` string.
2. If it's binary/ternary/reduction/etc., add it to the matching category set.
3. If it takes scalar args, add them to `UPARAMS` / `UKW` / `BPARAMS`
   (or `BW_OVERRIDE` for odd backward signatures).
4. If it needs a non-default shape, add it to `PER_OP_SHAPE`.
5. If torch has no golden for it, add one to the relevant `MANUAL_*` dict.
6. Probe it alone: `python .../eltwise_support_probe.py --op <name>`.
