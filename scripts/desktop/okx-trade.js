/**
 * OpenClaw - OKXOption Desktop Trade (Enhanced + Auto-Send)
 *
 * Features:
 *   - Full currency support (Crypto/Forex/Commodities/Indices)
 *   - Scroll to find currency in dropdown
 *   - Auto-send screenshot to Telegram after trade
 *
 * Supported currencies:
 *   Crypto: BTC, LTC, ETH, DOGE, LINK, BNB
 *   Forex: USD/CAD, EUR/USD, GBP/USD, EUR/JPY, USD/JPY, EUR/AUD, GBP/CAD, AUD/USD
 *   Commodities: Gold, Silver, Crude Oil, Brent Oil, Natural Gas
 *   Indices: ES, NQ, YM
 *
 * Run:
 *   node okx-trade.js --currency BTC --amount 60 --direction down --duration 60
 *   node okx-trade.js --currency Gold --amount 100 --direction up --duration 120 --telegram 7595498982
 */
const { chromium } = require('playwright');
const { execSync } = require('child_process');
const config = require('../okx-config');
const path = require('path');
const fs = require('fs');

// --------------- Parse CLI overrides ---------------
const args = process.argv.slice(2);
function getArg(name, fallback) {
  const idx = args.indexOf('--' + name);
  return idx !== -1 && args[idx + 1] ? args[idx + 1] : fallback;
}

const CURRENCY  = getArg('currency',  config.trade.currency);
const AMOUNT    = getArg('amount',    String(config.trade.amount));
const DURATION  = getArg('duration',  String(config.trade.duration));
const DIRECTION = getArg('direction', config.trade.direction).toLowerCase();
const ROUNDS    = parseInt(getArg('rounds', '1'), 10);
// Telegram ID: from CLI arg, env var, or default
const TELEGRAM_ID = getArg('telegram', process.env.OPENCLAW_TELEGRAM_ID || '7595498982');

const SCREENSHOT_DIR = path.join(__dirname, '..', 'screenshots');
if (!fs.existsSync(SCREENSHOT_DIR)) fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

// --------------- Currency Mapping ---------------
const CURRENCY_CATEGORIES = {
  'BTC': 'crypto', 'LTC': 'crypto', 'ETH': 'crypto', 
  'DOGE': 'crypto', 'LINK': 'crypto', 'BNB': 'crypto',
  'USD/CAD': 'forex', 'EUR/USD': 'forex', 'GBP/USD': 'forex', 
  'EUR/JPY': 'forex', 'USD/JPY': 'forex', 'EUR/AUD': 'forex',
  'GBP/CAD': 'forex', 'AUD/USD': 'forex',
  'GOLD': 'commodities', 'SILVER': 'commodities', 
  'CRUDE OIL': 'commodities', 'BRENT OIL': 'commodities', 
  'NATURAL GAS': 'commodities',
  'ES': 'indices', 'NQ': 'indices', 'YM': 'indices',
};

const CURRENCY_DISPLAY = {
  'GOLD': 'Gold', 'SILVER': 'Silver',
  'CRUDE OIL': 'Crude Oil', 'BRENT OIL': 'Brent Oil',
  'NATURAL GAS': 'Natural Gas',
};

function getCurrencyCategory(currency) {
  return CURRENCY_CATEGORIES[currency.toUpperCase()] || 'crypto';
}

function getCurrencyDisplay(currency) {
  return CURRENCY_DISPLAY[currency.toUpperCase()] || currency.toUpperCase();
}

function shot(page, name) {
  const p = path.join(SCREENSHOT_DIR, `trade-${name}.png`);
  console.log(`  [screenshot] ${p}`);
  return page.screenshot({ path: p });
}

function getWaitTime(dur) {
  return (parseInt(dur, 10) + 12) * 1000; // Reduced buffer for efficiency
}

// --------------- Send to Telegram ---------------
function sendToTelegram(imagePath, message, telegramId) {
  console.log(`  [telegram] Sending to ${telegramId}...`);
  try {
    const cmd = `openclaw message send --channel telegram --target "${telegramId}" --message "${message}" --media "${imagePath}"`;
    execSync(cmd, { encoding: 'utf-8', timeout: 30000 });
    console.log(`  [telegram] Sent!`);
    return true;
  } catch (err) {
    console.log(`  [telegram] Failed: ${err.message}`);
    return false;
  }
}

// --------------- Select Currency with Scroll ---------------
async function selectCurrency(page, currency) {
  const displayName = getCurrencyDisplay(currency);
  console.log(`  [currency] Selecting ${displayName}...`);

  // Step 1: Click on the Ant Design Select dropdown to open it
  console.log(`  [currency] Opening dropdown...`);
  const antSelect = page.locator('.ant-select').first();
  await antSelect.click();
  await page.waitForTimeout(600);

  // Step 2: Find the dropdown container (.ant-select-dropdown)
  const dropdown = page.locator('.ant-select-dropdown');
  
  // Step 3: Find and click the target currency, scrolling if needed
  const maxAttempts = 15;
  let found = false;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    // Try to find the item with title matching our currency
    const item = page.locator(`.ant-select-item[title="${displayName}"]`);
    
    if (await item.count() > 0) {
      // Check if it's visible
      const isVisible = await item.isVisible().catch(() => false);
      if (isVisible) {
        await item.click();
        console.log(`  [currency] Selected ${displayName}`);
        found = true;
        break;
      }
    }
    
    // Also try by text content
    const textItem = dropdown.locator(`.ant-select-item-option-content:text-is("${displayName}")`);
    if (await textItem.count() > 0) {
      const isVisible = await textItem.isVisible().catch(() => false);
      if (isVisible) {
        await textItem.click();
        console.log(`  [currency] Selected ${displayName} (text)`);
        found = true;
        break;
      }
    }

    // Not found, scroll the dropdown
    if (attempt < maxAttempts - 1) {
      console.log(`  [currency] Scrolling dropdown... (${attempt + 1}/${maxAttempts})`);
      
      // Scroll the dropdown container
      await page.evaluate(() => {
        const dd = document.querySelector('.ant-select-dropdown .rc-virtual-list-holder');
        if (dd) {
          dd.scrollBy({ top: 120, behavior: 'auto' });
        } else {
          // Fallback to dropdown itself
          const dd2 = document.querySelector('.ant-select-dropdown');
          if (dd2) dd2.scrollBy({ top: 120, behavior: 'auto' });
        }
      });
      await page.waitForTimeout(250);
    }
  }

  if (!found) {
    console.log(`  [currency] WARN: ${displayName} not found, trying force scroll...`);
    
    // Force scroll to bottom and back up
    await page.evaluate(() => {
      const dd = document.querySelector('.ant-select-dropdown .rc-virtual-list-holder') ||
                 document.querySelector('.ant-select-dropdown');
      if (dd) {
        dd.scrollTop = 9999; // Scroll to bottom
      }
    });
    await page.waitForTimeout(500);
    
    // Try one more time
    const item = page.locator(`.ant-select-item[title="${displayName}"]`);
    if (await item.count() > 0 && await item.isVisible()) {
      await item.click();
      console.log(`  [currency] Selected ${displayName} (after force scroll)`);
      found = true;
    }
  }

  if (!found) {
    console.log(`  [currency] ERROR: ${displayName} not found!`);
    // Close dropdown
    await page.keyboard.press('Escape');
  }

  await page.waitForTimeout(300);
  return found;
}

// --------------- Enter Amount ---------------
async function enterAmount(page, amount) {
  console.log(`  [amount] Setting ${amount}...`);
  
  const allInputs = page.locator('input:visible:not([type="password"]):not([type="hidden"])');
  const count = await allInputs.count();
  let targetInput = null;

  for (let i = 0; i < count; i++) {
    const inp = allInputs.nth(i);
    const currentVal = await inp.inputValue().catch(() => '');
    const placeholder = (await inp.getAttribute('placeholder') || '').toLowerCase();
    const type = await inp.getAttribute('type') || 'text';

    if (/account|user|email|phone|search|login/i.test(placeholder)) continue;
    if (/^\d+$/.test(currentVal) || type === 'number') {
      targetInput = inp;
      break;
    }
  }

  if (!targetInput && count > 0) {
    targetInput = allInputs.last();
  }

  if (targetInput) {
    await targetInput.click({ clickCount: 3 });
    await page.keyboard.press('Backspace');
    await page.keyboard.press('Control+A');
    await page.keyboard.press('Delete');
    await page.keyboard.type(String(amount), { delay: 30 });
    
    const newVal = await targetInput.inputValue().catch(() => '?');
    console.log(`  [amount] Set to ${newVal}`);
  } else {
    console.log('  [amount] WARN: Input not found');
  }
}

// --------------- Select Duration ---------------
async function selectDuration(page, duration) {
  console.log(`  [duration] Selecting ${duration}s...`);
  
  const clicked = await page.evaluate((dur) => {
    const target = dur + 's';
    const els = document.querySelectorAll('*');
    
    // First: exact own text match
    for (const el of els) {
      const ownText = Array.from(el.childNodes)
        .filter(n => n.nodeType === 3)
        .map(n => n.textContent.trim())
        .join('');
      if (ownText === target || ownText === dur + 'S') {
        el.click();
        return true;
      }
    }
    
    // Second: element containing duration text
    for (const el of els) {
      const t = el.textContent.trim();
      const r = el.getBoundingClientRect();
      if ((t === target || t.startsWith(target)) && r.width > 20 && r.width < 150 && r.height < 60) {
        el.click();
        return true;
      }
    }
    return false;
  }, duration);

  if (clicked) {
    console.log(`  [duration] Selected ${duration}s`);
  } else {
    const durBtn = page.getByText(duration + 's', { exact: true });
    if (await durBtn.count() > 0) {
      await durBtn.first().click();
      console.log(`  [duration] Selected ${duration}s (fallback)`);
    } else {
      console.log(`  [duration] WARN: ${duration}s not found`);
    }
  }
}

// --------------- Click Direction ---------------
async function clickDirection(page, direction) {
  const DIR = direction.toUpperCase();
  console.log(`  [direction] Clicking ${DIR}...`);

  // Try button role first
  const dirBtn = page.getByRole('button', { name: new RegExp(`^\\s*${DIR}\\s*$`, 'i') });
  if (await dirBtn.count() > 0) {
    await dirBtn.first().click();
    console.log(`  [direction] Clicked ${DIR}`);
    return;
  }

  // Try class-based selector
  const cls = direction === 'up'
    ? '[class*="up"], [class*="Up"], [class*="green"]'
    : '[class*="down"], [class*="Down"], [class*="red"]';
  const clsBtn = page.locator(cls).filter({ hasText: new RegExp(DIR, 'i') }).first();
  if (await clsBtn.count() > 0) {
    await clsBtn.click();
    console.log(`  [direction] Clicked ${DIR} (class)`);
    return;
  }

  // JS fallback
  await page.evaluate((d) => {
    for (const el of document.querySelectorAll('button, [role="button"], div, span')) {
      if (el.textContent.trim().toUpperCase() === d && el.offsetParent !== null) {
        el.click();
        return;
      }
    }
  }, DIR);
  console.log(`  [direction] Clicked ${DIR} (JS)`);
}

// --------------- Wait and Close Result ---------------
async function waitAndCloseResult(page, duration, currency, amount, direction, round) {
  const waitMs = getWaitTime(duration);
  console.log(`  [wait] Waiting ~${Math.round(waitMs / 1000)}s...`);

  const startTime = Date.now();
  const maxWait = waitMs + 20000;
  let resultInfo = { won: false, profit: '', details: '' };

  while (Date.now() - startTime < maxWait) {
    const resultPopup = page.getByText('Trade result');
    if (await resultPopup.count() > 0) {
      await page.waitForTimeout(800);

      // Extract result
      resultInfo = await page.evaluate(() => {
        let won = false;
        let profit = '';
        let details = '';
        
        // Check for profit
        for (const el of document.querySelectorAll('*')) {
          const t = el.textContent.trim();
          const match = t.match(/Profit:\s*(\d+\.?\d*)/i);
          if (match) {
            profit = match[1];
            won = parseFloat(profit) > 0;
            break;
          }
        }
        
        // Get trade details
        const rows = document.querySelectorAll('tr, [class*="row"]');
        for (const row of rows) {
          const cells = row.querySelectorAll('td, [class*="cell"]');
          if (cells.length >= 4) {
            details = Array.from(cells).map(c => c.textContent.trim()).join(' | ');
            break;
          }
        }
        
        return { won, profit, details };
      });

      console.log(`  [result] ${resultInfo.won ? '✅ Won' : '❌ Lost'} | Profit: ${resultInfo.profit || '0'}`);
      if (resultInfo.details) console.log(`  [result] ${resultInfo.details}`);

      // Screenshot
      const screenshotPath = path.join(SCREENSHOT_DIR, `trade-result-${Date.now()}.png`);
      await page.screenshot({ path: screenshotPath });
      console.log(`  [screenshot] ${screenshotPath}`);

      // Send to Telegram
      const displayCurrency = getCurrencyDisplay(currency);
      const emoji = resultInfo.won ? '✅' : '❌';
      const profitText = resultInfo.profit ? ` | Profit: $${resultInfo.profit}` : '';
      const message = `${emoji} ${displayCurrency} ${amount} ${direction.toUpperCase()} ${duration}s${profitText}`;
      sendToTelegram(screenshotPath, message, TELEGRAM_ID);

      // Close popup
      let closed = await page.evaluate(() => {
        const el = document.querySelector('.stx-ico-close');
        if (el) { el.click(); return true; }
        const dialog = document.querySelector('[class*="TradeResultDialog"]');
        if (dialog) {
          const btn = dialog.querySelector('[class*="close"]');
          if (btn) { btn.click(); return true; }
        }
        return false;
      });

      if (!closed) {
        const closeX = page.locator('.stx-ico-close');
        if (await closeX.count() > 0) {
          await closeX.first().click({ force: true });
          closed = true;
        }
      }

      console.log('  [result] Popup closed');
      await page.waitForTimeout(500);
      return resultInfo;
    }

    await page.waitForTimeout(1500);
  }

  console.log('  [warn] Result popup timeout, sending screenshot anyway...');
  
  // Still take screenshot and send even on timeout
  const screenshotPath = path.join(SCREENSHOT_DIR, `trade-timeout-${Date.now()}.png`);
  await page.screenshot({ path: screenshotPath });
  console.log(`  [screenshot] ${screenshotPath}`);
  
  const displayCurrency = getCurrencyDisplay(currency);
  const message = `⚠️ ${displayCurrency} ${amount} ${direction.toUpperCase()} ${duration}s | 结果超时`;
  sendToTelegram(screenshotPath, message, TELEGRAM_ID);
  
  return resultInfo;
}

// --------------- Main ---------------
async function main() {
  const displayCurrency = getCurrencyDisplay(CURRENCY);
  const DIR = DIRECTION.toUpperCase();
  
  console.log('');
  console.log('======================================');
  console.log('  OpenClaw Trade (Desktop + Auto-Send)');
  console.log(`  Currency : ${displayCurrency}`);
  console.log(`  Amount   : ${AMOUNT}`);
  console.log(`  Duration : ${DURATION}s`);
  console.log(`  Direction: ${DIR}`);
  console.log(`  Rounds   : ${ROUNDS}`);
  console.log(`  Category : ${getCurrencyCategory(CURRENCY)}`);
  console.log(`  Telegram : ${TELEGRAM_ID}`);
  console.log('======================================\n');

  const browser = await chromium.launch({
    headless: config.browser.headless,
    slowMo: config.browser.slowMo,
  });

  const authFile = path.join(__dirname, '..', 'auth.json');
  const ctxOpts = {
    viewport: config.browser.viewport,
    locale: config.browser.locale,
  };
  if (fs.existsSync(authFile)) {
    ctxOpts.storageState = authFile;
    console.log('[init] Session restored');
  }

  const context = await browser.newContext(ctxOpts);
  context.setDefaultTimeout(config.timeout.element);
  const page = await context.newPage();

  page.on('dialog', async d => { await d.accept(); });

  try {
    console.log('[init] Opening trade page...');
    await page.goto(config.tradeUrl, { waitUntil: 'domcontentloaded', timeout: config.timeout.navigation });
    await page.waitForTimeout(1500);

    // Auto-login if needed
    const hasPasswordField = await page.locator('input[type="password"]').count();
    if (hasPasswordField > 0) {
      console.log('[login] Logging in...');
      const inputs = page.locator('input');
      await inputs.nth(0).fill(config.account);
      await inputs.nth(1).fill(config.password);
      const loginBtn = page.locator('button').filter({ hasText: /log\s*in|login|sign/i }).first();
      await loginBtn.click();
      await page.waitForTimeout(2500);
      await context.storageState({ path: authFile });
      console.log('[login] Done');
    }

    const results = [];

    for (let round = 1; round <= ROUNDS; round++) {
      console.log(`\n=== Round ${round}/${ROUNDS}: ${displayCurrency} ${AMOUNT} ${DIR} ${DURATION}s ===`);

      await selectCurrency(page, CURRENCY);
      await enterAmount(page, AMOUNT);
      await selectDuration(page, DURATION);
      await page.waitForTimeout(200);
      
      await shot(page, `round${round}-pre`);
      await clickDirection(page, DIRECTION);
      
      console.log(`  [order] Placed!`);
      const result = await waitAndCloseResult(page, DURATION, CURRENCY, AMOUNT, DIRECTION, round);
      results.push(result);

      if (round < ROUNDS) {
        await page.waitForTimeout(800);
      }
    }

    // Summary
    console.log('\n======================================');
    console.log('  Trade Summary');
    console.log('======================================');
    let wins = 0, losses = 0, totalProfit = 0;
    results.forEach((r, i) => {
      const emoji = r.won ? '✅' : '❌';
      const profit = r.profit ? parseFloat(r.profit) : 0;
      totalProfit += r.won ? profit : -parseFloat(AMOUNT);
      if (r.won) wins++; else losses++;
      console.log(`  Round ${i + 1}: ${emoji} Profit: ${r.profit || '0'}`);
    });
    console.log(`  Total: ${wins}W / ${losses}L`);
    console.log('======================================\n');

    await browser.close();
  } catch (error) {
    console.error('\n[error]', error.message);
    await shot(page, 'error');
    await browser.close();
  }
}

main().catch(console.error);
