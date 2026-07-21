import { test, expect } from '@playwright/test'
import { E2E_API_KEY, loginAsAdminPage } from './auth'

test.describe('认证流程 E2E', () => {
  test('登录页面渲染正常', async ({ page }) => {
    await page.goto('/login')

    const apiKeyInput = page.getByLabel('访问密钥')
    await expect(apiKeyInput).toBeVisible({ timeout: 20_000 })
    await expect(apiKeyInput).toHaveAttribute('type', 'password')
    await expect(page.getByRole('button', { name: '连接' })).toBeVisible()
  })

  test('未认证访问受保护页面会跳转到登录页', async ({ page }) => {
    await page.goto('/chat')

    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByLabel('访问密钥')).toBeVisible()
  })

  test('输入有效 API Key 点击连接后跳转到聊天页面', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByLabel('访问密钥')).toBeVisible({ timeout: 20_000 })

    await page.getByLabel('访问密钥').fill(E2E_API_KEY)
    await page.getByRole('button', { name: '连接' }).click()

    await expect(page).toHaveURL(/\/chat(?:\/|$)/, { timeout: 30_000 })
  })

  test('输入错误 API Key 显示错误提示', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByLabel('访问密钥')).toBeVisible({ timeout: 20_000 })

    // 使用满足前端长度要求的错误密钥，确保请求真正到达后端认证层。
    await page.getByLabel('访问密钥').fill('invalid-e2e-api-key-at-least-32-characters')
    await page.getByRole('button', { name: '连接' }).click()

    await expect(page.getByRole('alert')).toHaveText('认证失败')
    await expect(page).toHaveURL(/\/login$/)
  })

  test('已登录用户访问登录页自动跳转到聊天页', async ({ page }) => {
    await loginAsAdminPage(page)
    await page.goto('/login')

    await expect(page).toHaveURL(/\/chat(?:\/|$)/, { timeout: 20_000 })
  })

  test('登出后回到登录页', async ({ page }) => {
    await loginAsAdminPage(page)

    const logoutButton = page.getByTitle('退出登录')
    await expect(logoutButton).toBeVisible()
    await logoutButton.click()

    await expect(page).toHaveURL(/\/login$/, { timeout: 15_000 })
    await expect(page.getByLabel('访问密钥')).toBeVisible()
  })
})
