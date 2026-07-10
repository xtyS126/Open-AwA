import { expect, type APIRequestContext, type Page } from '@playwright/test'

const backendPort = process.env.OPENAWA_E2E_BACKEND_PORT || '18000'
const backendApiBase = `http://127.0.0.1:${backendPort}/api`

export const E2E_ADMIN_USERNAME = 'admin'
export const E2E_ADMIN_PASSWORD = process.env.OPENAWA_ADMIN_PASSWORD || process.env.E2E_ADMIN_PASSWORD || 'openawa-e2e-admin'

// E2E 测试 API Key：默认值与 playwright.config.ts 中后端 OPENAWA_API_KEY 保持一致
// 单用户模式下登录页使用 API Key 校验（调用 /auth/me），不再使用用户名/密码
export const E2E_API_KEY = process.env.OPENAWA_API_KEY || process.env.OPENAWA_E2E_API_KEY || 'openawa-e2e-api-key-at-least-32-characters'

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
  expect(token).toBeTruthy()

  const storageState = await request.storageState()
  const csrfToken = storageState.cookies.find((cookie) => cookie.name === 'csrf_token')?.value

  return {
    token,
    csrfToken: csrfToken ?? null,
    cookies: storageState.cookies,
  }
}

export async function loginAsAdminPage(page: Page, loginUrl = '/login') {
  await page.goto(loginUrl)
  // 等待 API Key 输入框可见（页面加载完成标志）
  await expect(page.locator('#apiKey')).toBeVisible({ timeout: 30_000 })
  await page.locator('#apiKey').fill(E2E_API_KEY)
  // 登录页提交按钮文案为"连接"（加载中变为"验证中..."）
  await page.getByRole('button', { name: '连接' }).click()
  // 校验通过后前端路由守卫自动跳转到 /chat
  await page.waitForURL(/\/chat/, { timeout: 30_000 })
}

export async function loginAndSaveState(page: Page, loginUrl = '/login') {
  await loginAsAdminPage(page, loginUrl)
}
