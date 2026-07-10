/**
 * E2E 测试共享工具 — 登录与凭据管理。
 */
import { type Page, expect } from '@playwright/test'

/**
 * 从环境变量或默认值获取测试 API Key。
 * 默认值与 playwright.config.ts 中后端 OPENAWA_API_KEY 保持一致，
 * 单用户模式下登录页使用 API Key 校验（调用 /auth/me）。
 */
export function getApiKey(): string {
  return (
    process.env.OPENAWA_API_KEY ||
    process.env.OPENAWA_E2E_API_KEY ||
    'openawa-e2e-api-key-at-least-32-characters'
  )
}

/**
 * 从环境变量获取管理员密码，未设置时抛出明确错误。
 * 不允许硬编码后备值以避免凭据泄露到源代码中。
 * @deprecated 单用户模式改用 API Key 登录，请使用 getApiKey()
 */
export function getAdminPassword(): string {
  const password = process.env.OPENAWA_ADMIN_PASSWORD
  if (!password) {
    throw new Error(
      'OPENAWA_ADMIN_PASSWORD 环境变量未设置。请在运行 E2E 测试前设置该变量。'
    )
  }
  return password
}

/**
 * 以管理员身份通过 API Key 登录并等待重定向到聊天页面。
 * 作为测试中 beforeEach 钩子的共享登录步骤。
 * 单用户模式下登录页只有单个 API Key 输入框（#apiKey），提交后路由守卫跳转到 /chat。
 */
export async function loginAsAdmin(page: Page): Promise<void> {
  const apiKey = getApiKey()
  await page.goto('/login')
  await page.fill('#apiKey', apiKey)
  await page.click('button[type="submit"]')
  await expect(page).toHaveURL(/\/chat/, { timeout: 15000 })
}
