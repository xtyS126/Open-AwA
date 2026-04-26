import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { loginAsAdminApi, loginAsAdminPage } from './auth'

const backendApiBase = `http://127.0.0.1:${process.env.OPENAWA_E2E_BACKEND_PORT || '18000'}/api`

interface SessionSeed {
  sessionId: string
  title: string
}

async function createConversationSession(request: APIRequestContext, title: string): Promise<SessionSeed> {
  const { token, csrfToken } = await loginAsAdminApi(request)
  const response = await request.post(`${backendApiBase}/conversations`, {
    headers: {
      Authorization: `Bearer ${token}`,
      ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
    },
    data: { title },
  })

  expect(response.ok()).toBeTruthy()
  const session = await response.json()

  return {
    sessionId: session.session_id as string,
    title: session.title as string,
  }
}

async function addShortTermMessage(
  request: APIRequestContext,
  sessionId: string,
  role: 'user' | 'assistant',
  content: string,
) {
  const { token, csrfToken } = await loginAsAdminApi(request)
  const response = await request.post(`${backendApiBase}/memory/short-term`, {
    headers: {
      Authorization: `Bearer ${token}`,
      ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
    },
    data: {
      session_id: sessionId,
      role,
      content,
    },
  })

  expect(response.ok()).toBeTruthy()
}

function getConversationItem(page: Page, title: string) {
  return page.getByLabel('聊天历史侧边栏').locator('[role="button"]').filter({ hasText: title }).first()
}

test('会话可重命名、搜索，并在刷新后保留', async ({ page, request }) => {
  const title = `E2E 会话 ${randomUUID().slice(0, 8)}`
  const renamedTitle = `${title} 已重命名`
  const session = await createConversationSession(request, title)

  await loginAsAdminPage(page)
  await page.goto(`/chat/${session.sessionId}`)

  const conversationItem = getConversationItem(page, title)
  await expect(conversationItem).toBeVisible({ timeout: 20_000 })

  await conversationItem.getByTitle('重命名对话').click()
  await page.getByLabel('重命名对话标题').fill(renamedTitle)
  await page.getByRole('button', { name: '保存', exact: true }).click()

  await expect(getConversationItem(page, renamedTitle)).toBeVisible({ timeout: 20_000 })

  await page.reload()
  await expect(getConversationItem(page, renamedTitle)).toBeVisible({ timeout: 20_000 })

  await page.getByPlaceholder('搜索标题或摘要').fill(renamedTitle)
  await expect(getConversationItem(page, renamedTitle)).toBeVisible({ timeout: 20_000 })
})

test('历史消息可在刷新后恢复，并支持删除后恢复会话', async ({ page, request }) => {
  const title = `E2E 历史 ${randomUUID().slice(0, 8)}`
  const userMessage = `用户消息 ${randomUUID().slice(0, 8)}`
  const assistantMessage = `助手回复 ${randomUUID().slice(0, 8)}`
  const session = await createConversationSession(request, title)

  await addShortTermMessage(request, session.sessionId, 'user', userMessage)
  await addShortTermMessage(request, session.sessionId, 'assistant', assistantMessage)

  await loginAsAdminPage(page)
  await page.goto(`/chat/${session.sessionId}`)

  await expect(page.getByText(userMessage)).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(assistantMessage)).toBeVisible({ timeout: 20_000 })

  await page.reload()

  await expect(page.getByText(userMessage)).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(assistantMessage)).toBeVisible({ timeout: 20_000 })

  page.once('dialog', (dialog) => dialog.accept())
  await getConversationItem(page, title).getByTitle('删除对话').click()

  await expect(getConversationItem(page, title)).toHaveCount(0)

  await page.getByLabel('显示最近删除').check()
  const deletedConversationItem = getConversationItem(page, title)
  await expect(deletedConversationItem).toBeVisible({ timeout: 20_000 })
  await expect(deletedConversationItem).toContainText('已删除，可恢复')

  await deletedConversationItem.getByTitle('恢复对话').click()
  await expect(deletedConversationItem.getByText('已删除，可恢复')).toHaveCount(0)

  await deletedConversationItem.click()
  await expect(page.getByText(userMessage)).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(assistantMessage)).toBeVisible({ timeout: 20_000 })
})