/**
 * E2E 认证流程测试 — 登录/登出关键路径。
 * 单用户模式下登录页使用 API Key 校验（单个 #apiKey 输入框 + "连接" 按钮）。
 */
import { test, expect } from '@playwright/test'
import { getApiKey } from './utils/auth'

test.describe('Login Page', () => {
  test('displays login form with required elements', async ({ page }) => {
    await page.goto('/login')
    // 等待 API Key 输入框加载完成
    await expect(page.locator('#apiKey')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('button[type="submit"]')).toBeVisible()
  })

  test('shows error on invalid credentials', async ({ page }) => {
    await page.goto('/login')
    // 填入长度不足的 API Key 触发前端 zod 校验，无需调用后端
    await page.fill('#apiKey', 'invalid-short-key')
    await page.click('button[type="submit"]')
    // 应显示错误信息（[role="alert"] 由 LoginPage 渲染）
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
    const apiKey = getApiKey()
    await page.goto('/login')
    await page.fill('#apiKey', apiKey)
    await page.click('button[type="submit"]')
    // 登录成功应重定向到聊天页面
    await expect(page).toHaveURL(/\/chat/, { timeout: 15000 })
  })
})
