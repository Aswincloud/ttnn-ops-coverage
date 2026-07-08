// CI code gate for the TTNN Ops Coverage dashboard.
//
// Validates the JavaScript that ships to the edge — the checks we otherwise run
// by hand on every push:
//
//   1. app.js and worker/index.js are syntactically valid (parse without error).
//   2. data.js boots: requiring it populates window.DASH and the payload
//      reconciles (statusCounts sum == meta.total == rows length).
//   3. data.js is NOT tracked by git (it's a generated build artifact — must
//      stay gitignored so the source CSV remains the single source of truth).
//
// Runnable locally:  node scripts/check_code.mjs
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let failed = 0;
const fail = (m) => { console.log(`FAIL  ${m}`); failed++; };
const ok = (m) => console.log(`ok    ${m}`);

// --- 1: syntax check via `node --check` -----------------------------------
for (const rel of ["public/app.js", "worker/index.js"]) {
  try {
    execFileSync(process.execPath, ["--check", join(ROOT, rel)], { stdio: "pipe" });
    ok(`${rel}: valid syntax`);
  } catch (e) {
    fail(`${rel}: syntax error\n${e.stderr?.toString() || e.message}`);
  }
}

// --- 2: data.js boots + reconciles ----------------------------------------
try {
  const code = readFileSync(join(ROOT, "public/data.js"), "utf8");
  const sandbox = { window: {} };
  vm.runInNewContext(code, sandbox, { timeout: 5000 });
  const RAW = sandbox.window.DASH;
  // Nested per-board shape: window.DASH = { boards:{<name>:{…flat…}}, defaultBoard, boardOrder }.
  const boards = RAW?.boards;
  if (!RAW) {
    fail("data.js: did not set window.DASH");
  } else if (!boards || typeof boards !== "object" || !Object.keys(boards).length) {
    fail("data.js: missing/empty boards object");
  } else if (!boards[RAW.defaultBoard]) {
    fail(`data.js: defaultBoard ${JSON.stringify(RAW.defaultBoard)} not in boards ${JSON.stringify(Object.keys(boards))}`);
  } else {
    // Run the reconcile + broadcast-axis guards PER board.
    for (const [name, D] of Object.entries(boards)) {
      // Shape-guard first so a malformed board fails WITH its name, not via the
      // generic outer catch (which loses which board was bad).
      if (!D || typeof D !== "object" || !D.statusCounts || !Array.isArray(D.rows)) {
        fail(`data.js[${name}]: malformed payload (missing statusCounts or rows[])`);
        continue;
      }
      const sum = Object.values(D.statusCounts).reduce((a, b) => a + b, 0);
      const total = D.meta?.total;
      const nrows = D.rows.length;
      if (sum !== total) fail(`data.js[${name}]: statusCounts sum ${sum} != meta.total ${total}`);
      else if (nrows !== total) fail(`data.js[${name}]: rows length ${nrows} != meta.total ${total}`);
      else ok(`data.js[${name}] boots + reconciles (${total} configs, ${D.opLeaderboard?.length ?? "?"} ops)`);

      // broadcast axis must be present (guards against a regression that drops it)
      const bc = D.meta?.bcasts;
      if (!Array.isArray(bc) || !bc.includes("none")) {
        fail(`data.js[${name}]: meta.bcasts missing/invalid (expected an array incl. "none") — got ${JSON.stringify(bc)}`);
      } else if (!Array.isArray(D.dims?.bcast) || !D.dims.bcast.length) {
        fail(`data.js[${name}]: dims.bcast missing/empty (broadcast axis not aggregated)`);
      } else if (!D.rows.every((r) => typeof r[9] === "number")) {
        fail(`data.js[${name}]: some rows lack the bcastIdx (index 9) slot`);
      } else {
        ok(`data.js[${name}] broadcast axis present (modes: ${bc.join(", ")})`);
      }
    }
  }
} catch (e) {
  fail(`data.js: failed to evaluate — ${e.message}`);
}

// --- 3: build artifacts must stay gitignored, never committed -------------
// data.js + the README badge JSON are both generated from the source CSV on
// every build. Committing either would let a stale snapshot drift from the CSV,
// so `git ls-files` (TRACKED files) must list neither.
try {
  const tracked = execFileSync("git", ["ls-files", "public/data.js", "public/badges"],
    { cwd: ROOT, stdio: "pipe" }).toString().trim();
  if (tracked) fail(`generated build artifact(s) tracked by git — must stay gitignored (generated from the source CSV):\n     ${tracked.split("\n").join("\n     ")}`);
  else ok("public/data.js + public/badges are not tracked (correctly gitignored)");
} catch {
  // not a git repo (e.g. tarball CI) — skip rather than fail
  ok("git not available — skipping tracked-file check");
}

if (failed) {
  console.log(`\n== ${failed} code check(s) failed ==`);
  process.exit(1);
}
console.log("\n== all code checks passed ==");
