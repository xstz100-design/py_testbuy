/**
 * OpenClaw - OKXOption 一键全流程
 *
 * 功能：登录 → 探测页面 → 截图 → 监控数据
 * 运行：node scripts/okx-run.js
 */
const { chromium } = require('playwright');
const config = require('../okx-config');
const path = require('path');
const fs = require('fs');

const SHOT_DIR = path.join(__dirname, '..', 'screenshots');
if (!fs.existsSync(SHOT_DIR)) {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
}

async function run() {
  console.log('🦞 ============================');
  console.log('   OpenClaw 龙虾精准钳控');
  console.log('   目标: bptradinguk.com');
  console.log('   ============================\n');

  const browser = await chromium.launch({
    headless: config.browser.headless,
    slowMo: config.browser.slowMo,
  });

  const context = await browser.newContext({
    viewport: config.browser.viewport,
    locale: config.browser.locale,
  });

  context.setDefaultTimeout(config.timeout.element);
  const page = await context.newPage();

  page.on('dialog', async dialog => {
    console.log(`[弹窗] ${dialog.type()}: ${dialog.message()}`);
    await dialog.accept();
  });

  try {
    // ========== 第1步：打开页面 ==========
    console.log('📍 第1步：打开交易页面...');
    await page.goto(config.tradeUrl, {
      waitUntil: 'networkidle',
      timeout: config.timeout.navigation,
    });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: path.join(SHOT_DIR, 'step1-page-loaded.png') });
    console.log('✅ 页面已加载\n');

    // ========== 第2步：登录 ==========
    console.log('📍 第2步：自动登录...');

    // 定位表单
    const inputs = page.locator('input');
    const inputCount = await inputs.count();
    console.log(`   发现 ${inputCount} 个输入框`);

    if (inputCount >= 2) {
      // 填写账号（第一个输入框）
      await inputs.nth(0).click();
      await inputs.nth(0).fill(config.account);
      console.log('   ✅ 账号已填写');

      // 填写密码（第二个输入框）
      await inputs.nth(1).click();
      await inputs.nth(1).fill(config.password);
      console.log('   ✅ 密码已填写');

      await page.screenshot({ path: path.join(SHOT_DIR, 'step2-form-filled.png') });

      // 点击登录
      const loginBtn = page.locator('button, [role="button"], input[type="submit"]')
        .filter({ hasText: /log\s*in|登录|login|sign\s*in/i })
        .first();

      if (await loginBtn.count() > 0) {
        await loginBtn.click();
        console.log('   ✅ 已点击登录按钮');
      } else {
        // 如果找不到文字匹配的按钮，找页面上的主要按钮
        const primaryBtn = page.locator('button').first();
        await primaryBtn.click();
        console.log('   ⚠️ 未找到明确的登录按钮，点击了第一个按钮');
      }

      // 等待登录结果
      await page.waitForTimeout(3000);
      await page.waitForLoadState('networkidle').catch(() => {});
      await page.screenshot({ path: path.join(SHOT_DIR, 'step2-after-login.png') });
      console.log('   📸 登录后截图已保存');

      // 保存登录态
      await context.storageState({ path: path.join(__dirname, '..', 'auth.json') });
      console.log('   💾 登录态已保存\n');
    } else {
      console.log('   ⚠️ 输入框不足，可能已经登录或页面结构不同\n');
    }

    // ========== 第3步：探测页面结构 ==========
    console.log('📍 第3步：探测交易页面结构...');

    const pageInfo = await page.evaluate(() => {
      const info = { url: location.href, title: document.title };

      // 收集所有可见文本元素
      const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
        null
      );
      const visibleTexts = [];
      let node;
      while ((node = walker.nextNode())) {
        const text = node.textContent.trim();
        if (text && text.length > 1 && text.length < 100) {
          const parent = node.parentElement;
          if (parent && parent.offsetParent !== null) {
            visibleTexts.push(text);
          }
        }
      }
      info.visibleTexts = [...new Set(visibleTexts)].slice(0, 50);

      // 收集所有按钮
      info.buttons = Array.from(
        document.querySelectorAll('button, [role="button"]')
      ).map(el => el.textContent.trim().substring(0, 40)).filter(Boolean);

      // 收集输入框
      info.inputs = Array.from(
        document.querySelectorAll('input:not([type="hidden"])')
      ).map(el => ({
        type: el.type,
        placeholder: el.placeholder,
        value: el.value ? '(有值)' : '(空)',
      }));

      return info;
    });

    console.log(`   URL: ${pageInfo.url}`);
    console.log(`   标题: ${pageInfo.title}`);
    console.log(`   按钮: ${pageInfo.buttons.join(' | ') || '无'}`);
    console.log(`   输入框: ${pageInfo.inputs.length}个`);
    pageInfo.inputs.forEach((inp, i) => {
      console.log(`     ${i + 1}. [${inp.type}] "${inp.placeholder}" ${inp.value}`);
    });
    console.log(`   页面文本: ${pageInfo.visibleTexts.slice(0, 20).join(' | ')}`);
    console.log('');

    // ========== 第4步：全页截图 ==========
    console.log('📍 第4步：保存完整截图...');
    await page.screenshot({
      path: path.join(SHOT_DIR, 'step4-full-page.png'),
      fullPage: true,
    });
    console.log('   ✅ 全页截图已保存\n');

    // ========== 第5步：持续监控（可选） ==========
    console.log('📍 第5步：启动数据监控（每3秒采集一次）...');
    console.log('   按 Ctrl+C 停止\n');

    let round = 0;
    const monitorLoop = setInterval(async () => {
      try {
        round++;
        const time = new Date().toLocaleTimeString('zh-CN');
        const snapshot = await page.evaluate(() => {
          // 尝试提取最显眼的数字/价格
          const nums = document.body.innerText.match(/[\d,]+\.?\d*/g);
          const bigNums = nums ? nums.filter(n => parseFloat(n.replace(/,/g, '')) > 0).slice(0, 10) : [];
          return {
            title: document.title,
            numbers: bigNums,
            bodyLength: document.body.innerText.length,
          };
        });

        console.log(`[${time}] #${round} | 页面文本长度: ${snapshot.bodyLength} | 数字: ${snapshot.numbers.join(', ') || '无'}`);
      } catch (e) {
        console.log(`[监控] 采集出错: ${e.message}`);
      }
    }, config.monitorInterval);

    process.on('SIGINT', async () => {
      clearInterval(monitorLoop);
      console.log('\n🛑 监控已停止');
      await page.screenshot({ path: path.join(SHOT_DIR, 'final-snapshot.png') });
      console.log('📸 最终截图已保存');
      await browser.close();
      process.exit(0);
    });

  } catch (error) {
    console.error('❌ 执行出错:', error.message);
    await page.screenshot({ path: path.join(SHOT_DIR, 'error.png') }).catch(() => {});
    await browser.close();
  }
}

run().catch(console.error);
