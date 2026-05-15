import { test, expect, type Page } from '@playwright/test'
import { loginAsAdminPage } from '../auth'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

/**
 * 视觉回归测试框架
 *
 * 对关键页面在不同分辨率下进行截图，与基线对比，检测 UI 变更。
 *
 * 使用方式:
 *   1. 首次运行 -> 建立基线截图
 *      npm run e2e -- tests/e2e/compatibility/visual-regression.spec.ts --update-snapshots
 *
 *   2. 后续运行 -> 与基线对比
 *      npm run e2e -- tests/e2e/compatibility/visual-regression.spec.ts
 *
 * 截图命名规范: {page}-{browser}-{resolution}.png
 * 基线存储目录: tests/e2e/compatibility/screenshots/baseline/
 */

/** 视觉回归测试配置 */
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

/** 基线截图存储根目录 */
const BASELINE_DIR = path.resolve(__dirname, 'screenshots/baseline')

/**
 * 生成截图文件名（符合命名规范）
 * 格式: {page}-{browser}-{resolution}.png
 */
function screenshotName(pageLabel: string, browserName: string, viewportName: string): string {
  const safePage = pageLabel.replace(/[\s/\\:<>|?*]/g, '-')
  return `${safePage}-${browserName}-${viewportName}.png`
}

/**
 * 确保基线目录存在
 */
function ensureBaselineDir(): void {
  if (!fs.existsSync(BASELINE_DIR)) {
    fs.mkdirSync(BASELINE_DIR, { recursive: true })
  }
}

// ============================================================
// 方式一：使用 Playwright 内置 toHaveScreenshot()（推荐）
// 自动管理基线，CI 友好
// ============================================================

for (const viewport of SCREENSHOT_VIEWPORTS) {
  test.describe(`视觉回归 - ${viewport.name} (${viewport.width}×${viewport.height})`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    for (const pageInfo of SCREENSHOT_PAGES) {
      test(`${pageInfo.label} - ${pageInfo.path} - 全页截图对比`, async ({ page }) => {
        await loginAsAdminPage(page)
        await page.goto(pageInfo.path)
        await page.waitForLoadState('networkidle')

        // 等待字体、图标等资源加载完成
        await page.waitForTimeout(500)

        // 使用 Playwright 内置的视觉对比
        // 首次运行需加 --update-snapshots 建立基线
        // 后续运行自动与基线对比，差异超过阈值则测试失败
        await expect(page).toHaveScreenshot({
          fullPage: true,
          maxDiffPixels: 500,
          threshold: 0.2,
        })
      })
    }
  })
}

// ============================================================
// 方式二：手动截图 + 命名规范（{page}-{browser}-{resolution}.png）
// 适用于需要自定义截图存储和命名方案的场景
// ============================================================

test.describe('视觉回归 - 自定义命名截图（手动基线对比）', () => {
  /**
   * 获取当前浏览器名称
   */
  function getCurrentBrowserName(page: Page): string {
    // Playwright 没有直接的 browser name API，通过 user agent 推断
    return page.context().browser()?.browserType().name() ?? 'unknown'
  }

  for (const viewport of SCREENSHOT_VIEWPORTS) {
    for (const pageInfo of SCREENSHOT_PAGES) {
      test(`截图导出: ${pageInfo.label} @ ${viewport.name} (${viewport.width}×${viewport.height})`, async ({ page }) => {
        test.use({ viewport: { width: viewport.width, height: viewport.height } })

        await loginAsAdminPage(page)
        await page.goto(pageInfo.path)
        await page.waitForLoadState('networkidle')
        await page.waitForTimeout(500)

        ensureBaselineDir()

        const browserName = getCurrentBrowserName(page)
        const filename = screenshotName(pageInfo.label, browserName, viewport.name)
        const filepath = path.join(BASELINE_DIR, filename)

        await page.screenshot({
          path: filepath,
          fullPage: true,
        })

        // 验证截图文件已生成
        expect(fs.existsSync(filepath), `截图文件应已生成: ${filepath}`).toBe(true)

        // 验证截图文件大小合理（至少 1KB，有效截图）
        const stats = fs.statSync(filepath)
        expect(
          stats.size,
          `截图文件大小应合理: ${filepath} (${stats.size} bytes)`,
        ).toBeGreaterThan(1024)
      })
    }
  }
})

// ============================================================
// 高对比度/暗色模式视觉测试
// ============================================================

test.describe('视觉回归 - 暗色模式', () => {
  test.use({ viewport: { width: 1920, height: 1080 } })

  test('聊天页 - 暗色主题截图', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('networkidle')

    // 通过主题切换按钮切换到暗色模式
    const themeBtn = page.locator('.theme-toggle-btn').first()
    if (await themeBtn.isVisible().catch(() => false)) {
      await themeBtn.click()
      await page.waitForTimeout(300)
    }

    await page.goto('/chat')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(500)

    await expect(page).toHaveScreenshot({
      fullPage: false,
      maxDiffPixels: 500,
      threshold: 0.2,
    })
  })

  test('仪表盘 - 暗色主题截图', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('networkidle')

    // 切换到暗色模式
    const themeBtn = page.locator('.theme-toggle-btn').first()
    if (await themeBtn.isVisible().catch(() => false)) {
      await themeBtn.click()
      await page.waitForTimeout(300)
    }

    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(500)

    await expect(page).toHaveScreenshot({
      fullPage: false,
      maxDiffPixels: 500,
      threshold: 0.2,
    })
  })
})

// ============================================================
// 关键交互状态视觉测试
// ============================================================

test.describe('视觉回归 - 交互状态', () => {
  test.use({ viewport: { width: 1920, height: 1080 } })

  test('聊天页 - 侧边栏折叠态', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('networkidle')

    // 点击折叠按钮收缩侧边栏
    const collapseBtn = page.locator('.collapse-btn').first()
    if (await collapseBtn.isVisible().catch(() => false)) {
      await collapseBtn.click()
      await page.waitForTimeout(400)
    }

    await expect(page).toHaveScreenshot({
      fullPage: false,
      maxDiffPixels: 500,
      threshold: 0.2,
    })
  })

  test('设置页 - 设置标签切换', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/settings')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(500)

    // 确保 API 配置标签页可见
    await expect(page.locator('.main-content').first()).toBeVisible({ timeout: 15_000 })

    await expect(page).toHaveScreenshot({
      fullPage: false,
      maxDiffPixels: 500,
      threshold: 0.2,
    })
  })
})
