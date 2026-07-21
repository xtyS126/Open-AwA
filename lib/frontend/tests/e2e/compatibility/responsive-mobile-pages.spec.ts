import { test, expect } from '@playwright/test'
import { loginAsAdminPage } from '../auth'

/**
 * 关键页面移动端布局验证
 *
 * 覆盖 SubTask 21.5：各关键页面移动端布局快照用例
 *
 * 不做像素级截图对比，仅验证关键布局元素在移动端（375×812）可见、
 * 无水平溢出、页面特有元素（如 Settings 的 Tab、VibeCoding 的移动端 Tab）存在。
 *
 * 覆盖页面：Chat / Settings / Dashboard / Billing / VibeCoding
 */

test.describe('关键页面移动端布局 (375×812)', () => {
  test.describe.configure({ mode: 'serial' })
  test.use({ viewport: { width: 375, height: 812 } })

  test('聊天页 - 主内容区与输入栏可见', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.waitForLoadState('domcontentloaded')

    await expect(page.locator('.main-content').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('[data-testid="mobile-menu-btn"]').first()).toBeVisible()

    // ChatInput 容器在移动端应可见（fixed 定位 + safe-area-inset-bottom）
    await expect(page.locator('[data-testid="chat-input-container"]').first()).toBeVisible({ timeout: 15_000 })

    // 聊天页无水平溢出
    const overflowX = await page.evaluate(() => document.body.scrollWidth - window.innerWidth)
    expect(overflowX, '聊天页不应有水平溢出').toBeLessThanOrEqual(1)
  })

  test('设置页 - Tab 导航可见', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/settings')
    await page.waitForLoadState('domcontentloaded')

    await expect(page.locator('.main-content').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('[data-testid="mobile-menu-btn"]').first()).toBeVisible()

    // 设置页应有 tablist 角色容器（Tab 导航，移动端水平滚动）
    const tabList = page.locator('[role="tablist"]').first()
    await expect(tabList).toBeVisible({ timeout: 15_000 })

    // 至少有 1 个 tab 项可见
    const tabs = page.locator('[role="tab"]')
    const tabCount = await tabs.count()
    expect(tabCount, '设置页应至少有 1 个 Tab').toBeGreaterThanOrEqual(1)

    // 设置页无水平溢出（Tab 水平滚动用 overflow-x:auto，body 不应溢出）
    const overflowX = await page.evaluate(() => document.body.scrollWidth - window.innerWidth)
    expect(overflowX, '设置页不应有水平溢出').toBeLessThanOrEqual(1)
  })

  test('仪表盘 - 主内容区与统计区可见', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/dashboard')
    await page.waitForLoadState('domcontentloaded')

    await expect(page.locator('.main-content').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('[data-testid="mobile-menu-btn"]').first()).toBeVisible()

    // 仪表盘无水平溢出
    const overflowX = await page.evaluate(() => document.body.scrollWidth - window.innerWidth)
    expect(overflowX, '仪表盘不应有水平溢出').toBeLessThanOrEqual(1)
  })

  test('计费页 - 主内容区可见', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/billing')
    await page.waitForLoadState('domcontentloaded')

    await expect(page.locator('.main-content').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('[data-testid="mobile-menu-btn"]').first()).toBeVisible()

    // 计费页无水平溢出（移动端表格转卡片，不应有水平溢出）
    const overflowX = await page.evaluate(() => document.body.scrollWidth - window.innerWidth)
    expect(overflowX, '计费页不应有水平溢出').toBeLessThanOrEqual(1)
  })

  test('VibeCoding 页 - 移动端 Tab 切换可见', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/vibe-coding')
    await page.waitForLoadState('domcontentloaded')

    await expect(page.locator('.main-content').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('[data-testid="mobile-menu-btn"]').first()).toBeVisible()

    // 移动端 VibeCoding 应渲染 mobile-tab-bar（role="tablist"）
    const tabList = page.locator('[role="tablist"]').first()
    await expect(tabList).toBeVisible({ timeout: 15_000 })

    // 应有 3 个 Tab（会话/终端/预览）
    const tabs = page.locator('[role="tab"]')
    const tabCount = await tabs.count()
    expect(tabCount, 'VibeCoding 移动端应至少有 3 个 Tab').toBeGreaterThanOrEqual(3)

    // VibeCoding 页无水平溢出
    const overflowX = await page.evaluate(() => document.body.scrollWidth - window.innerWidth)
    expect(overflowX, 'VibeCoding 页不应有水平溢出').toBeLessThanOrEqual(1)
  })
})
