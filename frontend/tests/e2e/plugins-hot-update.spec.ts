import { test, expect } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

const backendApiBase = 'http://127.0.0.1:8000/api'
const pluginDir = path.resolve(process.cwd(), '../backend/plugins/plugins')

test('插件页冒烟可打开', async ({ page }) => {
  await page.goto('/plugins')
  await expect(page.getByText('插件管理')).toBeVisible({ timeout: 20000 })
  await expect(page.getByRole('button', { name: '导入插件' }).first()).toBeVisible()
})

test('热更新流程冒烟', async ({ request }) => {
  const suffix = `${Date.now()}_${Math.floor(Math.random() * 100000)}`
  const username = `e2e_${suffix}`
  const password = 'e2e_password_123'
  const pluginName = `e2e_hot_${suffix}`
  const pluginFilePath = path.join(pluginDir, `${pluginName}.py`)

  await fs.mkdir(pluginDir, { recursive: true })
  await fs.writeFile(
    pluginFilePath,
    `from plugins.base_plugin import BasePlugin\n\n\nclass E2EHotPlugin(BasePlugin):\n    name = \"${pluginName}\"\n    version = \"1.0.0\"\n    description = \"e2e hot update plugin\"\n\n    def initialize(self):\n        return True\n\n    def execute(self, **kwargs):\n        return kwargs\n`,
    'utf-8'
  )

  let pluginId = ''
  let token = ''

  try {
    await request.post(`${backendApiBase}/auth/register`, {
      data: { username, password },
    })

    const loginResponse = await request.post(`${backendApiBase}/auth/login`, {
      form: { username, password },
    })
    expect(loginResponse.ok()).toBeTruthy()
    const loginJson = await loginResponse.json()
    token = loginJson.access_token
    expect(token).toBeTruthy()

    const authHeaders = {
      Authorization: `Bearer ${token}`,
    }

    const installResponse = await request.post(`${backendApiBase}/plugins`, {
      headers: authHeaders,
      data: {
        name: pluginName,
        version: '1.0.0',
        config: '{}',
      },
    })
    expect(installResponse.ok()).toBeTruthy()
    const installJson = await installResponse.json()
    pluginId = installJson.id
    expect(pluginId).toBeTruthy()

    const hotUpdateResponse = await request.post(`${backendApiBase}/plugins/${pluginId}/hot-update`, {
      headers: authHeaders,
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
    const hotUpdateJson = await hotUpdateResponse.json()
    expect(hotUpdateJson.success).toBeTruthy()
    expect(hotUpdateJson.plugin_name).toBe(pluginName)

    const rollbackResponse = await request.post(`${backendApiBase}/plugins/${pluginId}/rollback`, {
      headers: authHeaders,
      data: {},
    })
    expect(rollbackResponse.ok()).toBeTruthy()
    const rollbackJson = await rollbackResponse.json()
    expect(rollbackJson.success).toBeTruthy()
  } finally {
    if (token && pluginId) {
      await request.delete(`${backendApiBase}/plugins/${pluginId}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      })
    }

    await fs.rm(pluginFilePath, { force: true })
  }
})
