# 选择器策略参考

元素定位是网页精准控制的核心。选择正确的定位策略直接决定脚本的稳定性和可维护性。

## 优先级排序

| 优先级 | 方式 | 稳定性 | 说明 |
|--------|------|--------|------|
| 🥇 1 | Role 定位 | ★★★★★ | 基于ARIA角色语义，不受样式/结构变化影响 |
| 🥈 2 | 文本/标签定位 | ★★★★☆ | 直观易读，文案变化时需更新 |
| 🥉 3 | Test ID | ★★★★☆ | 专为测试设计，需开发配合添加 |
| 4 | CSS选择器 | ★★★☆☆ | 灵活但与DOM结构耦合 |
| 5 | XPath | ★★☆☆☆ | 最灵活但最脆弱，最后手段 |

## Role 定位（最推荐）

基于元素的 ARIA 角色和可访问名称定位，是最稳定的方式：

```javascript
// 按钮
page.getByRole('button', { name: '提交' })
page.getByRole('button', { name: /提交|确认/ })  // 正则匹配

// 链接
page.getByRole('link', { name: '首页' })

// 输入框
page.getByRole('textbox', { name: '用户名' })

// 标题
page.getByRole('heading', { name: '欢迎', level: 1 })

// 复选框/单选框
page.getByRole('checkbox', { name: '同意条款' })
page.getByRole('radio', { name: '选项A' })

// 下拉菜单
page.getByRole('combobox', { name: '选择城市' })

// 表格
page.getByRole('row', { name: '张三' })
page.getByRole('cell', { name: '100分' })

// 导航/侧边栏
page.getByRole('navigation')
page.getByRole('complementary')  // aside

// 对话框
page.getByRole('dialog', { name: '确认删除' })

// 列表项
page.getByRole('listitem')

// 菜单
page.getByRole('menuitem', { name: '设置' })

// Tab标签
page.getByRole('tab', { name: '详情' })
page.getByRole('tabpanel')

// 精确匹配
page.getByRole('button', { name: '提交', exact: true })
```

### 常用 ARIA 角色表

| 角色 | 对应元素 |
|------|----------|
| `button` | `<button>`, `<input type="submit">`, `[role="button"]` |
| `textbox` | `<input type="text">`, `<textarea>`, `[role="textbox"]` |
| `link` | `<a href>`, `[role="link"]` |
| `heading` | `<h1>`-`<h6>`, `[role="heading"]` |
| `checkbox` | `<input type="checkbox">`, `[role="checkbox"]` |
| `radio` | `<input type="radio">`, `[role="radio"]` |
| `combobox` | `<select>`, `[role="combobox"]` |
| `img` | `<img>`, `[role="img"]` |
| `list` | `<ul>`, `<ol>`, `[role="list"]` |
| `listitem` | `<li>`, `[role="listitem"]` |
| `table` | `<table>`, `[role="table"]` |
| `row` | `<tr>`, `[role="row"]` |
| `cell` | `<td>`, `[role="cell"]` |
| `dialog` | `<dialog>`, `[role="dialog"]` |
| `navigation` | `<nav>`, `[role="navigation"]` |
| `main` | `<main>`, `[role="main"]` |

## 文本/标签定位

```javascript
// 按可见文本
page.getByText('欢迎回来')
page.getByText('欢迎', { exact: false })  // 包含匹配
page.getByText(/\d+ 条结果/)              // 正则匹配

// 按input的label
page.getByLabel('用户名')
page.getByLabel('密码')

// 按placeholder
page.getByPlaceholder('请输入搜索关键词')

// 按alt文本（图片）
page.getByAltText('用户头像')

// 按title属性
page.getByTitle('关闭窗口')
```

## Test ID 定位

```javascript
// 需要HTML中有 data-testid 属性
// <button data-testid="submit-btn">提交</button>
page.getByTestId('submit-btn')

// 自定义test-id属性名（在playwright.config中配置）
// testIdAttribute: 'data-cy'
```

## CSS 选择器

```javascript
// 基础选择器
page.locator('#login-form')            // ID
page.locator('.submit-button')         // class
page.locator('button')                 // 标签

// 组合选择器
page.locator('form#login .btn-primary')
page.locator('div.container > ul > li:first-child')
page.locator('input[type="email"]')
page.locator('button[disabled]')

// 属性选择器
page.locator('[data-type="premium"]')
page.locator('[href*="login"]')        // 包含
page.locator('[href^="https"]')        // 开头
page.locator('[href$=".pdf"]')         // 结尾

// 伪类
page.locator('li:nth-child(3)')
page.locator('tr:nth-of-type(even)')
page.locator('p:not(.hidden)')

// 相邻/兄弟
page.locator('label + input')          // 紧邻弟弟
page.locator('h2 ~ p')                 // 所有弟弟
```

## XPath

```javascript
// 基础路径
page.locator('xpath=//button[@id="submit"]')
page.locator('xpath=//div[@class="container"]//a')

// 文本匹配
page.locator('xpath=//span[text()="精确匹配"]')
page.locator('xpath=//span[contains(text(), "部分匹配")]')
page.locator('xpath=//span[starts-with(text(), "开头")]')

// 位置
page.locator('xpath=//ul/li[1]')           // 第一个
page.locator('xpath=//ul/li[last()]')      // 最后一个
page.locator('xpath=//ul/li[position()<=3]') // 前三个

// 轴定位
page.locator('xpath=//td[text()="张三"]/following-sibling::td[1]')  // 同级后面
page.locator('xpath=//span[@class="icon"]/parent::button')          // 父元素
page.locator('xpath=//div[@id="root"]//descendant::input')          // 所有后代

// 条件组合
page.locator('xpath=//button[@type="submit" and not(@disabled)]')
page.locator('xpath=//div[@class="item" and .//span[contains(text(), "热门")]]')
```

## 链式过滤

Playwright 支持在定位器上链式过滤，精准缩小范围：

```javascript
// 在容器内找元素
page.locator('.product-list').locator('.item')

// filter过滤
page.getByRole('listitem')
  .filter({ hasText: '已完成' })

page.getByRole('listitem')
  .filter({ has: page.getByRole('button', { name: '编辑' }) })

// 排除
page.getByRole('listitem')
  .filter({ hasNot: page.getByText('已删除') })

// 按位置
page.getByRole('listitem').first()
page.getByRole('listitem').last()
page.getByRole('listitem').nth(2)    // 第3个（0-based）

// 链式组合
page.locator('.order-list')
  .getByRole('listitem')
  .filter({ hasText: '待发货' })
  .getByRole('button', { name: '发货' })
```

## 调试选择器

```javascript
// 高亮元素
await page.getByRole('button', { name: '提交' }).highlight();

// 打印匹配数量
const count = await page.locator('.item').count();
console.log(`找到 ${count} 个元素`);

// 检查是否可见
const visible = await page.getByText('成功').isVisible();

// 使用codegen录制选择器
// npx playwright codegen https://target-site.com

// 使用 Playwright Inspector
// PWDEBUG=1 node script.js
```

## 选择器决策树

```
需要定位元素？
│
├── 元素有明确的角色和名称？
│   └── ✅ getByRole('role', { name: '名称' })
│
├── 元素有可见文本？
│   └── ✅ getByText('文本')
│
├── 是表单控件？
│   ├── 有label？ → getByLabel('标签')
│   └── 有placeholder？ → getByPlaceholder('提示')
│
├── 有 data-testid？
│   └── ✅ getByTestId('id')
│
├── 有唯一的CSS特征？
│   └── ✅ locator('css选择器')
│
└── 以上都不行？
    └── ✅ locator('xpath=...')
```
