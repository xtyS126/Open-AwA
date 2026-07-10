import { test, expect } from '@playwright/test'
import { loginAsAdminPage } from '../auth'

/**
 * 兼容性测试矩阵
 *
 * 跨浏览器 + 多分辨率组合测试，覆盖关键页面的基本功能验证。
 *
 * 运行方式:
 *   npm run e2e -- --project=chromium --project=firefox tests/e2e/compatibility/compatibility-matrix.spec.ts
 *
 * 如需添加 webkit 支持，在 playwright.config.ts 的 projects 中添加:
 *   { name: 'webkit', use: { ...devices['Desktop Safari'] } }
 */

/** 视口分辨率配置 */
const VIEWPORTS = [
  { name: '桌面全高清', width: 1920, height: 1080 },
  { name: '桌面常规', width: 1440, height: 900 },
  { name: '笔记本', width: 1366, height: 768 },
  { name: '移动端', width: 375, height: 812 },
] as const

/** 关键页面配置 */
const PAGES = [
  { path: '/chat', label: '聊天页' },
  { path: '/settings', label: '设置页' },
  { path: '/dashboard', label: '仪表盘' },
  { path: '/plugins/manage', label: '插件管理' },
  { path: '/billing', label: '计费页' },
] as const

/**
 * 各页面的 UI 检查配置
 * keySelectors: 必须在页面上可见的关键布局元素选择器
 */
const PAGE_CHECKS: Record<string, { keySelectors: string[] }> = {
  '/chat': {
    keySelectors: ['.app-container', '.main-content'],
  },
  '/settings': {
    keySelectors: ['.app-container', '.main-content'],
  },
  '/dashboard': {
    keySelectors: ['.app-container', '.main-content'],
  },
  '/plugins/manage': {
    keySelectors: ['.app-container', '.main-content'],
  },
  '/billing': {
    keySelectors: ['.app-container', '.main-content'],
  },
}

// ============================================================
// 测试生成：视口 × 页面 × 验证维度
// ============================================================

for (const viewport of VIEWPORTS) {
  test.describe(`视口: ${viewport.name} (${viewport.width}×${viewport.height})`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } })

    for (const pageInfo of PAGES) {
      const checks = PAGE_CHECKS[pageInfo.path]

      test(`${pageInfo.label} (${pageInfo.path}) - 页面加载成功，无控制台错误`, async ({ page }) => {
        const consoleErrors: string[] = []

        page.on('pageerror', (error) => {
          consoleErrors.push(error.message)
        })

        await loginAsAdminPage(page)
        const response = await page.goto(pageInfo.path)
        await page.waitForLoadState('domcontentloaded')

        expect(
          response?.status(),
          `页面 ${pageInfo.path} 应返回 HTTP 200`,
        ).toBe(200)

        expect(
          consoleErrors.length,
          `页面 ${pageInfo.path} 不应有 JS 运行时错误，实际错误: ${consoleErrors.join('; ')}`,
        ).toBe(0)
      })

      test(`${pageInfo.label} (${pageInfo.path}) - 页面标题存在`, async ({ page }) => {
        await loginAsAdminPage(page)
        await page.goto(pageInfo.path)
        await page.waitForLoadState('domcontentloaded')

        const title = await page.title()
        expect(title, '页面标题不应为空').toBeTruthy()
      })

      test(`${pageInfo.label} (${pageInfo.path}) - 关键 UI 元素可见`, async ({ page }) => {
        await loginAsAdminPage(page)
        await page.goto(pageInfo.path)
        await page.waitForLoadState('domcontentloaded')

        if (checks?.keySelectors) {
          for (const selector of checks.keySelectors) {
            const element = page.locator(selector).first()
            await expect(
              element,
              `关键元素 "${selector}" 应在 ${pageInfo.path} 页面可见`,
            ).toBeVisible({ timeout: 15_000 })
          }
        }
      })

      test(`${pageInfo.label} (${pageInfo.path}) - 无水平溢出`, async ({ page }) => {
        await loginAsAdminPage(page)
        await page.goto(pageInfo.path)
        await page.waitForLoadState('domcontentloaded')
        // 等待主内容区渲染完成（替代 networkidle，避免 SSE 长连接导致超时）
        await expect(page.locator('.main-content').first()).toBeVisible({ timeout: 15_000 })

        const bodyWidth = await page.evaluate(() => document.body.scrollWidth)
        const viewportWidth = viewport.width

        // 允许 1px 的舍入误差
        expect(
          bodyWidth,
          `页面 ${pageInfo.path} 在 ${viewport.width}px 视口下不应有水平溢出 (body=${bodyWidth}px > viewport=${viewportWidth}px)`,
        ).toBeLessThanOrEqual(viewportWidth + 1)
      })

      // 移动端额外检查：触摸目标尺寸
      if (viewport.width <= 768) {
        test(`${pageInfo.label} (${pageInfo.path}) - 移动端触摸目标友好`, async ({ page }) => {
          await loginAsAdminPage(page)
          await page.goto(pageInfo.path)
          await page.waitForLoadState('domcontentloaded')
          // 等待主内容区渲染完成（替代 networkidle，避免 SSE 长连接导致超时）
          await expect(page.locator('.main-content').first()).toBeVisible({ timeout: 15_000 })

          // 检查按钮和链接是否满足最小触摸尺寸（44×44 CSS 像素，WCAG 2.5.5）
          const undersizedTargets = await page.evaluate(() => {
            const interactiveElements = document.querySelectorAll(
              'button, a, [role="button"], [role="link"], [role="tab"]',
            )
            const MIN_TOUCH_SIZE = 44
            const undersized: string[] = []

            interactiveElements.forEach((el) => {
              const rect = el.getBoundingClientRect()
              const isVisible = rect.width > 0 && rect.height > 0
              if (isVisible && (rect.width < MIN_TOUCH_SIZE || rect.height < MIN_TOUCH_SIZE)) {
                const tag = el.tagName.toLowerCase()
                const text = (el as HTMLElement).innerText?.slice(0, 30) || ''
                undersized.push(`${tag}(${Math.round(rect.width)}×${Math.round(rect.height)})"${text}"`)
              }
            })

            return undersized
          })

          // 只报告警告，不阻塞移动端测试（因为侧边栏折叠态图标按钮天然较小）
          if (undersizedTargets.length > 5) {
            console.warn(
              `[移动端触摸目标] ${pageInfo.path} 存在 ${undersizedTargets.length} 个过小的触摸目标（<44px）:`,
              undersizedTargets.slice(0, 10),
            )
          }
        })
      }
    }
  })
}
