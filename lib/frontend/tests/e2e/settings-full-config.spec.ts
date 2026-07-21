import { expect, test } from '@playwright/test'
import { loginAsAdminPage } from './auth'

test.describe('完整设置配置 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdminPage(page)
  })

  test('设置页面展示完整一级分类', async ({ page }) => {
    await page.goto('/settings')

    await expect(page.getByRole('heading', { name: '设置', exact: true })).toBeVisible()
    for (const tab of ['通用', '画像', '模型', '外观', '搜索', '提示词', '计费', '后端连接', '高级']) {
      await expect(page.getByRole('tab', { name: tab })).toBeVisible()
    }
  })

  test('模型配置页展示供应商管理合同', async ({ page }) => {
    await page.goto('/settings?tab=api')

    await expect(page.getByRole('tab', { name: '模型' })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('heading', { name: 'API配置' })).toBeVisible()
    await expect(page.getByText('左侧管理供应商，右侧配置基础 URL、API Key，并从远端获取模型后用复选框选择。')).toBeVisible()
    await expect(page.getByRole('button', { name: '新增供应商' })).toBeVisible()
  })

  test('新增供应商模态框包含必需字段并可关闭', async ({ page }) => {
    await page.goto('/settings?tab=api')
    await page.getByRole('button', { name: '新增供应商' }).click()

    const dialog = page.getByRole('dialog', { name: '新增供应商' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByLabel(/供应商标识/)).toBeVisible()
    await expect(dialog.getByLabel(/显示名称/)).toBeVisible()

    await dialog.getByRole('button', { name: '取消' }).click()
    await expect(dialog).toBeHidden()
  })

  test('数据保留设置提供可编辑范围与清理开关', async ({ page }) => {
    await page.goto('/settings?tab=advanced&sub=data-retention')

    await expect(page.getByRole('heading', { name: '数据保留设置' })).toBeVisible()
    const retentionDays = page.getByRole('spinbutton')
    await expect(retentionDays).toHaveAttribute('min', '1')
    await expect(retentionDays).toHaveAttribute('max', '3650')
    await expect(page.getByLabel('保存后清理超出保留期限的旧数据')).toBeVisible()
    await expect(page.getByRole('button', { name: '保存设置' })).toBeVisible()
  })
})
