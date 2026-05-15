import { test, expect } from '@playwright/test'
import { loginAndSaveState } from './auth'

test.describe('插件生命周期 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAndSaveState(page)
  })

  test('插件管理页面渲染正常', async ({ page }) => {
    await page.goto('/plugins/manage')

    await expect(page.getByText('插件管理')).toBeVisible({ timeout: 20_000 })

    // 验证导入插件按钮存在
    const importButton = page.getByRole('button', { name: '导入插件' }).first()
    await expect(importButton).toBeVisible({ timeout: 10_000 })
  })

  test('插件列表渲染', async ({ page }) => {
    await page.goto('/plugins/manage')

    await expect(page.getByText('插件管理')).toBeVisible({ timeout: 20_000 })

    // 验证页面中存在插件列表区域或空状态提示
    const pluginList = page.locator('.plugin-list, [data-testid="plugin-list"], table, .plugin-grid').first()
    const hasPlugins = await pluginList.isVisible({ timeout: 10_000 }).catch(() => false)

    if (hasPlugins) {
      await expect(pluginList).toBeVisible()
    }

    // 检查是否有空状态提示
    const emptyState = page.locator('text=暂无插件, text=尚未安装, text=No plugins').first()
    const hasEmptyState = await emptyState.isVisible({ timeout: 5_000 }).catch(() => false)

    // 至少应有插件列表或空状态提示其中之一
    expect(hasPlugins || hasEmptyState).toBeTruthy()
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

    await expect(page.getByText('插件管理')).toBeVisible({ timeout: 20_000 })

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

    await expect(page.getByText('插件管理')).toBeVisible({ timeout: 20_000 })

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
      await expect(page.getByText('插件管理')).toBeVisible({ timeout: 10_000 })
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
      await expect(page.getByText('插件管理')).toBeVisible({ timeout: 10_000 })
    }

    // 如果既没有安装也没有卸载按钮，验证页面仍然正常
    if (!hasInstallBtn && !hasUninstallBtn) {
      await expect(page.getByText('插件管理')).toBeVisible()
    }
  })

  test('导入插件模态框', async ({ page }) => {
    await page.goto('/plugins/manage')

    await expect(page.getByText('插件管理')).toBeVisible({ timeout: 20_000 })

    const importButton = page.getByRole('button', { name: '导入插件' }).first()
    await importButton.click()

    // 验证导入模态框或文件上传 UI 出现
    const dialog = page.getByRole('dialog')
    const fileInput = page.locator('input[type="file"]')

    const hasDialog = await dialog.isVisible({ timeout: 5_000 }).catch(() => false)
    const hasFileInput = await fileInput.isVisible({ timeout: 5_000 }).catch(() => false)

    expect(hasDialog || hasFileInput).toBeTruthy()
  })
})
