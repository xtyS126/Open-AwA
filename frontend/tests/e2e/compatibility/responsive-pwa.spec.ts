import { test, expect } from '@playwright/test'

/**
 * PWA manifest 验证测试
 *
 * 验证 Web App Manifest 资源可访问性、字段完整性与 HTML 引用正确性。
 * 覆盖 SubTask 21.4：PWA manifest 验证用例
 *
 * 验证维度：
 * - manifest.webmanifest 返回 200 与正确 MIME 类型
 * - name / short_name / theme_color / display / icons 字段存在且合法
 * - 图标尺寸包含 192x192 与 512x512
 * - index.html 中 <link rel="manifest"> 引用存在
 * - theme-color meta 标签存在（支持双主题）
 */

/** manifest.webmanifest 中单个图标的类型 */
interface ManifestIcon {
  src: string
  sizes: string
  type: string
  purpose?: string
}

/** Web App Manifest 的结构化类型（仅约束测试关心的字段） */
interface WebAppManifest {
  name: string
  short_name: string
  description?: string
  start_url?: string
  scope?: string
  display: string
  orientation?: string
  background_color?: string
  theme_color: string
  icons: ManifestIcon[]
}

/** 合法的 display 值（W3C 规范） */
const VALID_DISPLAY_VALUES = ['standalone', 'fullscreen', 'minimal-ui', 'browser'] as const

test.describe('PWA manifest 验证', () => {
  test('manifest.webmanifest - 返回 200 状态与正确 Content-Type', async ({ request }) => {
    const response = await request.get('/manifest.webmanifest')
    expect(response.status()).toBe(200)

    // MIME 类型应为 application/manifest+json（部分服务器可能返回 application/json）
    const contentType = response.headers()['content-type'] ?? ''
    expect(
      contentType.includes('application/manifest+json') || contentType.includes('application/json'),
      `Content-Type 应为 manifest+json 或 json，实际: ${contentType}`,
    ).toBe(true)
  })

  test('manifest.webmanifest - 包含 name/short_name/theme_color/display 必需字段', async ({ request }) => {
    const response = await request.get('/manifest.webmanifest')
    const manifest = (await response.json()) as WebAppManifest

    // name 必须存在且为非空字符串
    expect(manifest.name, 'name 字段必须存在').toBeTruthy()
    expect(typeof manifest.name).toBe('string')

    // short_name 必须存在且为非空字符串
    expect(manifest.short_name, 'short_name 字段必须存在').toBeTruthy()
    expect(typeof manifest.short_name).toBe('string')

    // theme_color 必须存在且为合法十六进制颜色
    expect(manifest.theme_color, 'theme_color 字段必须存在').toBeTruthy()
    expect(manifest.theme_color).toMatch(/^#[0-9a-fA-F]{6}$/)

    // display 必须为规范定义的合法值
    expect(manifest.display, 'display 字段必须存在').toBeTruthy()
    expect(
      VALID_DISPLAY_VALUES,
      `display 应为合法值，实际: ${manifest.display}`,
    ).toContain(manifest.display as (typeof VALID_DISPLAY_VALUES)[number])
  })

  test('manifest.webmanifest - icons 字段包含 192x192 与 512x512 尺寸', async ({ request }) => {
    const response = await request.get('/manifest.webmanifest')
    const manifest = (await response.json()) as WebAppManifest

    // icons 必须为数组且至少 2 个（192 + 512）
    expect(Array.isArray(manifest.icons), 'icons 必须为数组').toBe(true)
    expect(manifest.icons.length, 'icons 至少包含 2 个尺寸').toBeGreaterThanOrEqual(2)

    const sizesList = manifest.icons.map((icon) => icon.sizes)
    expect(sizesList, '应包含 192x192 图标').toContain('192x192')
    expect(sizesList, '应包含 512x512 图标').toContain('512x512')

    // 每个图标必须有 src 与 type 字段
    for (const icon of manifest.icons) {
      expect(icon.src, '图标 src 不能为空').toBeTruthy()
      expect(icon.type, '图标 type 不能为空').toBeTruthy()
    }
  })

  test('index.html - 包含 <link rel="manifest"> 引用', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('domcontentloaded')

    // link[rel="manifest"] 应存在且 href 指向 /manifest.webmanifest
    const manifestLink = page.locator('link[rel="manifest"]')
    await expect(manifestLink).toHaveCount(1)
    await expect(manifestLink).toHaveAttribute('href', '/manifest.webmanifest')
  })

  test('index.html - 包含 theme-color meta 标签', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('domcontentloaded')

    // theme-color meta 应至少存在一个（亮色/暗色双主题配置）
    const themeColorMeta = page.locator('meta[name="theme-color"]')
    const count = await themeColorMeta.count()
    expect(count, '应至少有一个 theme-color meta 标签').toBeGreaterThanOrEqual(1)
  })
})
