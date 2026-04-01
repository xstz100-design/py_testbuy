/**
 * OpenClaw - OKXOption Mobile Trade Execution (Enhanced + Auto-Send)
 *
 * Two-phase strategy:
 *   Phase 1: Desktop viewport login (proven reliable) → save session
 *   Phase 2: Mobile viewport (iPhone 14 Pro Max) → trade → screenshot → send to Telegram
 *
 * Mobile flow:
 *   Market list → Scroll to find currency → Click → Enter amount → Click UP/DOWN → Wait result → Screenshot → Send
 *
 * Supported currencies:
 *   Crypto: BTC, LTC, ETH, DOGE, LINK, BNB
 *   Forex: USD/CAD, EUR/USD, GBP/USD, EUR/JPY, USD/JPY, EUR/AUD, GBP/CAD, AUD/USD
 *   Commodities: Gold, Silver, Crude Oil, Brent Oil, Natural Gas
 *   Indices: ES, NQ, YM
 *
 * Run:
 *   node okx-mobile-trade.js --currency ETH --amount 50 --direction down
 *   node okx-mobile-trade.js --currency Gold --amount 100 --direction up --duration 120
 *   node okx-mobile-trade.js --currency "Crude Oil" --amount 60 --direction down
 *   node okx-mobile-trade.js --currency BTC --amount 60 --direction down --telegram 7595498982
 */
const { chromium, webkit, devices } = require('playwright');
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
const AUTH_FILE = path.join(__dirname, '..', 'auth.json');
if (!fs.existsSync(SCREENSHOT_DIR)) fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

// --------------- Currency Category Mapping ---------------
const CURRENCY_CATEGORIES = {
  // Crypto
  'BTC': 'crypto', 'LTC': 'crypto', 'ETH': 'crypto', 
  'DOGE': 'crypto', 'LINK': 'crypto', 'BNB': 'crypto',
  // Forex
  'USD/CAD': 'forex', 'EUR/USD': 'forex', 'GBP/USD': 'forex', 
  'EUR/JPY': 'forex', 'USD/JPY': 'forex', 'EUR/AUD': 'forex',
  'GBP/CAD': 'forex', 'AUD/USD': 'forex',
  // Commodities
  'GOLD': 'commodities', 'SILVER': 'commodities', 
  'CRUDE OIL': 'commodities', 'BRENT OIL': 'commodities', 
  'NATURAL GAS': 'commodities',
  // Indices
  'ES': 'indices', 'NQ': 'indices', 'YM': 'indices',
};

// Display names for matching on page
const CURRENCY_DISPLAY = {
  'GOLD': 'Gold',
  'SILVER': 'Silver',
  'CRUDE OIL': 'Crude Oil',
  'BRENT OIL': 'Brent Oil',
  'NATURAL GAS': 'Natural Gas',
};

function getCurrencyCategory(currency) {
  const upper = currency.toUpperCase();
  return CURRENCY_CATEGORIES[upper] || 'crypto';
}

function getCurrencyDisplay(currency) {
  const upper = currency.toUpperCase();
  return CURRENCY_DISPLAY[upper] || currency.toUpperCase();
}

function shot(page, name) {
  const p = path.join(SCREENSHOT_DIR, `mobile-${name}.png`);
  console.log(`  [screenshot] ${p}`);
  return page.screenshot({ path: p });
}

function getWaitTime(dur) {
  return (parseInt(dur, 10) + 15) * 1000;
}

// --------------- Send Screenshot to Telegram ---------------
function sendToTelegram(imagePath, message, telegramId) {
  console.log(`  [telegram] Sending screenshot to ${telegramId}...`);
  try {
    const cmd = `openclaw message send --channel telegram --target "${telegramId}" --message "${message}" --media "${imagePath}"`;
    execSync(cmd, { encoding: 'utf-8', timeout: 30000 });
    console.log(`  [telegram] Screenshot sent successfully!`);
    return true;
  } catch (err) {
    console.log(`  [telegram] Failed to send: ${err.message}`);
    return false;
  }
}

// --------------- Phase 1: Desktop Login (Chromium) ---------------
async function desktopLogin() {
  console.log('[phase1] Desktop login via Chromium...');
  const browser = await chromium.launch({ headless: true, slowMo: 0 });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(config.tradeUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3000);

  const hasPwd = await page.locator('input[type="password"]').count();
  if (hasPwd > 0) {
    console.log('  [login] Filling credentials...');
    const inputs = page.locator('input');
    await inputs.nth(0).fill(config.account);
    await inputs.nth(1).fill(config.password);
    await page.locator('button').first().click();
    await page.waitForTimeout(5000);
    console.log('  [login] Done');
  } else {
    console.log('  [login] Already logged in (session valid)');
  }

  await ctx.storageState({ path: AUTH_FILE });
  console.log('  [session] Saved to', AUTH_FILE);
  await page.close();
  await ctx.close();
  await browser.close();
}

// --------------- Phase 2: Mobile Trade (WebKit/Safari) ---------------
async function mobileLogin() {
  console.log('[phase2] Opening iPhone 14 Pro Max via WebKit (Safari)...');
  const mobile = devices['iPhone 14 Pro Max'];
  const browser = await webkit.launch({
    headless: config.browser.headless,
    slowMo: 80,
  });
  const ctx = await browser.newContext({ ...mobile, storageState: AUTH_FILE });
  const page = await ctx.newPage();
  await page.goto(config.tradeUrl, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(5000);

  const currentUrl = page.url();
  const isLoginPage = currentUrl.includes('#/login') || currentUrl.includes('/login');
  const hasPwd = await page.locator('input[type="password"]').count();

  if (isLoginPage || hasPwd > 0) {
    console.log(`  [warn] Login required (url=${isLoginPage}, pwd_field=${hasPwd > 0})`);

    if (hasPwd === 0) {
      console.log('  [warn] Waiting for login form to render...');
      try {
        await page.locator('input[type="password"]').waitFor({ state: 'visible', timeout: 10000 });
      } catch {
        console.log('  [warn] Password field did not appear, trying page refresh...');
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
        await page.waitForTimeout(5000);
      }
    }

    const inputs = page.locator('input');
    const inputCount = await inputs.count();
    if (inputCount >= 2) {
      await inputs.nth(0).fill(config.account);
      await inputs.nth(1).fill(config.password);
      const loginClicked = await page.evaluate(() => {
        const btn = document.querySelector('.loginbtm') || document.querySelector('button');
        if (btn) { btn.click(); return true; }
        return false;
      });
      if (!loginClicked) console.log('  [warn] Login button not found');
      await page.waitForTimeout(5000);

      await page.goto(config.tradeUrl, { waitUntil: 'domcontentloaded', timeout: 45000 });
      await page.waitForTimeout(4000);
      console.log('  [login] Mobile login completed');
    } else {
      console.log(`  [warn] Expected >=2 inputs for login, found ${inputCount}`);
    }
  } else {
    console.log('  [session] Session valid, on trade page');
  }

  return { browser, ctx, page };
}

// Close popup overlay on market list page
async function closeMarketPopup(page) {
  const overlay = await page.locator('.van-overlay').count();
  if (overlay > 0) {
    console.log('  [popup] Closing market overlay...');
    await page.evaluate(() => {
      const o = document.querySelector('.van-overlay');
      if (o) o.click();
      const b = document.querySelector('.popback');
      if (b) b.click();
    });
    await page.waitForTimeout(1500);
  }
}

// Scroll down the market list to find more currencies
async function scrollMarketList(page, direction = 'down') {
  console.log(`  [scroll] Scrolling ${direction}...`);
  await page.evaluate((dir) => {
    const container = document.querySelector('.market-list, .trade-list, .van-list, [class*="list"]') 
                   || document.scrollingElement 
                   || document.body;
    const amount = dir === 'down' ? 300 : -300;
    container.scrollBy({ top: amount, behavior: 'smooth' });
  }, direction);
  await page.waitForTimeout(1000);
}

// Switch category tab (Crypto / Forex / Commodities / Indices)
async function switchCategory(page, category) {
  console.log(`  [category] Switching to ${category}...`);
  
  const tabTexts = {
    'crypto': ['Crypto', 'Digital', '数字货币', 'BTC'],
    'forex': ['Forex', 'FX', 'Currency', '外汇', 'Forex Trade'],
    'commodities': ['Commodities', 'Commodity', '商品', 'Gold', 'Oil'],
    'indices': ['Indices', 'Index', '指数', 'ES', 'NQ'],
  };

  const texts = tabTexts[category] || [category];
  
  const clicked = await page.evaluate((searchTexts) => {
    const candidates = document.querySelectorAll('div, span, button, a');
    for (const text of searchTexts) {
      for (const el of candidates) {
        const content = el.textContent.trim();
        if (content === text || content.includes(text)) {
          const rect = el.getBoundingClientRect();
          if (rect.width > 30 && rect.width < 200 && rect.height > 20 && rect.height < 80) {
            el.click();
            return text;
          }
        }
      }
    }
    return null;
  }, texts);

  if (clicked) {
    console.log(`  [category] Clicked tab: ${clicked}`);
    await page.waitForTimeout(2000);
  } else {
    console.log(`  [category] Tab not found, will try scrolling to find currency`);
  }
}

// Find and click currency with scrolling support
async function selectCurrency(page, currency) {
  const displayName = getCurrencyDisplay(currency);
  const category = getCurrencyCategory(currency);
  console.log(`  [currency] Selecting ${displayName} (category: ${category})...`);

  await closeMarketPopup(page);

  const url = page.url();
  if (!url.includes('#/trade') || url.includes('#/chart')) {
    await page.goto(config.tradeUrl, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(3000);
    await closeMarketPopup(page);
  }

  if (category !== 'crypto') {
    await switchCategory(page, category);
  }

  const maxScrollAttempts = 8;
  let found = false;

  for (let attempt = 0; attempt < maxScrollAttempts; attempt++) {
    const clicked = await page.evaluate((cur) => {
      const searchTerms = [cur, cur.toUpperCase(), cur.toLowerCase()];
      const spans = document.querySelectorAll('span, div');
      for (const span of spans) {
        const text = span.textContent.trim();
        for (const term of searchTerms) {
          if (text === term || text === term.replace('/', '') || text.includes(term)) {
            const parent = span.closest('div[class]') || span.parentElement;
            if (parent) {
              const rect = parent.getBoundingClientRect();
              if (rect.top >= 0 && rect.bottom <= window.innerHeight && rect.height > 30) {
                parent.click();
                return true;
              }
            }
          }
        }
      }
      return false;
    }, displayName);

    if (clicked) {
      console.log(`  [currency] Found and clicked ${displayName}`);
      found = true;
      break;
    }

    if (attempt < maxScrollAttempts - 1) {
      console.log(`  [currency] ${displayName} not visible, scrolling... (attempt ${attempt + 1}/${maxScrollAttempts})`);
      await scrollMarketList(page, 'down');
    }
  }

  if (!found) {
    console.log(`  [currency] WARN: ${displayName} not found after scrolling, trying direct navigation...`);
  }

  try {
    await page.waitForURL(/\#\/chart/, { timeout: 10000 });
  } catch {
    console.log('  [currency] WARN: Did not navigate to chart page, continuing...');
  }
  await page.waitForTimeout(2000);

  try {
    await page.locator('.amount-btn, .amount-box, .down-btn, .up-btn').first().waitFor({ state: 'visible', timeout: 15000 });
    console.log('  [currency] Trade panel loaded');
  } catch {
    console.log('  [currency] WARN: Trade panel not visible yet, waiting extra...');
    await page.waitForTimeout(5000);
  }

  const newUrl = page.url();
  console.log(`  [currency] Navigated to: ${newUrl}`);
}

// Enter amount using keyboard
async function enterAmount(page, amount) {
  console.log(`  [amount] Setting to ${amount}...`);

  const amountInput = page.locator('.amount-btn input, .amount-box input').first();
  try {
    await amountInput.waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    console.log('  [amount] WARN: .amount-btn/.amount-box input not found after 15s, trying fallback...');
    const fallback = page.locator('input:visible:not([type="password"]):not([type="hidden"])').first();
    try {
      await fallback.waitFor({ state: 'visible', timeout: 8000 });
      await fallback.click({ clickCount: 3 });
      await page.keyboard.press('Backspace');
      await page.keyboard.press('Control+A');
      await page.keyboard.press('Delete');
      await page.keyboard.type(amount, { delay: 50 });
    } catch {
      console.log('  [amount] ERROR: No amount input found on page at all');
      await shot(page, 'no-amount-input');
    }
    return;
  }

  await amountInput.click({ clickCount: 3 });
  await page.waitForTimeout(100);
  await page.keyboard.press('Backspace');
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
  await page.waitForTimeout(100);
  await page.keyboard.type(amount, { delay: 50 });

  const val = await amountInput.inputValue().catch(() => '?');
  console.log(`  [amount] Value is now: ${val}`);
}

// Select duration by tapping time area
async function selectDuration(page, duration) {
  const durText = duration + 's';
  console.log(`  [duration] Selecting ${durText}...`);

  const timeContent = page.locator('.time-content').first();
  if (await timeContent.count() === 0) {
    console.log('  [duration] WARN: .time-content not found, skipping duration selection');
    return;
  }
  await timeContent.tap();
  await page.waitForTimeout(1500);

  const selected = await page.evaluate((target) => {
    const popup = document.querySelector('.time-pop');
    if (!popup) return 'no-popup';
    const spans = popup.querySelectorAll('span');
    for (const s of spans) {
      if (s.textContent.trim() === target) { s.click(); return 'ok'; }
    }
    const num = target.replace('s', '');
    for (const s of spans) {
      if (s.textContent.trim().startsWith(num)) { s.click(); return 'ok-partial'; }
    }
    return 'not-found';
  }, durText);

  if (selected === 'ok' || selected === 'ok-partial') {
    console.log(`  [duration] Selected ${durText}`);
  } else if (selected === 'no-popup') {
    console.log('  [duration] WARN: Duration picker popup (.time-pop) did not appear');
    await timeContent.tap();
    await page.waitForTimeout(2000);
    await page.evaluate((target) => {
      const popup = document.querySelector('.time-pop');
      if (!popup) return;
      const spans = popup.querySelectorAll('span');
      for (const s of spans) {
        if (s.textContent.trim() === target) { s.click(); return; }
      }
    }, durText);
  } else {
    console.log(`  [duration] WARN: Could not find ${durText} in picker (status: ${selected})`);
  }
  await page.waitForTimeout(1000);
}

// Click UP or DOWN button
async function clickDirection(page, direction) {
  const cls = direction === 'up' ? '.up-btn' : '.down-btn';
  console.log(`  [direction] Tapping ${direction.toUpperCase()}...`);

  const btn = page.locator(cls).first();
  if (await btn.count() === 0) {
    console.log(`  [direction] WARN: ${cls} not found! Trying alternative...`);
    const alt = page.getByText(new RegExp(direction, 'i')).last();
    await alt.tap();
  } else {
    await btn.tap();
  }
  await page.waitForTimeout(1000);
  console.log(`  [direction] Tapped ${direction.toUpperCase()}`);
}

// Wait for trade result, screenshot, and send to Telegram
async function waitAndScreenshot(page, duration, round, currency, amount, direction) {
  const waitMs = getWaitTime(duration);
  console.log(`  [wait] Waiting ${Math.round(waitMs / 1000)}s for trade result...`);

  await page.waitForTimeout(3000);
  await shot(page, `countdown-r${round}`);

  let resultText = 'Unknown';
  
  try {
    await page.getByText(/Settlement Completed|结算完成/i).waitFor({ state: 'visible', timeout: waitMs });
    console.log('  [result] Settlement Completed popup appeared!');
  } catch {
    console.log('  [result] Timeout waiting for settlement popup, checking alternatives...');
    try {
      await page.getByText(/You (Won|Lost)|盈利|亏损/i).waitFor({ state: 'visible', timeout: 15000 });
      console.log('  [result] Found result text');
    } catch {
      console.log('  [result] WARN: No result popup detected — trade may have failed or page unresponsive');
      await shot(page, `no-result-r${round}`);
    }
  }

  console.log('  [result] Waiting for popup to fully render...');
  await page.waitForTimeout(2500);

  // Extract result details
  const resultInfo = await page.evaluate(() => {
    const texts = [];
    let won = false;
    let profit = '';
    
    for (const el of document.querySelectorAll('*')) {
      const t = el.textContent.trim();
      if (/You Won/i.test(t) && t.length < 50) { won = true; texts.push('✅ You Won'); break; }
      if (/You Lost/i.test(t) && t.length < 50) { won = false; texts.push('❌ You Lost'); break; }
    }
    
    for (const el of document.querySelectorAll('*')) {
      const t = el.textContent.trim();
      const profitMatch = t.match(/Profit:\s*(\d+\.?\d*)/i);
      if (profitMatch) { profit = profitMatch[1]; texts.push(`Profit: ${profit}`); break; }
    }
    
    for (const el of document.querySelectorAll('*')) {
      const t = el.textContent.trim();
      if (/^(Direction|Buy|Deal Price|Execution Price):?/i.test(t) && t.length < 80) {
        texts.push(t);
      }
    }
    return { texts: texts.slice(0, 8).join(' | '), won, profit };
  });
  
  if (resultInfo.texts) console.log(`  [result] ${resultInfo.texts}`);
  resultText = resultInfo.texts || 'Unknown';

  const screenshotPath = path.join(SCREENSHOT_DIR, `mobile-trade-result-r${round}.png`);
  await shot(page, `trade-result-r${round}`);

  // Build message for Telegram
  const displayCurrency = getCurrencyDisplay(currency);
  const resultEmoji = resultInfo.won ? '✅' : '❌';
  const profitText = resultInfo.profit ? ` | Profit: $${resultInfo.profit}` : '';
  const message = `${resultEmoji} ${displayCurrency} ${amount} ${direction.toUpperCase()} ${duration}s${profitText}`;
  
  // Send screenshot to Telegram
  sendToTelegram(screenshotPath, message, TELEGRAM_ID);

  // Close result popup
  try {
    const confirmBtn = page.getByText('Confirm', { exact: true });
    if (await confirmBtn.count() > 0) {
      await confirmBtn.first().tap();
      console.log('  [result] Closed popup via Confirm button');
    } else {
      const closed = await page.evaluate(() => {
        const el = document.querySelector('.stx-ico-close');
        if (el) { el.click(); return true; }
        return false;
      });
      if (closed) console.log('  [result] Closed popup via .stx-ico-close');
    }
  } catch (e) {
    console.log('  [result] Could not close popup:', e.message);
  }
  await page.waitForTimeout(1500);
  
  return resultInfo;
}

// --------------- Main ---------------
(async () => {
  console.log('======================================');
  console.log('  OpenClaw Trade (Mobile + Auto-Send)');
  console.log(`  Currency : ${CURRENCY}`);
  console.log(`  Amount   : ${AMOUNT}`);
  console.log(`  Duration : ${DURATION}s`);
  console.log(`  Direction: ${DIRECTION.toUpperCase()}`);
  console.log(`  Rounds   : ${ROUNDS}`);
  console.log(`  Category : ${getCurrencyCategory(CURRENCY)}`);
  console.log(`  Telegram : ${TELEGRAM_ID}`);
  console.log('======================================\n');

  try {
    await desktopLogin();
    const { browser, ctx, page } = await mobileLogin();

    const results = [];
    
    for (let round = 1; round <= ROUNDS; round++) {
      console.log(`\n=== Round ${round}/${ROUNDS}: ${getCurrencyDisplay(CURRENCY)} ${AMOUNT} ${DIRECTION} ${DURATION}s ===`);

      await selectCurrency(page, CURRENCY);
      await enterAmount(page, AMOUNT);
      await selectDuration(page, DURATION);
      await shot(page, `pre-trade-r${round}`);
      await clickDirection(page, DIRECTION);
      const result = await waitAndScreenshot(page, DURATION, round, CURRENCY, AMOUNT, DIRECTION);
      results.push(result);

      console.log(`=== Round ${round} complete ===`);
    }

    // Summary
    console.log('\n======================================');
    console.log('  Trade Summary');
    console.log('======================================');
    results.forEach((r, i) => {
      console.log(`  Round ${i + 1}: ${r.texts || 'Unknown'}`);
    });

    console.log('\n[done] All rounds completed!');
    await ctx.close();
    await browser.close();
  } catch (err) {
    console.error('[ERROR]', err.message);
    console.error('[STACK]', err.stack);
    process.exit(1);
  }
})();
