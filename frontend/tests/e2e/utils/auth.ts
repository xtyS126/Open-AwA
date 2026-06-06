/**
 * E2E 测试共享工具 — 登录与凭据管理。
 */
import { type Page, expect } from '@playwright/test'

/**
 * 从环境变量获取管理员密码，未设置时抛出明确错误。
 * 不允许硬编码后备值以避免凭据泄露到源代码中。
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
 * 以管理员身份登录并等待重定向到聊天页面。
 * 作为测试中 beforeEach 钩子的共享登录步骤。
 */
export async function loginAsAdmin(page: Page): Promise<void> {
  const password = getAdminPassword()
  await page.goto('/login')
  await page.fill('input[name="username"]', 'admin')
  await page.fill('input[type="password"]', password)
  await page.click('button[type="submit"]')
  await expect(page).toHaveURL(/\/chat/, { timeout: 15000 })
}
