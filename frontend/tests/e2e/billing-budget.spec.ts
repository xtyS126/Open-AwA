import { expect, test } from '@playwright/test'
import { E2E_API_KEY, loginAsAdminPage } from './auth'

const authorizationHeaders = {
  Authorization: `Bearer ${E2E_API_KEY}`,
}

async function getMutationHeaders(page: Parameters<typeof loginAsAdminPage>[0]) {
  const csrfResponse = await page.request.get('/api/auth/csrf-token', {
    headers: authorizationHeaders,
  })
  expect(
    csrfResponse.ok(),
    `获取 CSRF token 失败: ${csrfResponse.status()} ${await csrfResponse.text()}`,
  ).toBeTruthy()

  const csrfPayload = await csrfResponse.json()
  expect(typeof csrfPayload.csrf_token).toBe('string')
  expect(csrfPayload.csrf_token).not.toBe('')

  return {
    ...authorizationHeaders,
    'X-CSRF-Token': csrfPayload.csrf_token as string,
  }
}

test.describe('计费与预算 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdminPage(page)
  })

  test('计费页面展示核心操作', async ({ page }) => {
    await page.goto('/billing')

    await expect(page.getByRole('heading', { name: '用量计费' })).toBeVisible()
    await expect(page.getByText('查看 AI 模型调用的成本与用量统计')).toBeVisible()
    await expect(page.getByRole('button', { name: '导出CSV' })).toBeVisible()
    await expect(page.getByRole('button', { name: '同步模型目录' })).toBeVisible()
  })

  test('用量统计卡片与图表完整渲染', async ({ page }) => {
    await page.goto('/billing')

    for (const heading of ['总成本', '输入Tokens', '输出Tokens', 'API调用次数', '成本趋势', '模型使用分布']) {
      await expect(page.getByRole('heading', { name: heading })).toBeVisible()
    }
  })

  test('创建预算后页面显示预算状态', async ({ page }) => {
    const mutationHeaders = await getMutationHeaders(page)
    const createResponse = await page.request.post('/api/billing/budget', {
      headers: mutationHeaders,
      data: {
        budget_type: 'global',
        max_amount: 100,
        period_type: 'monthly',
        currency: 'USD',
        warning_threshold: 80,
      },
    })
    expect(
      createResponse.ok(),
      `创建预算失败: ${createResponse.status()} ${await createResponse.text()}`,
    ).toBeTruthy()
    const createdBudget = await createResponse.json()
    expect(createdBudget.id).toBeTruthy()

    try {
      await page.goto('/billing')
      await expect(page.getByText(/^预算:/)).toBeVisible()
    } finally {
      const deleteResponse = await page.request.delete(`/api/billing/budget/${createdBudget.id}`, {
        headers: mutationHeaders,
      })
      expect(
        deleteResponse.ok(),
        `删除预算失败: ${deleteResponse.status()} ${await deleteResponse.text()}`,
      ).toBeTruthy()
    }
  })

  test('用量明细表暴露完整计费字段', async ({ page }) => {
    await page.goto('/billing')

    await expect(page.getByRole('heading', { name: '用量明细' })).toBeVisible()
    for (const column of ['时间', '厂商', '模型', '输入Tokens', '输出Tokens', '成本', '耗时', '操作']) {
      await expect(page.getByRole('columnheader', { name: column, exact: true })).toBeVisible()
    }
  })
})
