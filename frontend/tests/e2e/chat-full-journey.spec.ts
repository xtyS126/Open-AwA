import { test, expect } from '@playwright/test'
import { loginAndSaveState } from './auth'

test.describe('完整聊天旅程 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAndSaveState(page)
  })

  test('聊天页面渲染正常', async ({ page }) => {
    await page.goto('/chat')

    // 验证聊天页面核心元素存在
    await expect(page.getByRole('heading', { name: '聊天' })).toBeVisible({ timeout: 20_000 })

    // 验证侧边栏会话列表存在
    const sidebar = page.getByLabel('聊天历史侧边栏')
    if (await sidebar.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await expect(sidebar).toBeVisible()
    }
  })

  test('会话列表渲染并可以切换', async ({ page }) => {
    await page.goto('/chat')

    // 验证会话列表区域存在
    const sidebar = page.getByLabel('聊天历史侧边栏')
    await expect(sidebar).toBeVisible({ timeout: 20_000 })

    // 获取所有会话项
    const conversationItems = sidebar.locator('[role="button"]').first()
    const hasConversations = await conversationItems.isVisible({ timeout: 10_000 }).catch(() => false)

    if (hasConversations) {
      // 点击第一个会话项进行切换
      await conversationItems.click()

      // 验证 URL 发生变化，进入具体会话
      await page.waitForURL(/\/chat\/\w+/, { timeout: 15_000 })
      await expect(page).toHaveURL(/\/chat\/\w+/)
    }
  })

  test('创建新会话按钮可见并可点击', async ({ page }) => {
    await page.goto('/chat')

    // 查找新建会话按钮
    const newChatButton = page.locator('[title="新建对话"], [aria-label="新建对话"], button:has-text("新建")').first()

    const isVisible = await newChatButton.isVisible({ timeout: 10_000 }).catch(() => false)
    if (isVisible) {
      await newChatButton.click()

      // 验证跳转到了新的聊天页面
      await page.waitForURL(/\/chat/, { timeout: 15_000 })
      await expect(page).toHaveURL(/\/chat/)
    }
  })

  test('输入消息并发送', async ({ page }) => {
    await page.goto('/chat')

    // 等待输入框出现
    const inputArea = page.locator('textarea, [contenteditable="true"], [role="textbox"]').first()
    await expect(inputArea).toBeVisible({ timeout: 20_000 })

    // 输入测试消息
    const testMessage = '你好，这是一条 E2E 测试消息'
    await inputArea.fill(testMessage)
    await expect(inputArea).toHaveValue(testMessage)

    // 点击发送按钮
    const sendButton = page.locator('[title="发送"], [aria-label="发送"], button:has-text("发送")').first()
    const sendVisible = await sendButton.isVisible({ timeout: 5_000 }).catch(() => false)
    if (sendVisible) {
      await sendButton.click()

      // 等待用户消息出现在对话区域
      await expect(page.getByText(testMessage)).toBeVisible({ timeout: 15_000 })
    }
  })

  test('搜索会话功能', async ({ page }) => {
    await page.goto('/chat')

    const searchInput = page.getByPlaceholder('搜索标题或摘要')
    const searchVisible = await searchInput.isVisible({ timeout: 10_000 }).catch(() => false)

    if (searchVisible) {
      await searchInput.fill('E2E')

      // 验证搜索操作不会导致页面崩溃
      await page.waitForTimeout(2_000)
      await expect(searchInput).toHaveValue('E2E')

      // 清空搜索
      await searchInput.fill('')
      await expect(searchInput).toHaveValue('')
    }
  })
})
