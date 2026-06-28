// CI code gate for the TTNN Ops Coverage dashboard.
//
// Validates the JavaScript that ships to the edge — the checks we otherwise run
// by hand on every push:
//
//   1. app.js and worker/index.js are syntactically valid (parse without error).
//   2. data.js boots: requiring it populates window.DASH and the payload
//      reconciles (statusCounts sum == meta.total == rows length).
//   3. data.js is NOT tracked by git (it's a generated build artifact — must
//      stay gitignored so ops.csv remains the single source of truth).
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
  const D = sandbox.window.DASH;
  if (!D) {
    fail("data.js: did not set window.DASH");
  } else {
    const sum = Object.values(D.statusCounts).reduce((a, b) => a + b, 0);
    const total = D.meta?.total;
    const nrows = (D.rows || []).length;
    if (sum !== total) fail(`data.js: statusCounts sum ${sum} != meta.total ${total}`);
    else if (nrows !== total) fail(`data.js: rows length ${nrows} != meta.total ${total}`);
    else ok(`data.js boots + reconciles (${total} configs, ${D.opLeaderboard?.length ?? "?"} ops)`);
  }
} catch (e) {
  fail(`data.js: failed to evaluate — ${e.message}`);
}

// --- 3: data.js must be a gitignored build artifact, never committed ------
try {
  // `git ls-files` lists TRACKED files; data.js must not appear.
  const tracked = execFileSync("git", ["ls-files", "public/data.js"],
    { cwd: ROOT, stdio: "pipe" }).toString().trim();
  if (tracked) fail("public/data.js is tracked by git — it must stay gitignored (generated from ops.csv)");
  else ok("public/data.js is not tracked (correctly gitignored)");
} catch {
  // not a git repo (e.g. tarball CI) — skip rather than fail
  ok("git not available — skipping tracked-file check");
}

if (failed) {
  console.log(`\n== ${failed} code check(s) failed ==`);
  process.exit(1);
}
console.log("\n== all code checks passed ==");
