import { test, expect } from '@playwright/test'
import { _electron as electron } from 'playwright'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { E2E_API_KEY } from './auth'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(__dirname, '..', '..')
const frontendPort = process.env.OPENAWA_E2E_FRONTEND_PORT || '15173'
const frontendBaseUrl = `http://127.0.0.1:${frontendPort}`

test('electron 冒烟：可启动并打开插件页', async () => {
  // 复刻项目其他 spec 的登录方式：在 electron 窗口内走 /login 表单输入 API Key 连接。
  // 历史"API 登录拿 cookies 后 addCookies 注入"方案无法让前端 zustand useAuthStore
  // 建立已登录态，SPA 启动路由 guard 会把未登录访客从 /plugins/manage 弹回 /login，
  // 导致 heading 20s 不可见。改走表单登录后 axios 拉到 access_token、store 认认证态。
  const electronApp = await electron.launch({
    args: [path.join(__dirname, 'electron-main.cjs')],
    cwd: frontendRoot,
    env: {
      ...process.env,
      FRONTEND_URL: `${frontendBaseUrl}/login`,
    },
  })

  try {
    const firstWindow = await electronApp.firstWindow()
    // 表单登录建立认证态（与 loginAsAdminPage 同路径的 electron 版本）
    const apiKeyInput = firstWindow.getByLabel('访问密钥')
    await expect(apiKeyInput).toBeVisible({ timeout: 30_000 })
    await apiKeyInput.fill(E2E_API_KEY)
    await firstWindow.getByRole('button', { name: '连接' }).click()
    // 登录成功后路由跳到 /chat, 以此作为认证态生效的信号
    await expect(firstWindow).toHaveURL(/\/chat(?:\/|$)/, { timeout: 30_000 })

    // 进入插件管理页, 验证页头渲染
    await firstWindow.goto(`${frontendBaseUrl}/plugins/manage`)
    await expect(firstWindow).toHaveURL(/\/plugins\/manage/, { timeout: 30_000 })
    await expect(firstWindow.getByRole('heading', { name: '插件管理' })).toBeVisible({ timeout: 20_000 })
  } finally {
    await electronApp.close()
  }
})
