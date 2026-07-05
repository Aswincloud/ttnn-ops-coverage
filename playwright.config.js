/**
 * @file playwright.config.js
 * @copyright © 2025 Aswin. All rights reserved.
 * @author Aswin
 * @description Playwright E2E configuration.
 */
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: { baseURL: 'http://127.0.0.1:4173', trace: 'on-first-retry' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // Always (re)build data.js and start fresh so results never depend on a
    // stale public/data.js from a previously-running local server.
    command: 'python3 process.py && npx serve@14 public -l 4173 -n',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
