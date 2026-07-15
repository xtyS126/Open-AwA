/**
 * E2E 设置页面测试 — 导航和 Tab 切换。
 */
import { test, expect } from '@playwright/test'
import { loginAsAdminPage } from './auth'

test.describe('Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdminPage(page)
  })

  test('navigates to settings page', async ({ page }) => {
    // 通过 URL 直接导航到设置页
    await page.goto('/settings')
    await expect(page).toHaveURL(/\/settings/, { timeout: 10000 })
  })

  test('settings page has navigation tabs', async ({ page }) => {
    await page.goto('/settings')
    const tabList = page.getByRole('tablist', { name: '设置分类' })
    await expect(tabList).toBeVisible()
    await expect(tabList.getByRole('tab')).toHaveCount(9)
  })

  test('can switch between settings tabs', async ({ page }) => {
    await page.goto('/settings')
    const appearanceTab = page.getByRole('tab', { name: '外观', exact: true })
    await appearanceTab.click()
    await expect(appearanceTab).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('heading', { name: /^(语言|Language)$/ })).toBeVisible()
  })
})
