import { test, expect } from '@playwright/test'
import { loginAsAdminPage } from '../auth'

/**
 * 响应式布局专项测试
 *
 * 验证关键页面在不同断点下的布局行为：
 * - 桌面端 (>= 1025px)：侧边栏展开、主内容区正常
 * - 平板端 (768px - 1024px)：布局适应性
 * - 移动端 (<= 767px)：汉堡菜单、遮罩层、触摸友好
 * - 横屏/竖屏切换
 */

// ============================================================
// 桌面端测试 (1920×1080)
// ============================================================

test.describe('桌面端布局 (1920×1080)', () => {
  test.use({ viewport: { width: 1920, height: 1080 } })

  test.describe('聊天页 /chat', () => {
    test('侧边栏应展开并显示导航项', async ({ page }) => {
      await loginAsAdminPage(page)
      await page.waitForLoadState('networkidle')

      // 侧边栏容器应可见
      const sidebar = page.locator('.sidebar').first()
      await expect(sidebar).toBeVisible({ timeout: 15_000 })

      // 侧边栏不应处于折叠态
      await expect(sidebar).not.toHaveClass(/collapsed/)

      // 导航项"聊天"应可见（激活态）
      const chatNav = page.locator('.sidebar-item').filter({ hasText: '聊天' }).first()
      await expect(chatNav).toBeVisible()
    })

    test('主内容区与侧边栏并排显示', async ({ page }) => {
      await loginAsAdminPage(page)
      await page.waitForLoadState('networkidle')

      const mainContent = page.locator('.main-content').first()
      await expect(mainContent).toBeVisible()

      // 主内容区宽度应小于视口宽度（侧边栏占用了部分空间）
      const mainBox = await mainContent.boundingBox()
      expect(mainBox).not.toBeNull()
      expect(mainBox!.width).toBeLessThan(1920)
      expect(mainBox!.width).toBeGreaterThan(800)
    })

    test('侧边栏宽度应为默认 260px', async ({ page }) => {
      await loginAsAdminPage(page)
      await page.waitForLoadState('networkidle')

      const sidebarWidth = await page.evaluate(() => {
        const el = document.querySelector('.sidebar') as HTMLElement | null
        if (!el) return 0
        return el.getBoundingClientRect().width
      })

      expect(sidebarWidth).toBeCloseTo(260, -1)
    })
  })

  test.describe('仪表盘 /dashboard', () => {
    test('主内容区可见且正常布局', async ({ page }) => {
      await loginAsAdminPage(page)
      await page.goto('/dashboard')
      await page.waitForLoadState('networkidle')

      const mainContent = page.locator('.main-content').first()
      await expect(mainContent).toBeVisible({ timeout: 15_000 })
    })
  })

  test.describe('设置页 /settings', () => {
    test('侧边栏和主内容区均可见', async ({ page }) => {
      await loginAsAdminPage(page)
      await page.goto('/settings')
      await page.waitForLoadState('networkidle')

      const sidebar = page.locator('.sidebar').first()
      const mainContent = page.locator('.main-content').first()

      await expect(sidebar).toBeVisible()
      await expect(mainContent).toBeVisible()
    })
  })
})

// ============================================================
// 平板端测试 (1024×768)
// ============================================================

test.describe('平板端布局 (1024×768)', () => {
  test.use({ viewport: { width: 1024, height: 768 } })

  test('聊天页 - 侧边栏可见（768px 以上不触发移动端断点）', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('networkidle')

    const sidebar = page.locator('.sidebar').first()
    await expect(sidebar).toBeVisible({ timeout: 15_000 })

    // 移动端汉堡菜单不应显示（断点 max-width: 768px）
    const mobileMenu = page.locator('.mobile-menu-btn').first()
    await expect(mobileMenu).not.toBeVisible()
  })

  test('聊天页 - 主内容区宽度合理', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('networkidle')

    const mainContent = page.locator('.main-content').first()
    await expect(mainContent).toBeVisible()

    const mainBox = await mainContent.boundingBox()
    expect(mainBox).not.toBeNull()
    // 1024 - 260(侧边栏) ≈ 764px，允许一些边距浮动
    expect(mainBox!.width).toBeGreaterThan(500)
    expect(mainBox!.width).toBeLessThan(1024)
  })

  test('仪表盘 - 页面正常加载', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')

    const mainContent = page.locator('.main-content').first()
    await expect(mainContent).toBeVisible({ timeout: 15_000 })
  })
})

// ============================================================
// 移动端测试 (375×812)
// ============================================================

test.describe('移动端布局 (375×812)', () => {
  test.use({ viewport: { width: 375, height: 812 } })

  test('聊天页 - 汉堡菜单按钮可见', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('networkidle')

    // 移动端汉堡菜单按钮应该可见
    const mobileMenu = page.locator('.mobile-menu-btn').first()
    await expect(mobileMenu).toBeVisible({ timeout: 15_000 })
  })

  test('聊天页 - 侧边栏默认隐藏', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('networkidle')

    const sidebar = page.locator('.sidebar').first()
    // 移动端侧边栏默认隐藏，不应有 mobile-open 类
    await expect(sidebar).not.toHaveClass(/mobile-open/)
  })

  test('聊天页 - 点击汉堡菜单可展开侧边栏', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('networkidle')

    const mobileMenu = page.locator('.mobile-menu-btn').first()
    await expect(mobileMenu).toBeVisible({ timeout: 15_000 })

    // 点击汉堡菜单展开侧边栏
    await mobileMenu.click()

    const sidebar = page.locator('.sidebar').first()
    await expect(sidebar).toHaveClass(/mobile-open/)

    // 应显示遮罩层
    const overlay = page.locator('.mobile-overlay').first()
    await expect(overlay).toBeVisible()
  })

  test('聊天页 - 点击遮罩层可关闭侧边栏', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('networkidle')

    // 展开侧边栏
    await page.locator('.mobile-menu-btn').first().click()
    const sidebar = page.locator('.sidebar').first()
    await expect(sidebar).toHaveClass(/mobile-open/)

    // 点击遮罩层关闭
    const overlay = page.locator('.mobile-overlay').first()
    await overlay.click()

    // 侧边栏应关闭
    await expect(sidebar).not.toHaveClass(/mobile-open/)
  })

  test('聊天页 - 主内容区占满视口宽度', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('networkidle')

    const mainContent = page.locator('.main-content').first()
    await expect(mainContent).toBeVisible({ timeout: 15_000 })

    const mainBox = await mainContent.boundingBox()
    expect(mainBox).not.toBeNull()
    // 移动端主内容区应接近满宽
    expect(mainBox!.width).toBeGreaterThan(300)
  })

  test('仪表盘 - 移动端页面正常加载', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')

    const mainContent = page.locator('.main-content').first()
    await expect(mainContent).toBeVisible({ timeout: 15_000 })

    // 移动端汉堡菜单可见
    await expect(page.locator('.mobile-menu-btn').first()).toBeVisible()
  })
})

// ============================================================
// 横竖屏切换测试
// ============================================================

test.describe('横竖屏切换', () => {
  test('移动端竖屏→横屏 布局自适应', async ({ page }) => {
    // 初始：竖屏 375×812
    await page.setViewportSize({ width: 375, height: 812 })
    await loginAsAdminPage(page)
    await page.waitForLoadState('networkidle')

    // 竖屏下汉堡菜单应可见
    await expect(page.locator('.mobile-menu-btn').first()).toBeVisible()

    // 切换到横屏 812×375
    await page.setViewportSize({ width: 812, height: 375 })
    await page.waitForLoadState('networkidle')

    // 横屏宽度 > 768px，汉堡菜单应隐藏
    const mobileMenu = page.locator('.mobile-menu-btn').first()
    const isVisible = await mobileMenu.isVisible().catch(() => false)
    expect(isVisible).toBe(false)
  })

  test('桌面端窗口调整后布局保持正常', async ({ page }) => {
    // 初始：桌面端
    await page.setViewportSize({ width: 1920, height: 1080 })
    await loginAsAdminPage(page)
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')

    // 调整到较小桌面窗口
    await page.setViewportSize({ width: 1280, height: 720 })
    await page.waitForLoadState('networkidle')

    // 主内容区仍然可见
    await expect(page.locator('.main-content').first()).toBeVisible({ timeout: 15_000 })
    // 侧边栏仍然可见（1280 > 768）
    await expect(page.locator('.sidebar').first()).toBeVisible()
  })
})
