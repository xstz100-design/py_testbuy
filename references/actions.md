# 页面操作参考

## 点击操作

```javascript
// 基础点击
await locator.click();

// 双击
await locator.dblclick();

// 右键
await locator.click({ button: 'right' });

// 中键（鼠标滚轮键）
await locator.click({ button: 'middle' });

// Shift/Ctrl/Alt + 点击
await locator.click({ modifiers: ['Shift'] });
await locator.click({ modifiers: ['Control'] });

// 强制点击（跳过可操作性检查，元素被遮挡时用）
await locator.click({ force: true });

// 点击指定位置（相对元素左上角偏移）
await locator.click({ position: { x: 10, y: 10 } });

// 带超时的点击
await locator.click({ timeout: 5000 });

// 点击后不等待导航
await locator.click({ noWaitAfter: true });
```

## 输入操作

```javascript
// 清空并填入（推荐）
await locator.fill('新内容');

// 逐字符输入（模拟真实打字）
await locator.type('内容', { delay: 100 });

// 按键输入（用于触发键盘事件的输入框）
await locator.pressSequentially('内容', { delay: 50 });

// 清空输入框
await locator.clear();

// 输入前聚焦
await locator.focus();
await locator.fill('内容');
```

## 键盘操作

```javascript
// 单个按键
await page.keyboard.press('Enter');
await page.keyboard.press('Tab');
await page.keyboard.press('Escape');
await page.keyboard.press('Backspace');
await page.keyboard.press('ArrowDown');

// 组合键
await page.keyboard.press('Control+A');    // 全选
await page.keyboard.press('Control+C');    // 复制
await page.keyboard.press('Control+V');    // 粘贴
await page.keyboard.press('Control+Z');    // 撤销
await page.keyboard.press('Control+Shift+I'); // 开发者工具

// 按住不放
await page.keyboard.down('Shift');
await page.keyboard.press('ArrowDown');
await page.keyboard.press('ArrowDown');
await page.keyboard.up('Shift');

// 输入文本
await page.keyboard.insertText('直接插入文本');
```

## 鼠标操作

```javascript
// 移动鼠标
await page.mouse.move(100, 200);

// 鼠标按下/释放
await page.mouse.down();
await page.mouse.up();

// 滚轮滚动
await page.mouse.wheel(0, 300);   // 向下300px
await page.mouse.wheel(0, -300);  // 向上300px
await page.mouse.wheel(300, 0);   // 向右300px

// 拖拽（方式1：source -> target）
await page.getByText('拖我').dragTo(page.getByText('放这里'));

// 拖拽（方式2：手动控制）
const box = await page.getByText('拖我').boundingBox();
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
await page.mouse.down();
await page.mouse.move(500, 300, { steps: 10 });
await page.mouse.up();
```

## 悬停操作

```javascript
// 基础悬停
await locator.hover();

// 悬停指定位置
await locator.hover({ position: { x: 5, y: 5 } });

// 强制悬停
await locator.hover({ force: true });

// 悬停展开菜单后操作
await page.getByText('菜单').hover();
await page.getByText('子菜单项').click();
```

## 选择操作

```javascript
// 下拉选择 - 按value
await locator.selectOption('value');

// 按label
await locator.selectOption({ label: '选项名称' });

// 按index
await locator.selectOption({ index: 2 });

// 多选
await locator.selectOption(['value1', 'value2']);

// 复选框 - 勾选
await locator.check();

// 复选框 - 取消
await locator.uncheck();

// 复选框 - 设置状态
await locator.setChecked(true);

// 单选按钮
await page.getByLabel('选项A').check();
```

## 文件上传

```javascript
// 单个文件
await locator.setInputFiles('path/to/file.pdf');

// 多个文件
await locator.setInputFiles(['file1.jpg', 'file2.jpg']);

// 清空选择
await locator.setInputFiles([]);

// 通过 filechooser 事件上传
const [fileChooser] = await Promise.all([
  page.waitForEvent('filechooser'),
  page.getByText('上传文件').click(),
]);
await fileChooser.setFiles('path/to/file.pdf');
```

## 滚动操作

```javascript
// 滚动元素到可见区域
await locator.scrollIntoViewIfNeeded();

// 页面滚动到底部
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));

// 页面滚动到顶部
await page.evaluate(() => window.scrollTo(0, 0));

// 滚动到指定位置
await page.evaluate(() => window.scrollTo(0, 500));

// 滚动容器内部
await page.locator('.scroll-container').evaluate(el => el.scrollTop = 500);

// 平滑滚动
await page.evaluate(() => window.scrollTo({ top: 1000, behavior: 'smooth' }));
```

## 等待策略

```javascript
// 等待元素可见
await locator.waitFor({ state: 'visible' });

// 等待元素隐藏
await locator.waitFor({ state: 'hidden' });

// 等待元素挂载到DOM
await locator.waitFor({ state: 'attached' });

// 等待元素从DOM移除
await locator.waitFor({ state: 'detached' });

// 等待页面加载
await page.waitForLoadState('load');
await page.waitForLoadState('domcontentloaded');
await page.waitForLoadState('networkidle');

// 等待URL变化
await page.waitForURL('**/success');
await page.waitForURL(url => url.searchParams.has('token'));

// 等待网络请求
const request = await page.waitForRequest('**/api/submit');
const response = await page.waitForResponse(resp =>
  resp.url().includes('/api/data') && resp.status() === 200
);

// 等待超时
await page.waitForTimeout(1000); // 不推荐，仅调试用

// 等待自定义条件
await page.waitForFunction(() => {
  return document.querySelectorAll('.loaded-item').length >= 10;
});
await page.waitForFunction(
  (threshold) => window.scrollY > threshold,
  500
);
```

## 对话框处理

```javascript
// 自动接受所有弹窗
page.on('dialog', dialog => dialog.accept());

// 自动取消
page.on('dialog', dialog => dialog.dismiss());

// 带输入的prompt弹窗
page.on('dialog', dialog => dialog.accept('我的输入'));

// 一次性处理
page.once('dialog', async dialog => {
  console.log(dialog.type(), dialog.message());
  await dialog.accept();
});
```

## 数据提取

```javascript
// 单个文本
const text = await locator.textContent();
const innerText = await locator.innerText();

// 所有匹配元素的文本
const texts = await locator.allTextContents();

// 获取属性
const href = await locator.getAttribute('href');
const src = await locator.getAttribute('src');

// 获取输入框的值
const value = await locator.inputValue();

// 获取元素数量
const count = await locator.count();

// 判断状态
const visible = await locator.isVisible();
const enabled = await locator.isEnabled();
const checked = await locator.isChecked();
const editable = await locator.isEditable();

// 获取边界框
const box = await locator.boundingBox();
// box = { x, y, width, height }

// 执行页面内JS
const data = await page.evaluate(() => {
  return JSON.parse(document.querySelector('#data').textContent);
});

// 传参到页面内JS
const text = await page.evaluate(
  (selector) => document.querySelector(selector).textContent,
  '.target'
);
```

## 截图与导出

```javascript
// 当前视口截图
await page.screenshot({ path: 'viewport.png' });

// 全页截图
await page.screenshot({ path: 'full.png', fullPage: true });

// 元素截图
await locator.screenshot({ path: 'element.png' });

// 裁剪截图
await page.screenshot({
  path: 'clip.png',
  clip: { x: 100, y: 100, width: 500, height: 300 }
});

// 透明背景（仅Chromium）
await page.screenshot({ path: 'transparent.png', omitBackground: true });

// 转Base64
const buffer = await page.screenshot();
const base64 = buffer.toString('base64');

// 导出PDF（仅Chromium无头模式）
await page.pdf({
  path: 'output.pdf',
  format: 'A4',
  printBackground: true,
  margin: { top: '1cm', bottom: '1cm' }
});
```
