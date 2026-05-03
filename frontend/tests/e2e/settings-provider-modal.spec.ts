import { expect, test, type APIRequestContext } from '@playwright/test'
import { loginAsAdminApi, loginAsAdminPage } from './auth'

const backendApiBase = `http://127.0.0.1:${process.env.OPENAWA_E2E_BACKEND_PORT || '18000'}/api`

async function deleteProviderIfExists(request: APIRequestContext, providerId: string) {
  const { token, csrfToken } = await loginAsAdminApi(request)
  await request.delete(`${backendApiBase}/billing/providers/${providerId}`, {
    headers: {
      Authorization: `Bearer ${token}`,
      ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
    },
    failOnStatusCode: false,
  })
}

test('新增供应商弹窗仅保留显示名称和基础 URL，并为预置供应商自动填充基础 URL', async ({ page, request }) => {
  const providerId = 'moonshot'

  await deleteProviderIfExists(request, providerId)
  await loginAsAdminPage(page)
  await page.goto('/settings?tab=api')

  await expect(page.getByRole('heading', { name: 'API配置' })).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: '新增供应商' }).click()

  const dialog = page.getByRole('dialog', { name: '新增供应商' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByLabel('显示名称（可选）')).toBeVisible()
  await expect(dialog.getByLabel('基础 URL（可选）')).toBeVisible()
  await expect(dialog.getByText('图标地址（可选）')).toHaveCount(0)
  await expect(dialog.getByText('默认模型（可选）')).toHaveCount(0)
  await expect(dialog.getByText('API URL（可选）')).toHaveCount(0)
  await expect(dialog.getByText('API Key（可选）')).toHaveCount(0)
  await expect(dialog.getByText('最大 Token 数（可选）')).toHaveCount(0)

  await dialog.getByLabel('供应商标识').selectOption(providerId)
  await expect(dialog.getByLabel('显示名称（可选）')).toHaveValue('Kimi')
  await expect(dialog.getByLabel('基础 URL（可选）')).toHaveValue('https://api.moonshot.cn/v1')

  await dialog.getByLabel('显示名称（可选）').fill('Moonshot 国内镜像')
  await dialog.getByLabel('基础 URL（可选）').fill('https://api.moonshot.cn/v1/chat/completions')

  const createRequestPromise = page.waitForRequest((requestItem) => {
    return requestItem.method() === 'POST' && requestItem.url().includes('/api/billing/configurations')
  })

  await dialog.getByRole('button', { name: '确认创建' }).click()

  const createRequest = await createRequestPromise
  const payload = createRequest.postDataJSON() as Record<string, unknown>
  expect(payload).toEqual({
    provider: 'moonshot',
    model: 'custom-model',
    display_name: 'Moonshot 国内镜像',
    api_endpoint: 'https://api.moonshot.cn/v1',
    is_default: false,
  })

  await expect(page.getByText('供应商创建成功')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('button', { name: /Moonshot 国内镜像/ })).toBeVisible({ timeout: 20_000 })
})
