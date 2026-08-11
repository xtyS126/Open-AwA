import { expect, type APIRequestContext, type Page } from '@playwright/test'

const backendPort = process.env.OPENAWA_E2E_BACKEND_PORT || '18000'
const backendApiBase = `http://127.0.0.1:${backendPort}/api`

export const E2E_ADMIN_USERNAME = 'admin'
export const E2E_ADMIN_PASSWORD = process.env.OPENAWA_ADMIN_PASSWORD || process.env.E2E_ADMIN_PASSWORD || 'OpenAwAE2e1'

// E2E 测试 API Key：默认值与 playwright.config.ts 中后端 OPENAWA_API_KEY 保持一致
// 单用户模式下登录页使用 API Key 校验（调用 /auth/me），不再使用用户名/密码
export const E2E_API_KEY = process.env.OPENAWA_API_KEY || process.env.OPENAWA_E2E_API_KEY || 'openawa-e2e-api-key-at-least-32-characters'

export function getApiKey(): string {
  return E2E_API_KEY
}

export async function loginAsAdminApi(request: APIRequestContext) {
  const loginResponse = await request.post(`${backendApiBase}/auth/login`, {
    form: {
      username: E2E_ADMIN_USERNAME,
      password: E2E_ADMIN_PASSWORD,
    },
  })
  expect(loginResponse.ok()).toBeTruthy()

  const loginJson = await loginResponse.json()
  const token = loginJson.access_token
  const csrfToken = loginJson.csrf_token
  expect(token).toBeTruthy()
  expect(csrfToken).toBeTruthy()

  const storageState = await request.storageState()

  return {
    token,
    csrfToken: csrfToken as string,
    cookies: storageState.cookies,
  }
}

export async function loginAsAdminPage(page: Page, loginUrl = '/login') {
  await page.goto(loginUrl)
  const apiKeyInput = page.getByLabel('访问密钥')
  await expect(apiKeyInput).toBeVisible({ timeout: 30_000 })
  await apiKeyInput.fill(E2E_API_KEY)
  await page.getByRole('button', { name: '连接' }).click()
  await expect(page).toHaveURL(/\/assistant(?:\/|$)/, { timeout: 30_000 })
  await expect(page.getByTestId('chat-input-container')).toBeVisible({ timeout: 30_000 })
}

export async function loginAndSaveState(page: Page, loginUrl = '/login') {
  await loginAsAdminPage(page, loginUrl)
}

export const loginAsAdmin = loginAsAdminPage
