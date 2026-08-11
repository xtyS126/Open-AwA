import { expect, test } from '@playwright/test'

test('隔离后端公开系统 ping 并返回实例能力', async ({ request }) => {
  const startedAt = performance.now()
  const response = await request.get('/api/system/ping')
  const elapsedMs = performance.now() - startedAt

  expect(response.status()).toBe(200)
  const payload = await response.json()
  expect(payload).toMatchObject({
    pong: true,
    instance_name: 'Open-AwA',
    api_prefix: '/api',
  })
  expect(typeof payload.version).toBe('string')
  expect(payload.capabilities).toEqual(expect.objectContaining({
    lan_discovery: true,
    api_key_auth: true,
  }))

  console.info(
    `system ping: status=${response.status()} request_id=${response.headers()['x-request-id'] ?? ''} elapsed_ms=${elapsedMs.toFixed(2)}`,
  )
})
