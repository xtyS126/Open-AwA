import { expect, test } from '@playwright/test'
import { loginAndSaveState } from './auth'

async function openWechatTab(page: Parameters<typeof loginAndSaveState>[0]) {
  await page.goto('/im')
  await expect(page.getByRole('heading', { name: 'IM 渠道管理', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '微信', exact: true }).click()
  await expect(page.getByRole('heading', { name: '微信通讯配置', exact: true })).toBeVisible()
}

test.describe('微信自动回复 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAndSaveState(page)
    await openWechatTab(page)
  })

  test('微信标签展示配置、绑定和自动回复区域', async ({ page }) => {
    await expect(page.getByRole('heading', { name: '微信通讯配置', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: '绑定状态', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: '自动回复', exact: true })).toBeVisible()
  })

  test('自动回复规则表单可填写并校验必填字段', async ({ page }) => {
    const rulesSection = page.getByRole('heading', { name: '自动回复规则配置', exact: true }).locator('..')
    await expect(rulesSection).toBeVisible()
    await rulesSection.getByRole('button', { name: '添加规则', exact: true }).click()

    await rulesSection.getByPlaceholder('输入规则名称').fill('E2E 测试规则')
    await rulesSection.getByRole('combobox').selectOption('keyword')
    await rulesSection.getByPlaceholder('输入触发关键词').fill('e2e test pattern')
    await rulesSection.getByPlaceholder('输入自动回复内容').fill('e2e test reply')

    await expect(rulesSection.getByRole('button', { name: '保存规则', exact: true })).toBeEnabled()
  })

  test('未绑定账号时自动回复控制被明确禁用', async ({ page }) => {
    await expect(page.getByText('当前未完成绑定，自动回复操作暂不可用。')).toBeVisible()
    await expect(page.getByRole('button', { name: '启动自动回复', exact: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: '停止自动回复', exact: true })).toBeDisabled()
  })
})
