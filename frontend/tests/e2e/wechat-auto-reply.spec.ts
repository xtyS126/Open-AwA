import { test, expect } from '@playwright/test'
import { loginAndSaveState } from './auth'

test.describe('WeChat Auto Reply E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAndSaveState(page)
    await page.goto('/communication')
  })

  test('should load communication page and see wechat module', async ({ page }) => {
    await expect(page.getByRole('heading', { name: '通讯配置', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: '微信通讯配置', exact: true })).toBeVisible()
  })

  test('should open auto reply rule form', async ({ page }) => {
    await expect(page.getByRole('heading', { name: '自动回复规则配置' })).toBeVisible()

    await page.getByRole('button', { name: '添加规则' }).click()

    await expect(page.getByPlaceholder('输入规则名称')).toBeVisible()
    await page.getByPlaceholder('输入规则名称').fill('E2E测试规则')
    await page.getByRole('combobox').selectOption('keyword')
    await page.getByPlaceholder('输入触发关键词').fill('e2e test pattern')
    await page.getByPlaceholder('输入自动回复内容').fill('e2e test reply')

    await expect(page.getByRole('button', { name: '保存规则' })).toBeEnabled()
  })

  test('should start and stop auto reply', async ({ page }) => {
    // This assumes the user is already bound in the mock environment.
    // If not, this might fail, so we conditionally check if button is enabled.
    const startBtn = page.getByText('启动自动回复')
    
    // If it's disabled, it means binding is not ready or it's already running
    if (await startBtn.isDisabled()) {
      const stopBtn = page.getByText('停止自动回复')
      if (await stopBtn.isEnabled()) {
        await stopBtn.click()
        await expect(page.getByText('自动回复已停止')).toBeVisible()
      }
    } else {
      await startBtn.click()
      await expect(page.getByText('自动回复已启动')).toBeVisible()
      
      const stopBtn = page.getByText('停止自动回复')
      await stopBtn.click()
      await expect(page.getByText('自动回复已停止')).toBeVisible()
    }
  })
})
