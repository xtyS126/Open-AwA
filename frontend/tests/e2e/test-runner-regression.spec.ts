import { expect, test } from '@playwright/test'
import { getApiKey } from './auth'

interface ScenarioResult {
  name: string
  status: string
  message: string
}

interface ScenarioRunResponse {
  results: ScenarioResult[]
  passed: number
  failed: number
  total: number
  duration_ms: number
}

test('run-all 执行全部系统场景且仅允许真实模型场景缺少密钥', async ({ request }) => {
  test.setTimeout(180_000)

  const response = await request.post('/api/test-scenarios/run-all', {
    headers: { Authorization: `Bearer ${getApiKey()}` },
    timeout: 150_000,
  })

  expect(response.status()).toBe(200)
  const payload = await response.json() as ScenarioRunResponse
  expect(payload.total).toBe(10)
  expect(payload.results).toHaveLength(payload.total)
  expect(payload.passed + payload.failed).toBe(payload.total)
  expect(payload.duration_ms).toBeGreaterThanOrEqual(0)

  const failedNames = payload.results
    .filter((result) => result.status !== 'ok')
    .map((result) => result.name)
  expect(failedNames.every((name) => name === 'chat-nonstream')).toBe(true)

  console.info(`run-all 汇总: ${payload.passed}/${payload.total} 通过，失败场景: ${failedNames.join(', ') || '无'}`)
})
