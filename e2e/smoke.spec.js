import { test, expect } from '@playwright/test';

test('coverage page loads and data is wired in', async ({ page }) => {
  const resp = await page.goto('/');
  expect(resp?.ok()).toBeTruthy();
  await expect(page.locator('body')).not.toBeEmpty();
  // process.py writes window.DASH into public/data.js; app.js consumes it.
  const hasData = await page.evaluate(
    () => typeof window.DASH !== 'undefined' && window.DASH !== null
  );
  expect(hasData, 'window.DASH populated by data.js').toBeTruthy();
});

test('no uncaught page errors on load', async ({ page }) => {
  // Track only real JS exceptions (pageerror). We avoid asserting on
  // console.error and avoid networkidle (analytics can keep the socket open),
  // which would make the test flaky.
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e)));
  await page.goto('/');
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1500); // let deferred scripts run
  expect(pageErrors, 'uncaught exceptions on load').toEqual([]);
});
