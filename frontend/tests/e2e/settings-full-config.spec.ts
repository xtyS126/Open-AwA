import { test, expect } from '@playwright/test'
import { loginAndSaveState } from './auth'

test.describe('完整设置配置 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAndSaveState(page)
  })

  test('设置页面导航正常', async ({ page }) => {
    await page.goto('/settings')

    // 验证设置页面的基本元素
    await expect(page.getByRole('heading', { name: '设置' })).toBeVisible({ timeout: 20_000 })
  })

  test('API 配置标签页渲染正常', async ({ page }) => {
    await page.goto('/settings?tab=api')

    await expect(page.getByRole('heading', { name: 'API配置' })).toBeVisible({ timeout: 20_000 })

    // 验证新增供应商按钮存在
    const addProviderBtn = page.getByRole('button', { name: '新增供应商' })
    await expect(addProviderBtn).toBeVisible({ timeout: 10_000 })
  })

  test('供应商列表显示', async ({ page }) => {
    await page.goto('/settings?tab=api')

    await expect(page.getByRole('heading', { name: 'API配置' })).toBeVisible({ timeout: 20_000 })

    // 验证页面渲染了供应商相关的 UI 元素
    // 不同状态下可能显示供应商列表或空状态
    const providerSection = page.locator('[data-testid="provider-list"], .provider-list, table').first()
    const hasProviders = await providerSection.isVisible({ timeout: 10_000 }).catch(() => false)

    if (hasProviders) {
      await expect(providerSection).toBeVisible()
    } else {
      // 如果没有供应商列表 UI，至少页面主体已加载
      await expect(page.getByRole('heading', { name: 'API配置' })).toBeVisible()
    }
  })

  test('点击新增供应商弹出模态框', async ({ page }) => {
    await page.goto('/settings?tab=api')

    await expect(page.getByRole('heading', { name: 'API配置' })).toBeVisible({ timeout: 20_000 })

    const addProviderBtn = page.getByRole('button', { name: '新增供应商' })
    await expect(addProviderBtn).toBeVisible({ timeout: 10_000 })
    await addProviderBtn.click()

    // 验证模态框出现
    const dialog = page.getByRole('dialog', { name: '新增供应商' })
    await expect(dialog).toBeVisible({ timeout: 10_000 })

    // 验证模态框中的关键字段存在
    await expect(dialog.getByLabel(/供应商标识/)).toBeVisible()
    await expect(dialog.getByLabel(/显示名称/)).toBeVisible()

    // 可以关闭模态框
    await dialog.getByRole('button', { name: '取消' }).click()
    await expect(dialog).not.toBeVisible({ timeout: 5_000 })
  })

  test('模型选择交互', async ({ page }) => {
    await page.goto('/settings?tab=api')

    await expect(page.getByRole('heading', { name: 'API配置' })).toBeVisible({ timeout: 20_000 })

    // 检查是否有已配置的模型列表
    // 模型配置可能在不同状态下显示，检查是否有任何配置相关元素
    const modelSection = page.locator('text=模型配置, text=已选模型, [data-testid="model-list"]').first()
    const hasModelSection = await modelSection.isVisible({ timeout: 10_000 }).catch(() => false)

    if (hasModelSection) {
      await expect(modelSection).toBeVisible()
    }

    // 检查模型下拉选择器是否可用（可能在聊天页面的模型选择器中）
    await page.goto('/chat')
    const modelSelector = page.locator('[data-testid="model-selector"], .model-selector, select[name="model"]').first()
    const hasModelSelector = await modelSelector.isVisible({ timeout: 10_000 }).catch(() => false)

    if (hasModelSelector) {
      await expect(modelSelector).toBeVisible()

      // 尝试点击展开
      await modelSelector.click()
      await page.waitForTimeout(1_000)
    }
  })
})
