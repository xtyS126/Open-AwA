import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { getApiKey, loginAsAdminPage } from './auth'

const backendApiBase = `http://127.0.0.1:${process.env.OPENAWA_E2E_BACKEND_PORT || '18000'}/api`

interface SessionSeed {
  sessionId: string
  title: string
}

async function createConversationSession(request: APIRequestContext, title: string): Promise<SessionSeed> {
  const response = await request.post(`${backendApiBase}/conversations`, {
    headers: {
      Authorization: `Bearer ${getApiKey()}`,
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
  const response = await request.post(`${backendApiBase}/memory/short-term`, {
    headers: {
      Authorization: `Bearer ${getApiKey()}`,
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

  await conversationItem.hover()
  await conversationItem.getByTitle(/重命名|Rename/).click()
  await page.getByLabel(/^(重命名对话标题|Rename conversation)$/).fill(renamedTitle)
  await page.getByRole('button', { name: /^(保存|Save)$/ }).click()

  await expect(getConversationItem(page, renamedTitle)).toBeVisible({ timeout: 20_000 })

  await page.reload()
  await expect(getConversationItem(page, renamedTitle)).toBeVisible({ timeout: 20_000 })

  await page.getByLabel('聊天历史侧边栏').getByRole('textbox').first().fill(renamedTitle)
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

  const conversationItem = getConversationItem(page, title)
  await conversationItem.hover()
  await conversationItem.getByTitle(/删除|Delete/).click()
  const deleteDialog = page.getByRole('alertdialog', { name: '删除会话' })
  await expect(deleteDialog).toBeVisible()
  await deleteDialog.getByRole('button', { name: '删除', exact: true }).click()

  await expect(getConversationItem(page, title)).toHaveCount(0)

  await page.getByLabel(/^(显示最近删除|Show recently deleted)$/).check()
  const deletedConversationItem = getConversationItem(page, title)
  await expect(deletedConversationItem).toBeVisible({ timeout: 20_000 })
  await expect(deletedConversationItem).toContainText(/已删除，可恢复|Deleted, recoverable/)

  await deletedConversationItem.getByTitle(/恢复|Restore/).click()
  await expect(deletedConversationItem.getByText(/^(已删除，可恢复|Deleted, recoverable)$/)).toHaveCount(0)

  await deletedConversationItem.click()
  await expect(page.getByText(userMessage)).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(assistantMessage)).toBeVisible({ timeout: 20_000 })
})
