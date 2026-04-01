const { chromium } = require('playwright');
const config = require('../okx-config');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({ headless: false, slowMo: 100 });
  const authFile = path.join(__dirname, '..', 'auth.json');
  const ctxOpts = { viewport: { width: 1440, height: 900 } };
  if (fs.existsSync(authFile)) ctxOpts.storageState = authFile;
  
  const context = await browser.newContext(ctxOpts);
  const page = await context.newPage();
  
  await page.goto(config.tradeUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2000);
  
  // Login if needed
  const hasPwd = await page.locator('input[type="password"]').count();
  if (hasPwd > 0) {
    const inputs = page.locator('input');
    await inputs.nth(0).fill(config.account);
    await inputs.nth(1).fill(config.password);
    await page.locator('button').first().click();
    await page.waitForTimeout(3000);
  }
  
  // Click dropdown
  console.log('Clicking dropdown...');
  const selector = await page.locator('.ant-select').first();
  await selector.click();
  await page.waitForTimeout(1000);
  
  // Screenshot
  await page.screenshot({ path: path.join(__dirname, '..', 'screenshots', 'dropdown-open.png') });
  console.log('Screenshot saved');
  
  // List all HTML of dropdown
  const html = await page.evaluate(() => {
    const dropdown = document.querySelector('.ant-select-dropdown');
    return dropdown ? dropdown.outerHTML.substring(0, 3000) : 'No dropdown found';
  });
  console.log('Dropdown HTML:', html);
  
  await page.waitForTimeout(2000);
  await browser.close();
})();
