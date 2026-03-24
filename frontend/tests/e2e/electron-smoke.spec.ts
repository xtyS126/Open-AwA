import { test, expect } from '@playwright/test'
import { _electron as electron } from 'playwright'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(__dirname, '..', '..')

test('electron 冒烟：可启动并打开插件页', async () => {
  const electronApp = await electron.launch({
    args: [path.join(__dirname, 'electron-main.cjs')],
    cwd: frontendRoot,
    env: {
      ...process.env,
      FRONTEND_URL: 'http://127.0.0.1:5173/plugins',
    },
  })

  try {
    const firstWindow = await electronApp.firstWindow()
    await firstWindow.waitForURL(/\/plugins/, { timeout: 30_000 })
    await expect(firstWindow.getByText('插件管理')).toBeVisible({ timeout: 20_000 })
  } finally {
    await electronApp.close()
  }
})

