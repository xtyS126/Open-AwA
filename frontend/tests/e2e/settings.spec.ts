/**
 * E2E 设置页面测试 — 导航和 Tab 切换。
 */
import { test, expect } from '@playwright/test'

const ADMIN_PASSWORD = process.env.OPENAWA_ADMIN_PASSWORD || 'openawa-e2e-admin'

test.describe('Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    // 登录
    await page.goto('/login')
    await page.fill('input[name="username"]', 'admin')
    await page.fill('input[type="password"]', ADMIN_PASSWORD)
    await page.click('button[type="submit"]')
    await expect(page).toHaveURL(/\/chat/, { timeout: 15000 })
  })

  test('navigates to settings page', async ({ page }) => {
    // 通过 URL 直接导航到设置页
    await page.goto('/settings')
    await expect(page).toHaveURL(/\/settings/, { timeout: 10000 })
  })

  test('settings page has navigation tabs', async ({ page }) => {
    await page.goto('/settings')
    // 设置页应有导航标签
    const navItems = page.locator('.secondary-nav .nav-item, [role="tab"], .tab')
    const count = await navItems.count()
    // 设置页应至少有 3 个标签
    expect(count).toBeGreaterThanOrEqual(3)
  })

  test('can switch between settings tabs', async ({ page }) => {
    await page.goto('/settings')
    // 点击导航项切换标签
    const navItems = page.locator('.secondary-nav .nav-item, [role="tab"], .tab')
    const count = await navItems.count()
    if (count > 1) {
      await navItems.nth(1).click()
      // 等待内容区域更新
      await page.waitForTimeout(500)
      // 第二个标签应是激活状态
      await expect(navItems.nth(1)).toHaveClass(/active|selected|current/)
    }
  })
})
