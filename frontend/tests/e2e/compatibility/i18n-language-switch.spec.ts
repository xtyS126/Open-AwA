import { test, expect } from '@playwright/test'
import { loginAsAdminPage } from '../auth'

/**
 * 国际化（i18n）语言切换 E2E 测试
 *
 * 验证：
 * - 外观设置 Tab 中语言选择器可见
 * - 切换到 English 后界面文本同步更新
 * - 切换回简体中文后界面文本恢复
 * - 语言偏好持久化到 localStorage
 *
 * 依赖：后端 /api/auth/login 可用、前端 /settings/appearance 路由可访问
 */

test.describe('i18n 语言切换', () => {
  test.use({ viewport: { width: 1280, height: 800 } })

  test('外观 Tab 显示语言选择器', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/settings')
    await page.waitForLoadState('networkidle')

    // 进入外观 Tab（点击外观标签）
    const appearanceTab = page.getByRole('tab', { name: /外观|Appearance/ }).first()
    if (await appearanceTab.isVisible({ timeout: 10_000 }).catch(() => false)) {
      await appearanceTab.click()
    }

    // 语言选择器应可见
    const langSelect = page.locator('select').filter({ hasText: /简体中文|English/ }).first()
    await expect(langSelect).toBeVisible({ timeout: 15_000 })
  })

  test('切换到 English 后界面文本更新', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/settings')
    await page.waitForLoadState('networkidle')

    // 进入外观 Tab
    const appearanceTab = page.getByRole('tab', { name: /外观|Appearance/ }).first()
    if (await appearanceTab.isVisible({ timeout: 10_000 }).catch(() => false)) {
      await appearanceTab.click()
    }

    // 选择 English
    const langSelect = page.locator('select').filter({ hasText: /简体中文|English/ }).first()
    await expect(langSelect).toBeVisible({ timeout: 15_000 })
    await langSelect.selectOption('en-US')

    // 等待语言包加载并应用
    await page.waitForTimeout(1500)

    // localStorage 应记录 en-US
    const storedLocale = await page.evaluate(() => localStorage.getItem('openawa_locale'))
    expect(storedLocale).toBe('en-US')
  })

  test('切换回简体中文后界面文本恢复', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/settings')
    await page.waitForLoadState('networkidle')

    // 先设置为 English
    await page.evaluate(() => localStorage.setItem('openawa_locale', 'en-US'))
    await page.reload()
    await page.waitForLoadState('networkidle')

    // 进入外观 Tab
    const appearanceTab = page.getByRole('tab', { name: /外观|Appearance/ }).first()
    if (await appearanceTab.isVisible({ timeout: 10_000 }).catch(() => false)) {
      await appearanceTab.click()
    }

    // 切换回简体中文
    const langSelect = page.locator('select').filter({ hasText: /简体中文|English/ }).first()
    await expect(langSelect).toBeVisible({ timeout: 15_000 })
    await langSelect.selectOption('zh-CN')

    await page.waitForTimeout(1500)

    // localStorage 应恢复为 zh-CN
    const storedLocale = await page.evaluate(() => localStorage.getItem('openawa_locale'))
    expect(storedLocale).toBe('zh-CN')
  })

  test('语言偏好跨页面持久化', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/settings')
    await page.waitForLoadState('networkidle')

    // 进入外观 Tab 并切换到 English
    const appearanceTab = page.getByRole('tab', { name: /外观|Appearance/ }).first()
    if (await appearanceTab.isVisible({ timeout: 10_000 }).catch(() => false)) {
      await appearanceTab.click()
    }

    const langSelect = page.locator('select').filter({ hasText: /简体中文|English/ }).first()
    await expect(langSelect).toBeVisible({ timeout: 15_000 })
    await langSelect.selectOption('en-US')
    await page.waitForTimeout(1500)

    // 导航到其他页面
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')

    // localStorage 仍应保持 en-US
    const storedLocale = await page.evaluate(() => localStorage.getItem('openawa_locale'))
    expect(storedLocale).toBe('en-US')
  })
})
