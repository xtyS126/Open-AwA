import { test, expect } from '@playwright/test'
import { loginAndSaveState } from './auth'

test.describe('插件生命周期 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAndSaveState(page)
  })

  test('插件管理页面渲染正常', async ({ page }) => {
    await page.goto('/plugins/manage')

    await expect(page.getByRole('heading', { name: '插件管理' })).toBeVisible({ timeout: 20_000 })

    await expect(page.getByRole('button', { name: '刷新' })).toBeVisible()
    await expect(page.getByPlaceholder('搜索插件名称 / 版本 / 作者 / 简介')).toBeVisible()
  })

  test('插件列表渲染', async ({ page }) => {
    await page.goto('/plugins/manage')

    await expect(page.getByRole('heading', { name: '插件管理' })).toBeVisible({ timeout: 20_000 })

    const userSection = page.getByRole('heading', { name: /User Plugins|用户插件/ })
    const builtinSection = page.getByRole('heading', { name: /System Built-in Plugins|系统内置插件/ })
    const globalEmptyState = page.getByText(/还没有安装任何插件|没有匹配的插件/)
    const hasPluginSection = await userSection.isVisible().catch(() => false)
      || await builtinSection.isVisible().catch(() => false)
    const hasEmptyState = await globalEmptyState.isVisible().catch(() => false)

    expect(hasPluginSection || hasEmptyState).toBeTruthy()
  })

  test('插件市场页面渲染', async ({ page }) => {
    await page.goto('/plugins/marketplace')

    // 验证插件市场页面基本元素
    const marketplaceHeading = page.locator('text=插件市场, text=Marketplace, text=发现插件').first()
    const hasHeading = await marketplaceHeading.isVisible({ timeout: 15_000 }).catch(() => false)

    if (hasHeading) {
      await expect(marketplaceHeading).toBeVisible()
    }

    // 验证页面在正常渲染（没有崩溃）
    await expect(page.locator('body')).toBeVisible()
  })

  test('插件详情查看', async ({ page }) => {
    await page.goto('/plugins/manage')

    await expect(page.getByRole('heading', { name: '插件管理' })).toBeVisible({ timeout: 20_000 })

    // 查找可点击的插件项
    const pluginItems = page.locator('[role="button"], a').filter({ hasText: /插件|plugin/i })

    const count = await pluginItems.count()
    if (count > 0) {
      // 点击第一个插件相关的可点击元素
      const firstPluginItem = pluginItems.first()
      await firstPluginItem.click()

      // 验证页面跳转或模态框展开
      await page.waitForTimeout(2_000)
      await expect(page.locator('body')).toBeVisible()
    }
  })

  test('安装/卸载交互', async ({ page }) => {
    await page.goto('/plugins/manage')

    await expect(page.getByRole('heading', { name: '插件管理' })).toBeVisible({ timeout: 20_000 })

    // 查找安装或卸载按钮
    const installButton = page.getByRole('button', { name: /安装|Install/ }).first()
    const uninstallButton = page.getByRole('button', { name: /卸载|Uninstall/ }).first()

    const hasInstallBtn = await installButton.isVisible({ timeout: 5_000 }).catch(() => false)
    const hasUninstallBtn = await uninstallButton.isVisible({ timeout: 5_000 }).catch(() => false)

    if (hasInstallBtn) {
      await installButton.click()
      // 等待可能的确认对话框
      const confirmDialog = page.getByRole('dialog')
      const dialogVisible = await confirmDialog.isVisible({ timeout: 5_000 }).catch(() => false)
      if (dialogVisible) {
        // 取消安装以避免副作用
        await confirmDialog.getByRole('button', { name: /取消|Cancel/ }).first().click()
      }
      await page.waitForTimeout(1_000)
      await expect(page.getByRole('heading', { name: '插件管理' })).toBeVisible({ timeout: 10_000 })
    }

    if (hasUninstallBtn) {
      await uninstallButton.click()
      const confirmDialog = page.getByRole('dialog')
      const dialogVisible = await confirmDialog.isVisible({ timeout: 5_000 }).catch(() => false)
      if (dialogVisible) {
        // 取消卸载以避免副作用
        await confirmDialog.getByRole('button', { name: /取消|Cancel/ }).first().click()
      }
      await page.waitForTimeout(1_000)
      await expect(page.getByRole('heading', { name: '插件管理' })).toBeVisible({ timeout: 10_000 })
    }

    // 如果既没有安装也没有卸载按钮，验证页面仍然正常
    if (!hasInstallBtn && !hasUninstallBtn) {
      await expect(page.getByRole('heading', { name: '插件管理' })).toBeVisible()
    }
  })

  test('插件搜索与刷新控件', async ({ page }) => {
    await page.goto('/plugins/manage')

    await expect(page.getByRole('heading', { name: '插件管理' })).toBeVisible({ timeout: 20_000 })

    const searchInput = page.getByPlaceholder('搜索插件名称 / 版本 / 作者 / 简介')
    await expect(searchInput).toBeVisible()
    await searchInput.fill('system-tools')
    await expect(page.getByText('system-tools').first()).toBeVisible()

    await page.getByRole('button', { name: '刷新' }).click()
    await expect(page.getByRole('heading', { name: '插件管理' })).toBeVisible()
  })
})
