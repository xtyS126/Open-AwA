/* Web 端思考开关验证：关闭思考 → 发消息 → 确认回复无思维链
 * 用法：node scripts/verify-thinking-web.cjs
 * 依赖 frontend/node_modules 的 playwright（chromium 已安装）
 */
const { chromium } = require('playwright')
const fs = require('fs')

const API_KEY = process.env.OPENAWA_API_KEY

async function main() {
  if (!API_KEY) {
    console.error('缺少 OPENAWA_API_KEY 环境变量')
    process.exit(1)
  }
  const browser = await chromium.launch()
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.log('  [console.error]', msg.text().slice(0, 120))
  })

  // 1. 打开登录页
  await page.goto('http://localhost:5173/login', { waitUntil: 'networkidle', timeout: 30000 })
  console.log('1. 登录页加载完成')

  // 2. 输入 API Key 登录
  const keyInput = page.locator('#apiKey, input[type=password], input[placeholder*="密钥"], input[placeholder*="key"]').first()
  await keyInput.fill(API_KEY)
  await page.getByRole('button', { name: /连接|登录|Login/ }).first().click()
  await page.waitForURL(/\/chat/, { timeout: 30000 })
  console.log('2. 登录成功，进入 /chat')

  // 3. 等待聊天页加载，关闭思考开关（若开启）
  await page.waitForSelector('textarea', { timeout: 15000 })
  const toggle = page.locator('label[title*="思考"], [class*=thinking-toggle]').first()
  if (await toggle.count()) {
    const input = toggle.locator('input').first()
    if (await input.isChecked()) {
      await toggle.click()
      await page.waitForTimeout(500)
      console.log('3. 思考开关已关闭（原为开启）')
    } else {
      console.log('3. 思考开关已处于关闭状态')
    }
  } else {
    console.log('3. 未找到思考开关（可能已关闭）')
  }

  // 4. 发送测试消息：先填文本（空输入时发送按钮本就禁用），再等待按钮可用
  const ta = page.locator('textarea').first()
  await ta.fill('Web端思考验证：5+5等于几')
  const sendBtn = page.locator('button[aria-label="发送"], button:has-text("发送")').last()
  await sendBtn.waitFor({ state: 'visible', timeout: 10000 })
  await page.waitForFunction(() => {
    const sendBtn = [...document.querySelectorAll('button')].find(b => b.getAttribute('aria-label') === '发送')
    return sendBtn && !sendBtn.disabled
  }, null, { timeout: 20000 })
  await sendBtn.click()
  console.log('4. 消息已发送，等待流式回复...')

  // 5. 等待回复完成（发送按钮重新可用 / 出现最终回复）
  await page.waitForFunction(() => {
    const sendBtn = [...document.querySelectorAll('button')].find(b => b.getAttribute('aria-label') === '发送' || b.textContent.trim() === '发送')
    return sendBtn && !sendBtn.disabled && document.body.innerText.includes('5 + 5') && document.body.innerText.includes('10')
  }, null, { timeout: 60000 }).catch(() => {})

  // 6. 检查最新助手消息是否含思维链区块
  const result = await page.evaluate(() => {
    const main = document.querySelector('#main-content') || document.body
    const msgs = [...main.querySelectorAll('[class*=message]')].map(m => m.textContent.trim()).filter(Boolean)
    const unique = [...new Set(msgs)]
    const last = unique[unique.length - 1] || ''
    const chainTitle = [...main.querySelectorAll('[class*=title]')].filter(el => el.textContent.trim().includes('思维链'))
    return {
      lastMsg: last.slice(0, 80),
      chainInLast: last.includes('思维链'),
      chainTitlesTotal: chainTitle.length,
    }
  })
  console.log('5. 最新消息:', result.lastMsg)
  console.log('6. 最新消息含思维链:', result.chainInLast)

  // 7. 刷新后确认持久化
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForSelector('textarea', { timeout: 15000 })
  await page.waitForTimeout(1500)
  const persisted = await page.evaluate(() => {
    const main = document.querySelector('#main-content') || document.body
    const msgs = [...main.querySelectorAll('[class*=message]')].map(m => m.textContent.trim()).filter(Boolean)
    const unique = [...new Set(msgs)]
    const last = unique[unique.length - 1] || ''
    return { lastMsg: last.slice(0, 80), chainInLast: last.includes('思维链') }
  })
  console.log('7. 刷新后最新消息:', persisted.lastMsg)
  console.log('8. 刷新后含思维链:', persisted.chainInLast)

  await browser.close()

  const pass = !result.chainInLast && !persisted.chainInLast
  console.log(pass ? '\n=== 验证通过：思考关闭时回复无思维链 ===' : '\n=== 验证失败 ===')
  process.exit(pass ? 0 : 2)
}

main().catch((e) => { console.error('验证失败:', e.message); process.exit(1) })
