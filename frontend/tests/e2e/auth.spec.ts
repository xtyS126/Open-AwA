/**
 * E2E 认证流程测试 — 登录/登出关键路径。
 */
import { test, expect } from '@playwright/test'
import { getAdminPassword, loginAsAdmin } from './utils/auth'

test.describe('Login Page', () => {
  test('displays login form with required elements', async ({ page }) => {
    await page.goto('/login')
    // 等待登录表单加载完成
    await expect(page.locator('input[name="username"]')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('input[type="password"]')).toBeVisible()
    await expect(page.locator('button[type="submit"]')).toBeVisible()
  })

  test('shows error on invalid credentials', async ({ page }) => {
    await page.goto('/login')
    await page.fill('input[name="username"]', 'nonexistent_user')
    await page.fill('input[type="password"]', 'wrong_password')
    await page.click('button[type="submit"]')
    // 应显示错误信息 — 优先匹配 ARIA role，再回退到通用错误类
    await expect(page.locator('[role="alert"]')).toBeVisible({ timeout: 10000 })
  })

  test('redirects to login for unauthenticated access', async ({ page }) => {
    // 直接访问受保护页面应重定向到登录页
    await page.goto('/chat')
    await expect(page).toHaveURL(/\/login/)
  })
})

test.describe('Login Success', () => {
  test('logs in and redirects to chat page', async ({ page }) => {
    const password = getAdminPassword()
    await page.goto('/login')
    await page.fill('input[name="username"]', 'admin')
    await page.fill('input[type="password"]', password)
    await page.click('button[type="submit"]')
    // 登录成功应重定向到聊天页面
    await expect(page).toHaveURL(/\/chat/, { timeout: 15000 })
  })
})
