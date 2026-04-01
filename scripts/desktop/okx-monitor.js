/**
 * OpenClaw - OKXOption 数据监控
 *
 * 功能：登录后实时监控交易页面的价格和行情数据
 * 运行：node scripts/okx-monitor.js
 */
const { chromium } = require('playwright');
const config = require('../okx-config');
const path = require('path');
const fs = require('fs');

const SHOT_DIR = path.join(__dirname, '..', 'screenshots');
if (!fs.existsSync(SHOT_DIR)) {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
}

async function monitor() {
  const browser = await chromium.launch({
    headless: config.browser.headless,
    slowMo: 0, // 监控模式不需要慢动作
  });

  // 尝试恢复登录态
  const authFile = path.join(__dirname, '..', 'auth.json');
  const contextOptions = {
    viewport: config.browser.viewport,
    locale: config.browser.locale,
  };

  if (fs.existsSync(authFile)) {
    contextOptions.storageState = authFile;
    console.log('🔑 已恢复登录态');
  } else {
    console.log('⚠️ 未找到 auth.json，请先运行 okx-login.js 登录');
  }

  const context = await browser.newContext(contextOptions);
  context.setDefaultTimeout(config.timeout.element);
  const page = await context.newPage();

  try {
    console.log('🦞 OpenClaw 监控模式启动...');
    await page.goto(config.tradeUrl, {
      waitUntil: 'networkidle',
      timeout: config.timeout.navigation,
    });

    await page.waitForTimeout(3000); // 等待页面完整加载

    console.log('📊 开始监控交易数据...');
    console.log('按 Ctrl+C 停止监控\n');

    let round = 0;

    // 定时采集数据
    const intervalId = setInterval(async () => {
      try {
        round++;
        const timestamp = new Date().toLocaleTimeString('zh-CN');

        // ========== 数据提取 ==========
        // 提取页面上可见的数字/价格数据
        const pageData = await page.evaluate(() => {
          const data = {};

          // 页面标题
          data.title = document.title;

          // 尝试提取所有看起来像价格的数字
          const allText = document.body.innerText;

          // 提取页面可见文本（前500字符概览）
          data.pagePreview = allText.substring(0, 500).replace(/\s+/g, ' ');

          // 尝试查找常见的价格/行情CSS类
          const priceSelectors = [
            '.price', '.trade-price', '.last-price', '.current-price',
            '.bid', '.ask', '.high', '.low', '.volume',
            '[class*="price"]', '[class*="Price"]',
            '[class*="amount"]', '[class*="Amount"]',
            '[class*="rate"]', '[class*="Rate"]',
          ];

          const prices = {};
          for (const sel of priceSelectors) {
            const els = document.querySelectorAll(sel);
            if (els.length > 0) {
              prices[sel] = Array.from(els).map(el => el.textContent.trim()).filter(Boolean);
            }
          }
          data.prices = prices;

          return data;
        });

        // 输出监控数据
        console.log(`--- [${timestamp}] 第 ${round} 轮采集 ---`);
        console.log('页面标题:', pageData.title);

        if (Object.keys(pageData.prices).length > 0) {
          console.log('价格数据:');
          for (const [selector, values] of Object.entries(pageData.prices)) {
            console.log(`  ${selector}: ${values.join(', ')}`);
          }
        } else {
          console.log('页面概览:', pageData.pagePreview);
        }

        console.log('');

        // 每10轮保存一次截图
        if (round % 10 === 0) {
          const screenshotName = `monitor-${Date.now()}.png`;
          await page.screenshot({
            path: path.join(SHOT_DIR, screenshotName),
          });
          console.log(`📸 截图已保存: ${screenshotName}`);
        }

      } catch (err) {
        console.error('采集出错:', err.message);
      }
    }, config.monitorInterval);

    // 优雅退出
    process.on('SIGINT', async () => {
      console.log('\n🛑 停止监控...');
      clearInterval(intervalId);
      await page.screenshot({
        path: path.join(SHOT_DIR, 'monitor-final.png'),
        fullPage: true,
      });
      console.log('📸 最终截图已保存');
      await browser.close();
      process.exit(0);
    });

  } catch (error) {
    console.error('❌ 监控启动失败:', error.message);
    await page.screenshot({ path: path.join(SHOT_DIR, 'error-monitor.png') });
    await browser.close();
  }
}

monitor().catch(console.error);
