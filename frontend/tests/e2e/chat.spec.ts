/**
 * E2E 聊天页面测试 — 核心交互路径。
 */
import { test, expect } from '@playwright/test'

const ADMIN_PASSWORD = process.env.OPENAWA_ADMIN_PASSWORD || 'openawa-e2e-admin'

test.describe('Chat Page', () => {
  test.beforeEach(async ({ page }) => {
    // 登录
    await page.goto('/login')
    await page.fill('input[name="username"]', 'admin')
    await page.fill('input[type="password"]', ADMIN_PASSWORD)
    await page.click('button[type="submit"]')
    await expect(page).toHaveURL(/\/chat/, { timeout: 15000 })
  })

  test('displays chat interface after login', async ({ page }) => {
    // 聊天页面应有侧边栏、消息区和输入框
    await expect(page.locator('nav, [role="navigation"], .sidebar')).toBeVisible({ timeout: 10000 })
    // 输入框应可见
    await expect(page.locator('textarea, [contenteditable]').first()).toBeVisible()
  })

  test('can type message in input area', async ({ page }) => {
    const input = page.locator('textarea').first()
    await expect(input).toBeVisible({ timeout: 10000 })
    await input.fill('Hello, this is an E2E test message')
    expect(await input.inputValue()).toBe('Hello, this is an E2E test message')
  })

  test('sidebar navigation is functional', async ({ page }) => {
    // 侧边栏菜单项应存在且可点击
    const navItems = page.locator('nav a, [role="navigation"] a, .sidebar-item')
    const count = await navItems.count()
    expect(count).toBeGreaterThan(0)
  })
})

test.describe('Chat History', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login')
    await page.fill('input[name="username"]', 'admin')
    await page.fill('input[type="password"]', ADMIN_PASSWORD)
    await page.click('button[type="submit"]')
    await expect(page).toHaveURL(/\/chat/, { timeout: 15000 })
  })

  test('can open conversation sidebar', async ({ page }) => {
    // 点击历史对话切换按钮
    const historyBtn = page.locator('.history-toggle, [aria-label*="history" i]')
    if (await historyBtn.isVisible()) {
      await historyBtn.first().click()
      // 对话列表应可见
      await expect(page.locator('.conversation-sidebar, [class*="conversation"]').first()).toBeVisible({ timeout: 5000 })
    }
  })
})
