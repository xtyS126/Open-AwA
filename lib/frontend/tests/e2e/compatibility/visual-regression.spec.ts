import { expect, test, type Page } from '@playwright/test'
import { loginAsAdminPage } from '../auth'

/**
 * 视觉回归只覆盖稳定、可重复的页面状态。
 *
 * 每个用例使用全新的浏览器上下文，并在首次页面加载前固定语言和主题。
 * 聊天消息与会话历史属于运行时数据，截图时会遮罩，避免把时间戳或会话标识误判为界面回归。
 */
const SCREENSHOT_PAGES = [
  { path: '/chat', label: '聊天页' },
  { path: '/settings', label: '设置页' },
  { path: '/dashboard', label: '仪表盘' },
  { path: '/plugins/manage', label: '插件管理' },
  { path: '/billing', label: '计费页' },
] as const

const SCREENSHOT_VIEWPORTS = [
  { name: 'desktop', width: 1920, height: 1080 },
  { name: 'laptop', width: 1440, height: 900 },
  { name: 'mobile', width: 375, height: 812 },
] as const

async function prepareVisualPage(page: Page, path: string): Promise<void> {
  await page.route('**/api/user/preferences', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ preferences: {} }),
    })
  })

  await page.addInitScript(() => {
    const initializedKey = '__openawa_visual_test_initialized__'
    if (sessionStorage.getItem(initializedKey)) return

    sessionStorage.setItem(initializedKey, 'true')
    localStorage.setItem('openawa_locale', 'zh-CN')
    localStorage.setItem('theme', 'light')
  })

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await loginAsAdminPage(page)
  await ensureTheme(page, 'light')
  await page.goto(path)
  await expect(page.locator('#main-content')).toBeVisible({ timeout: 15_000 })
  await page.evaluate(async () => {
    await document.fonts.ready
  })
  await waitForVisualContent(page, path)
}

async function waitForVisualContent(page: Page, path: string): Promise<void> {
  if (path === '/dashboard') {
    await expect(page.getByText('今日交互')).toBeVisible({ timeout: 15_000 })
  }

  if (path === '/billing') {
    await expect(page.getByRole('button', { name: '导出CSV' })).toBeVisible({ timeout: 15_000 })
  }
}

async function ensureTheme(page: Page, targetTheme: 'light' | 'dark'): Promise<void> {
  const themeButton = page.getByTestId('theme-toggle-btn')
  const html = page.locator('html')
  const targetIsDark = targetTheme === 'dark'

  await expect(themeButton).toBeVisible()
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const isDark = await html.evaluate((element) => element.classList.contains('dark'))
    if (isDark === targetIsDark) {
      await page.waitForTimeout(250)
      const settledIsDark = await html.evaluate((element) => element.classList.contains('dark'))
      if (settledIsDark === targetIsDark) return
    }

    await themeButton.click()
  }

  const expectedClass = targetIsDark ? /dark/ : /^$/
  await expect(html).toHaveClass(expectedClass)
}

function getDynamicMasks(page: Page, path: string) {
  if (path !== '/chat') return []

  return [
    page.locator('[role="log"]'),
    page.locator('[aria-label*="聊天历史"], [aria-label*="Chat history"]'),
  ]
}

async function expectPageScreenshot(page: Page, path: string): Promise<void> {
  await expect(page).toHaveScreenshot({
    animations: 'disabled',
    caret: 'hide',
    fullPage: true,
    mask: getDynamicMasks(page, path),
    maxDiffPixelRatio: 0.005,
    threshold: 0.2,
  })
}

for (const viewport of SCREENSHOT_VIEWPORTS) {
  test.describe(`视觉回归 - ${viewport.name} (${viewport.width}×${viewport.height})`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    for (const pageInfo of SCREENSHOT_PAGES) {
      test(`${pageInfo.label} - ${pageInfo.path} - 全页截图对比`, async ({ page }) => {
        await prepareVisualPage(page, pageInfo.path)
        await expectPageScreenshot(page, pageInfo.path)
      })
    }
  })
}

test.describe('视觉回归 - 暗色模式', () => {
  test.use({ viewport: { width: 1920, height: 1080 } })

  for (const pageInfo of [
    { path: '/chat', label: '聊天页' },
    { path: '/dashboard', label: '仪表盘' },
  ] as const) {
    test(`${pageInfo.label} - 暗色主题截图`, async ({ page }) => {
      await prepareVisualPage(page, '/chat')

      await ensureTheme(page, 'dark')

      await page.goto(pageInfo.path)
      await expect(page.locator('#main-content')).toBeVisible({ timeout: 15_000 })
      await waitForVisualContent(page, pageInfo.path)
      await expectPageScreenshot(page, pageInfo.path)
    })
  }
})

test.describe('视觉回归 - 交互状态', () => {
  test.use({ viewport: { width: 1920, height: 1080 } })

  test('聊天页 - 侧边栏折叠态', async ({ page }) => {
    await prepareVisualPage(page, '/chat')

    const collapseButton = page.getByTestId('sidebar-collapse-btn')
    await expect(collapseButton).toBeVisible()
    await collapseButton.click()
    await expect(page.locator('[data-testid="sidebar"]')).toHaveAttribute('data-collapsed', 'true')

    await expect(page).toHaveScreenshot({
      animations: 'disabled',
      caret: 'hide',
      fullPage: false,
      mask: getDynamicMasks(page, '/chat'),
      maxDiffPixelRatio: 0.005,
      threshold: 0.2,
    })
  })

  test('设置页 - 外观标签页', async ({ page }) => {
    await prepareVisualPage(page, '/settings?tab=appearance')
    await expect(page.locator('select').first()).toBeVisible()

    await expect(page).toHaveScreenshot({
      animations: 'disabled',
      caret: 'hide',
      fullPage: false,
      maxDiffPixelRatio: 0.005,
      threshold: 0.2,
    })
  })
})
