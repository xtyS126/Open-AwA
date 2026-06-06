/**
 * E2E 设置页面测试 — 导航和 Tab 切换。
 */
import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './utils/auth'

test.describe('Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page)
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
      // Playwright 的 expect 自带自动重试，无需手动 waitForTimeout
      await expect(navItems.nth(1)).toHaveClass(/active|selected|current/)
    }
  })
})
