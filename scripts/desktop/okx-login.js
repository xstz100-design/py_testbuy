/**
 * OpenClaw - OKXOption 自动登录
 *
 * 功能：自动打开网站并完成登录
 * 运行：node scripts/okx-login.js
 */
const { chromium } = require('playwright');
const config = require('../okx-config');
const path = require('path');
const fs = require('fs');

// 确保截图目录存在
const SHOT_DIR = path.join(__dirname, '..', 'screenshots');
if (!fs.existsSync(SHOT_DIR)) {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
}

async function login() {
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

  // 监听控制台和网络错误
  page.on('console', msg => {
    if (msg.type() === 'error') console.error('[页面错误]', msg.text());
  });

  try {
    console.log('🦞 OpenClaw 启动 - 正在打开登录页面...');
    await page.goto(config.tradeUrl, {
      waitUntil: 'networkidle',
      timeout: config.timeout.navigation,
    });

    await page.screenshot({ path: path.join(SHOT_DIR, '01-login-page.png') });
    console.log('📸 登录页截图已保存');

    // ========== 定位并填写登录表单 ==========

    // 等待登录表单加载
    await page.waitForLoadState('domcontentloaded');

    // 尝试多种方式定位账号输入框
    const accountInput = page.locator('input').first();
    const passwordInput = page.locator('input[type="password"], input').nth(1);

    // 如果页面有明确的 placeholder 或 label，优先使用：
    const accountByPlaceholder = page.getByPlaceholder(/account|账号|用户名|手机|邮箱/i);
    const passwordByPlaceholder = page.getByPlaceholder(/password|密码/i);

    // 判断用哪个定位器
    let acctLocator, pwdLocator;

    if (await accountByPlaceholder.count() > 0) {
      acctLocator = accountByPlaceholder.first();
      console.log('✅ 通过placeholder定位到账号输入框');
    } else {
      acctLocator = accountInput;
      console.log('⚠️ 通过顺序定位到第一个input作为账号框');
    }

    if (await passwordByPlaceholder.count() > 0) {
      pwdLocator = passwordByPlaceholder.first();
      console.log('✅ 通过placeholder定位到密码输入框');
    } else {
      pwdLocator = passwordInput;
      console.log('⚠️ 通过顺序定位到第二个input作为密码框');
    }

    // 填写账号
    await acctLocator.click();
    await acctLocator.fill(config.account);
    console.log('📝 账号已填写');

    // 填写密码
    await pwdLocator.click();
    await pwdLocator.fill(config.password);
    console.log('📝 密码已填写');

    await page.screenshot({ path: path.join(SHOT_DIR, '02-form-filled.png') });

    // ========== 点击登录按钮 ==========
    // 尝试多种方式定位登录按钮
    const loginBtn =
      page.getByRole('button', { name: /log\s*in|登录|login/i }).first() ||
      page.locator('button:has-text("Log In"), button:has-text("登录")').first();

    await loginBtn.click();
    console.log('🖱️ 已点击登录按钮');

    // ========== 等待登录成功 ==========
    // 等待页面变化（URL变化或特定元素出现）
    await Promise.race([
      page.waitForURL('**/trade**', { timeout: config.timeout.navigation }),
      page.waitForURL('**/dashboard**', { timeout: config.timeout.navigation }),
      page.waitForLoadState('networkidle'),
    ]).catch(() => {
      console.log('⏳ 等待页面跳转超时，可能需要验证码或其他验证');
    });

    await page.waitForTimeout(2000); // 等待渲染完成
    await page.screenshot({ path: path.join(SHOT_DIR, '03-after-login.png') });

    // 检查是否登录成功
    const currentUrl = page.url();
    console.log('📍 当前页面:', currentUrl);

    // 保存登录态，后续脚本可以复用
    const authFile = path.join(__dirname, '..', 'auth.json');
    await context.storageState({ path: authFile });
    console.log('💾 登录态已保存到 auth.json');

    console.log('✅ 登录流程完成！');
    console.log('');
    console.log('后续操作：');
    console.log('  监控行情: node scripts/okx-monitor.js');
    console.log('  交易操作: node scripts/okx-trade.js');

    // 保持浏览器打开，方便调试
    // 如需自动关闭，取消下面的注释：
    // await browser.close();

    return { browser, context, page };

  } catch (error) {
    console.error('❌ 登录失败:', error.message);
    await page.screenshot({ path: path.join(SHOT_DIR, 'error-login.png') });
    await browser.close();
    throw error;
  }
}

// 直接运行时执行登录
if (require.main === module) {
  login().catch(console.error);
}

module.exports = { login };
