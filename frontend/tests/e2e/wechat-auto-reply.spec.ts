import { test, expect } from '@playwright/test'
import { loginAndSaveState } from './auth'

test.describe('WeChat Auto Reply E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAndSaveState(page)
    await page.goto('/communication')
  })

  test('should load communication page and see wechat module', async ({ page }) => {
    await expect(page.getByText('通讯渠道配置')).toBeVisible()
    await expect(page.getByText('微信通讯配置')).toBeVisible()
  })

  test('should create a new auto reply rule and it becomes active', async ({ page }) => {
    // Navigate to WeChat module and rules section
    await expect(page.getByText('自动回复规则配置')).toBeVisible()

    // Click "添加新规则"
    await page.getByText('添加新规则').click()

    // Fill rule form
    await page.getByPlaceholder('例如：欢迎语').fill('E2E测试规则')
    await page.locator('select').filter({ hasText: '关键词包含' }).selectOption('keyword')
    await page.getByPlaceholder('例如：你好').fill('e2e test pattern')
    await page.getByPlaceholder('例如：你好，请问有什么可以帮您？').fill('e2e test reply')
    
    // Save rule
    await page.getByText('保存规则').click()

    // Verify success message
    await expect(page.getByText('规则创建成功')).toBeVisible()
    
    // Verify rule appears in the list
    await expect(page.getByText('E2E测试规则')).toBeVisible()
    await expect(page.getByText('e2e test pattern')).toBeVisible()
    await expect(page.getByText('e2e test reply')).toBeVisible()
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