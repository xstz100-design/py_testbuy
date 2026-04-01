/**
 * OpenClaw - OKXOption 网站配置
 * 
 * ⚠️ 安全提醒：请勿将此文件提交到公开仓库
 * 建议将此文件加入 .gitignore
 */
module.exports = {
  // 网站地址
  baseUrl: 'https://okxoption.com',
  tradeUrl: 'https://okxoption.com/#/trade',

  // 登录凭据
  account: process.env.OKX_ACCOUNT || '885236645',
  password: process.env.OKX_PASSWORD || '123456',

  // 浏览器设置
  browser: {
    headless: false,       // false=显示浏览器窗口
    slowMo: 100,           // 操作间隔(ms)，方便观察
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN',
  },

  // 超时设置
  timeout: {
    navigation: 30000,     // 页面导航超时
    element: 10000,        // 元素等待超时
    network: 15000,        // 网络请求超时
  },

  // 截图设置
  screenshot: {
    dir: './screenshots',
    fullPage: true,
  },

  // Trade defaults
  trade: {
    currency: 'BTC',           // BTC, LTC, ETH, DOGE, LINK, BNB, USD/CAD, EUR/USD
    amount: 100,               // Order amount
    duration: 60,              // Duration in seconds: 60, 90, 120, 180, 300
    direction: 'up',           // 'up' or 'down'
  },

  // Monitor interval (ms)
  monitorInterval: 3000,
};
