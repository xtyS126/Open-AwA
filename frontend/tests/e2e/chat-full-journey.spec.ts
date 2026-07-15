import { expect, test } from '@playwright/test'
import { loginAsAdminPage } from './auth'

const messagePlaceholder = 'type your question... (try /diary for daily diary)'

test.describe('完整聊天旅程 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdminPage(page)
  })

  test('聊天页面呈现导航、历史和输入区', async ({ page }) => {
    await page.goto('/chat')

    await expect(page.getByRole('heading', { name: 'AI 助手' })).toBeVisible()
    await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible()
    await expect(page.getByRole('complementary', { name: '聊天历史侧边栏' })).toBeVisible()
    await expect(page.getByPlaceholder(messagePlaceholder)).toBeVisible()
  })

  test('历史侧边栏提供创建、搜索和排序控制', async ({ page }) => {
    await page.goto('/chat')

    const sidebar = page.getByRole('complementary', { name: '聊天历史侧边栏' })
    await expect(sidebar.getByRole('button', { name: '新建对话' })).toBeVisible()
    const searchInput = sidebar.getByPlaceholder('搜索标题或摘要')
    await expect(searchInput).toBeVisible()
    await expect(sidebar.getByRole('combobox')).toBeVisible()

    await searchInput.fill('E2E')
    await expect(searchInput).toHaveValue('E2E')
    await searchInput.fill('')
    await expect(searchInput).toHaveValue('')
  })

  test('新对话操作保持可交互的聊天状态', async ({ page }) => {
    await page.goto('/chat')

    await page.getByRole('button', { name: '新对话', exact: true }).click()

    await expect(page).toHaveURL(/\/chat(?:\/[^/]+)?$/)
    await expect(page.getByPlaceholder(messagePlaceholder)).toBeVisible()
  })

  test('发送消息后用户消息立即出现在对话流', async ({ page }) => {
    await page.goto('/chat')

    const input = page.getByPlaceholder(messagePlaceholder)
    const message = 'E2E user message must be visible'
    await expect(input).toBeEditable()
    await input.fill(message)
    await expect(page.getByRole('button', { name: '发送' })).toBeEnabled()
    await page.getByRole('button', { name: '发送' }).click()

    await expect(
      page.getByRole('log', { name: '消息列表' }).getByText(message, { exact: true }),
    ).toBeVisible()
  })
})
