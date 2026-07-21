import { test, expect } from '@playwright/test'
import { loginAsAdminApi, loginAsAdminPage } from './auth'

const backendApiBase = `http://127.0.0.1:${process.env.OPENAWA_E2E_BACKEND_PORT || '18000'}/api`

test('插件页冒烟可打开', async ({ page }) => {
  await loginAsAdminPage(page)
  await page.goto('/plugins/manage')
  await expect(page.getByRole('heading', { name: '插件管理' })).toBeVisible({ timeout: 20000 })
  await expect(page.getByRole('button', { name: '刷新' })).toBeVisible()
  await expect(page.getByPlaceholder('搜索插件名称 / 版本 / 作者 / 简介')).toBeVisible()
})

test('热更新流程冒烟', async ({ request }) => {
  const { token, csrfToken } = await loginAsAdminApi(request)

  const authHeaders = {
    Authorization: `Bearer ${token}`,
  }

  const pluginsResponse = await request.get(`${backendApiBase}/plugins`, {
    headers: authHeaders,
  })
  expect(pluginsResponse.ok()).toBeTruthy()
  const plugins = await pluginsResponse.json()

  const mutatingHeaders = {
    ...authHeaders,
    ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
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
    expect(
      hotUpdateResponse.ok(),
      `热更新失败: ${hotUpdateResponse.status()} ${await hotUpdateResponse.text()}`,
    ).toBeTruthy()

    const rollbackResponse = await request.post(`${backendApiBase}/plugins/${targetPluginId}/rollback`, {
      headers: mutatingHeaders,
      data: {},
    })
    expect(
      rollbackResponse.ok(),
      `回滚失败: ${rollbackResponse.status()} ${await rollbackResponse.text()}`,
    ).toBeTruthy()
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
