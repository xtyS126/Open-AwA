import { expect, test } from '@playwright/test'
import { loginAsAdminPage } from './auth'

test.describe('记忆与经验 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdminPage(page)
  })

  test('全新用户的记忆页面展示确定性空状态', async ({ page }) => {
    await page.goto('/memory')

    await expect(page.getByRole('heading', { name: '记忆管理' })).toBeVisible()
    await expect(page.getByRole('heading', { name: '记忆条目' })).toBeVisible()
    await expect(page.getByText('暂无记忆数据')).toBeVisible()
    await expect(page.getByPlaceholder('搜索记忆内容...')).toBeVisible()
  })

  test('全新用户的经验页面展示确定性空状态', async ({ page }) => {
    await page.goto('/experience')

    await expect(page.getByRole('button', { name: '刷新列表' })).toBeVisible()
    await expect(page.getByText('当前没有可用经验文件，请先通过提取流程生成 Markdown 文件。')).toBeVisible()
  })

  test('侧边栏可以导航到记忆页面', async ({ page }) => {
    await page.goto('/chat')

    await page.getByRole('link', { name: /记忆|Memory/ }).click()

    await expect(page).toHaveURL(/\/memory$/)
    await expect(page.getByRole('heading', { name: '记忆管理' })).toBeVisible()
  })

  test('侧边栏可以导航到经验页面', async ({ page }) => {
    await page.goto('/chat')

    await page.getByRole('link', { name: /经验|Experience/ }).click()

    await expect(page).toHaveURL(/\/experience$/)
    await expect(page.getByText('当前没有可用经验文件，请先通过提取流程生成 Markdown 文件。')).toBeVisible()
  })
})
