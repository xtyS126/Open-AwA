import { test, expect } from '@playwright/test'
import { _electron as electron } from 'playwright'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { loginAsAdminApi } from './auth'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(__dirname, '..', '..')
const frontendBaseUrl = 'http://127.0.0.1:5173'

test('electron 冒烟：可启动并打开插件页', async ({ request }) => {
  const { cookies } = await loginAsAdminApi(request)

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
    await firstWindow.context().addCookies(cookies)
    await firstWindow.goto(`${frontendBaseUrl}/plugins/manage`)
    await firstWindow.waitForURL(/\/plugins\/manage/, { timeout: 30_000 })
    await expect(firstWindow.getByRole('heading', { name: '插件管理' })).toBeVisible({ timeout: 20_000 })
  } finally {
    await electronApp.close()
  }
})

