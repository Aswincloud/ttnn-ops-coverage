/**
 * @file e2e/smoke.spec.js
 * @copyright © 2025 Aswin. All rights reserved.
 * @author Aswin
 * @description End-to-end (Playwright) smoke tests for the coverage dashboard.
 */
import { test, expect } from '@playwright/test';

test('coverage page loads with real data wired in', async ({ page }) => {
  const resp = await page.goto('/');
  expect(resp?.ok()).toBeTruthy();

  // The static shell renders a real heading.
  await expect(page.getByRole('heading', { name: /coverage/i }).first()).toBeVisible();

  // process.py writes window.DASH into public/data.js. The shape is nested
  // per board — { boards:{<name>:{…}}, defaultBoard } — so resolve the default
  // board and assert IT is populated with rows (an empty payload should fail).
  const meta = await page.evaluate(() => {
    const d = window.DASH;
    if (!d || typeof d !== 'object') return null;
    const b = d?.boards?.[d.defaultBoard] ?? Object.values(d?.boards ?? {})[0];
    if (!b) return null;
    return { total: b?.meta?.total ?? 0, ops: b?.meta?.ops ?? 0 };
  });
  expect(meta, 'window.DASH populated by data.js').not.toBeNull();
  expect(meta.total, 'DASH.meta.total rows').toBeGreaterThan(0);
  expect(meta.ops, 'DASH.meta.ops count').toBeGreaterThan(0);
});

test('no uncaught exceptions on load', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e)));
  // goto already waits for 'load'; no redundant waitForLoadState needed.
  await page.goto('/');
  await expect(page.locator('#meta')).toBeVisible();
  expect(pageErrors, 'uncaught exceptions on load').toEqual([]);
});
