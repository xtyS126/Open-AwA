import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from '@playwright/test'

const backendApiBase = 'http://127.0.0.1:8000/api'
const currentFilePath = fileURLToPath(import.meta.url)
const currentDirPath = path.dirname(currentFilePath)
const backendDbPath = path.resolve(currentDirPath, '../../../backend/openawa_e2e.db')

function promoteUserToAdmin(username: string) {
  execFileSync(process.env.PYTHON ?? 'python', [
    '-c',
    [
      'import sqlite3, sys',
      'conn = sqlite3.connect(sys.argv[1])',
      'conn.execute("UPDATE users SET role = ? WHERE username = ?", ("admin", sys.argv[2]))',
      'conn.commit()',
      'row = conn.execute("SELECT role FROM users WHERE username = ?", (sys.argv[2],)).fetchone()',
      'conn.close()',
      'assert row and row[0] == "admin", "failed to promote user to admin"',
    ].join('; '),
    backendDbPath,
    username,
  ])
}

test('插件页冒烟可打开', async ({ page }) => {
  await page.goto('/plugins')
  await expect(page.getByText('插件管理')).toBeVisible({ timeout: 20000 })
  await expect(page.getByRole('button', { name: '导入插件' }).first()).toBeVisible()
})

test('热更新流程冒烟', async ({ request }) => {
  const suffix = `${Date.now()}_${Math.floor(Math.random() * 100000)}`
  const username = `e2e_${suffix}`
  const password = 'e2e_password_123'

  await request.post(`${backendApiBase}/auth/register`, {
    data: { username, password },
  })

  promoteUserToAdmin(username)

  const loginResponse = await request.post(`${backendApiBase}/auth/login`, {
    form: { username, password },
  })
  expect(loginResponse.ok()).toBeTruthy()
  const loginJson = await loginResponse.json()
  const token = loginJson.access_token
  expect(token).toBeTruthy()

  const authHeaders = {
    Authorization: `Bearer ${token}`,
  }

  const pluginsResponse = await request.get(`${backendApiBase}/plugins`, {
    headers: authHeaders,
  })
  expect(pluginsResponse.ok()).toBeTruthy()
  const plugins = await pluginsResponse.json()
  const storageState = await request.storageState()
  const csrfToken = storageState.cookies.find((cookie) => cookie.name === 'csrf_token')?.value
  expect(csrfToken).toBeTruthy()

  const mutatingHeaders = {
    ...authHeaders,
    'X-CSRF-Token': csrfToken!,
  }

  if (Array.isArray(plugins) && plugins.length > 0) {
    const targetPluginId = plugins[0].id as string
    const hotUpdateResponse = await request.post(`${backendApiBase}/plugins/${targetPluginId}/hot-update`, {
      headers: mutatingHeaders,
      data: {
        strategy: 'gray',
        rollout_config: {
          enabled: false,
          strategy: 'percentage',
          percentage: 0,
        },
      },
    })
    expect(hotUpdateResponse.ok()).toBeTruthy()

    const rollbackResponse = await request.post(`${backendApiBase}/plugins/${targetPluginId}/rollback`, {
      headers: mutatingHeaders,
      data: {},
    })
    expect(rollbackResponse.ok()).toBeTruthy()
  } else {
    const notFoundResponse = await request.post(`${backendApiBase}/plugins/nonexistent-plugin-id/hot-update`, {
      headers: mutatingHeaders,
      data: {
        strategy: 'gray',
      },
    })
    expect(notFoundResponse.status()).toBe(404)
  }
})
