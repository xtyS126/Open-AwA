import { expect, test } from '@playwright/test'
import { loginAsAdminPage } from '../auth'

async function openAppearanceSettings(page: Parameters<typeof loginAsAdminPage>[0]) {
  await page.goto('/settings?tab=appearance')
  const languageSelect = page.locator('select').first()
  await expect(languageSelect).toBeVisible()
  return languageSelect
}

test.describe('i18n 语言切换', () => {
  test.use({ viewport: { width: 1280, height: 800 } })

  test('外观 Tab 显示语言选择器', async ({ page }) => {
    await loginAsAdminPage(page)
    const languageSelect = await openAppearanceSettings(page)

    await expect(languageSelect).toHaveValue(/^(zh-CN|en-US|ja-JP|ru-RU)$/)
  })

  test('切换到 English 后界面文本和本地偏好同步更新', async ({ page }) => {
    await loginAsAdminPage(page)
    const languageSelect = await openAppearanceSettings(page)
    await languageSelect.selectOption('en-US')

    await expect(page.getByRole('heading', { name: 'Language' })).toBeVisible()
    await expect.poll(() => page.evaluate(() => localStorage.getItem('openawa_locale'))).toBe('en-US')
  })

  test('切换回简体中文后界面文本和本地偏好同步更新', async ({ page }) => {
    await loginAsAdminPage(page)
    const languageSelect = await openAppearanceSettings(page)
    await languageSelect.selectOption('zh-CN')

    await expect(page.getByRole('heading', { name: '语言' })).toBeVisible()
    await expect.poll(() => page.evaluate(() => localStorage.getItem('openawa_locale'))).toBe('zh-CN')
  })

  test('语言偏好跨页面保持', async ({ page }) => {
    await loginAsAdminPage(page)
    const languageSelect = await openAppearanceSettings(page)
    await languageSelect.selectOption('en-US')

    await page.goto('/dashboard')
    await expect(page.getByRole('link', { name: 'Chat' })).toBeVisible()
    await expect.poll(() => page.evaluate(() => localStorage.getItem('openawa_locale'))).toBe('en-US')
  })
})
