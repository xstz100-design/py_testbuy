/**
 * OpenClaw 网页操作模板
 * 使用方法：根据需要修改下方操作区域的代码
 *
 * 运行：node scripts/template.js
 */
const { chromium } = require('playwright');

(async () => {
  // ========== 配置 ==========
  const config = {
    headless: false,       // true=无头模式  false=显示浏览器
    slowMo: 0,             // 操作间隔(ms)，调试时设200-500
    viewport: { width: 1280, height: 720 },
    locale: 'zh-CN',
    timeout: 30000,        // 全局超时(ms)
    screenshotDir: './screenshots',
  };

  const browser = await chromium.launch({
    headless: config.headless,
    slowMo: config.slowMo,
  });

  const context = await browser.newContext({
    viewport: config.viewport,
    locale: config.locale,
    // 恢复登录态（如有）
    // storageState: 'auth.json',
  });

  context.setDefaultTimeout(config.timeout);
  const page = await context.newPage();

  // 监听控制台输出
  page.on('console', msg => {
    if (msg.type() === 'error') console.error('[PAGE]', msg.text());
  });

  // 自动处理弹窗
  page.on('dialog', async dialog => {
    console.log(`[弹窗] ${dialog.type()}: ${dialog.message()}`);
    await dialog.accept();
  });

  try {
    // ========== 操作区域 - 在此编写你的操作 ==========

    // 1. 导航到目标页面
    await page.goto('https://example.com', { waitUntil: 'networkidle' });
    console.log('页面标题:', await page.title());

    // 2. 执行操作（示例：搜索）
    // await page.getByPlaceholder('搜索').fill('关键词');
    // await page.getByRole('button', { name: '搜索' }).click();

    // 3. 等待结果
    // await page.getByText('搜索结果').waitFor({ state: 'visible' });

    // 4. 提取数据
    // const results = await page.locator('.result-item').allTextContents();
    // console.log('搜索结果:', results);

    // 5. 截图验证
    await page.screenshot({ path: `${config.screenshotDir}/result.png`, fullPage: true });
    console.log('截图已保存');

    // ========== 操作结束 ==========

    // 保存登录态（如需要）
    // await context.storageState({ path: 'auth.json' });

  } catch (error) {
    console.error('操作失败:', error.message);
    await page.screenshot({ path: `${config.screenshotDir}/error.png` });
  } finally {
    await browser.close();
  }
})();
