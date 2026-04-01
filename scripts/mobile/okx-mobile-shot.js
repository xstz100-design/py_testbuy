/**
 * OpenClaw - Mobile Screenshot
 * Strategy: Login with desktop viewport first (proven working),
 * save session, then reopen with mobile viewport to screenshot.
 */
const { chromium, devices } = require('playwright');
const config = require('../okx-config');
const path = require('path');
const fs = require('fs');

const shotDir = path.join(__dirname, '..', 'screenshots');
const authFile = path.join(__dirname, '..', 'auth.json');
if (!fs.existsSync(shotDir)) fs.mkdirSync(shotDir, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: false, slowMo: 80 });

  // ===== Phase 1: Login with desktop viewport =====
  console.log('[phase1] Login with desktop viewport...');
  const desktopCtx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN',
  });
  const dPage = await desktopCtx.newPage();
  await dPage.goto(config.tradeUrl, { waitUntil: 'networkidle', timeout: 30000 });
  await dPage.waitForTimeout(2000);

  const hasPwd = await dPage.locator('input[type="password"]').count();
  if (hasPwd > 0) {
    console.log('[login] Filling credentials...');
    const inputs = dPage.locator('input');
    await inputs.nth(0).fill(config.account);
    await inputs.nth(1).fill(config.password);
    const loginBtn = dPage.locator('button, [role="button"]')
      .filter({ hasText: /log\s*in|login|sign\s*in/i }).first();
    if (await loginBtn.count() > 0) {
      await loginBtn.click();
    } else {
      await dPage.locator('button').first().click();
    }
    await dPage.waitForTimeout(4000);
    await dPage.waitForLoadState('networkidle').catch(() => {});
    console.log('[login] Done');
  } else {
    console.log('[login] Already logged in (no password field)');
  }

  // Save session cookies
  await desktopCtx.storageState({ path: authFile });
  console.log('[session] Saved to', authFile);
  await dPage.close();
  await desktopCtx.close();

  // ===== Phase 2: Open with mobile viewport using saved session =====
  console.log('\n[phase2] Opening mobile viewport with saved session...');
  const mobile = devices['iPhone 14 Pro Max'];
  const mobileCtx = await browser.newContext({
    ...mobile,
    locale: 'zh-CN',
    storageState: authFile,
  });
  const mPage = await mobileCtx.newPage();
  await mPage.goto(config.tradeUrl, { waitUntil: 'networkidle', timeout: 30000 });
  await mPage.waitForTimeout(4000);

  // Verify logged in - check if password field is absent
  const stillNeedLogin = await mPage.locator('input[type="password"]').count();
  if (stillNeedLogin > 0) {
    console.log('[warn] Mobile page still shows login form, retrying login...');
    const inputs = mPage.locator('input');
    await inputs.nth(0).fill(config.account);
    await inputs.nth(1).fill(config.password);
    // On mobile, try JS click on any button
    await mPage.evaluate(() => {
      const btns = document.querySelectorAll('button, [role="button"], input[type="submit"], .btn, [class*="login"], [class*="Login"]');
      for (const b of btns) {
        if (b.offsetParent !== null && b.getBoundingClientRect().height > 0) {
          b.click(); return;
        }
      }
    });
    await mPage.waitForTimeout(4000);
    await mPage.waitForLoadState('networkidle').catch(() => {});
  }

  // Take screenshots
  console.log('[shot] Taking mobile screenshots...');
  await mPage.screenshot({ path: path.join(shotDir, 'mobile-trade.png'), fullPage: false });
  console.log('[shot] mobile-trade.png (viewport)');

  await mPage.evaluate(() => window.scrollBy(0, 400));
  await mPage.waitForTimeout(800);
  await mPage.screenshot({ path: path.join(shotDir, 'mobile-trade-scroll.png'), fullPage: false });
  console.log('[shot] mobile-trade-scroll.png (scrolled)');

  await mPage.screenshot({ path: path.join(shotDir, 'mobile-trade-full.png'), fullPage: true });
  console.log('[shot] mobile-trade-full.png (full page)');

  console.log('\n[done] All mobile screenshots saved to ./screenshots/');
  await browser.close();
})();
