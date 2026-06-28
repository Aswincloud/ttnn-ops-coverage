// Flat ESLint config (eslint v9+). Minimal on purpose — this is a hand-rolled,
// zero-runtime-dependency site, so we want syntax/correctness signal, not style
// dogma. Two source contexts with different globals:
//   public/app.js     -> browser (window, document, fetch, timers …)
//   worker/index.js   -> Cloudflare Workers (Response, Request, fetch, URL …)
// public/data.js is a generated build artifact and is ignored.

const browserGlobals = {
  window: "readonly", document: "readonly", fetch: "readonly",
  setTimeout: "readonly", clearTimeout: "readonly",
  setInterval: "readonly", clearInterval: "readonly",
  location: "readonly", navigator: "readonly", localStorage: "readonly",
  console: "readonly", getComputedStyle: "readonly", matchMedia: "readonly",
  requestAnimationFrame: "readonly",
  addEventListener: "readonly", removeEventListener: "readonly",
  innerWidth: "readonly", innerHeight: "readonly",
  URLSearchParams: "readonly", URL: "readonly",
};

const workerGlobals = {
  Response: "readonly", Request: "readonly", fetch: "readonly",
  URL: "readonly", console: "readonly", crypto: "readonly",
  addEventListener: "readonly", caches: "readonly",
};

const rules = {
  // correctness signal we actually care about:
  "no-undef": "error",          // catch typos / missing globals
  "no-unused-vars": ["warn", { args: "none", varsIgnorePattern: "^_" }],
  "no-dupe-keys": "error",
  "no-unreachable": "error",
  "no-cond-assign": "error",
  "no-constant-condition": ["error", { checkLoops: false }],
  "valid-typeof": "error",
};

export default [
  { ignores: ["public/data.js", "node_modules/**"] },
  {
    files: ["public/app.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: browserGlobals,
    },
    rules,
  },
  {
    files: ["worker/index.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: workerGlobals,
    },
    rules,
  },
  {
    files: ["scripts/*.mjs"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { process: "readonly", console: "readonly" },
    },
    rules,
  },
];
