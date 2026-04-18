import { expect, type APIRequestContext, type Page } from '@playwright/test'

const backendApiBase = 'http://127.0.0.1:8000/api'

export const E2E_ADMIN_USERNAME = 'admin'
export const E2E_ADMIN_PASSWORD = 'openawa-e2e-admin'

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
  expect(csrfToken).toBeTruthy()

  return {
    token,
    csrfToken: csrfToken!,
    cookies: storageState.cookies,
  }
}

export async function loginAsAdminPage(page: Page, loginUrl = '/login') {
  await page.goto(loginUrl)
  await expect(page.getByRole('button', { name: '登录' })).toBeVisible({ timeout: 30_000 })
  await page.locator('#username').fill(E2E_ADMIN_USERNAME)
  await page.locator('#password').fill(E2E_ADMIN_PASSWORD)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL(/\/chat/, { timeout: 30_000 })
}