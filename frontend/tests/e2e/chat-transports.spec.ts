import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { getApiKey, loginAsAdminApi } from './auth'

const backendPort = process.env.OPENAWA_E2E_BACKEND_PORT || '18000'
const backendBaseUrl = `http://127.0.0.1:${backendPort}`
const coordinatorPurpose = '模型原生工具调用与回答'

interface WebSocketProbeResult {
  protocolAccepted: boolean
  messageTypes: string[]
  final: Record<string, unknown>
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error(`${label} 不是对象`)
  }
  return value as Record<string, unknown>
}

async function createConversation(
  request: APIRequestContext,
  transport: string,
): Promise<string> {
  const response = await request.post('/api/conversations', {
    headers: { Authorization: `Bearer ${getApiKey()}` },
    data: { title: `${transport} 传输门禁 ${randomUUID().slice(0, 8)}` },
  })

  expect(response.status()).toBe(200)
  const payload = asRecord(await response.json(), '会话创建响应')
  expect(payload.session_id).toEqual(expect.any(String))
  return String(payload.session_id)
}

function parseSseEvents(body: string): Array<Record<string, unknown>> {
  return body
    .split('\n')
    .filter((line) => line.startsWith('data: ') && line !== 'data: [DONE]')
    .map((line) => asRecord(JSON.parse(line.slice(6)) as unknown, 'SSE 事件'))
}

function readCoordinatorPurposeFromPlan(event: Record<string, unknown>): string {
  const plan = asRecord(event.plan, '计划事件 plan')
  if (!Array.isArray(plan.steps) || plan.steps.length === 0) {
    throw new Error('计划事件缺少 steps')
  }
  const firstStep = asRecord(plan.steps[0], '计划第一步')
  return String(firstStep.purpose || '')
}

function readCoordinatorPurposeFromResponse(payload: Record<string, unknown>): string {
  if (!Array.isArray(payload.results) || payload.results.length === 0) {
    throw new Error('WebSocket 终态缺少 results')
  }
  const firstResult = asRecord(payload.results[0], 'WebSocket 第一项结果')
  const firstStep = asRecord(firstResult.step, 'WebSocket 第一项步骤')
  return String(firstStep.purpose || '')
}

async function probeWebSocket(
  page: Page,
  sessionId: string,
  token: string,
): Promise<WebSocketProbeResult> {
  await page.goto('/login')
  return page.evaluate(
    ({ url, protocol, timeoutMs }) => new Promise<WebSocketProbeResult>((resolve, reject) => {
      const socket = new WebSocket(url, [protocol])
      const messages: Array<Record<string, unknown>> = []
      let settled = false
      const timeout = window.setTimeout(() => {
        settled = true
        socket.close()
        reject(new Error(`WebSocket 超时，已收到 ${messages.length} 帧`))
      }, timeoutMs)

      socket.onopen = () => {
        socket.send(JSON.stringify({
          type: 'message',
          content: '请执行 WebSocket 新协调器传输门禁',
          request_id: `playwright-${Date.now()}`,
        }))
      }
      socket.onerror = () => {
        if (settled) return
        settled = true
        window.clearTimeout(timeout)
        reject(new Error('WebSocket 连接错误'))
      }
      socket.onclose = (event) => {
        if (settled) return
        settled = true
        window.clearTimeout(timeout)
        reject(new Error(
          `WebSocket 提前关闭 code=${event.code} reason=${event.reason} frames=${messages.length}`,
        ))
      }
      socket.onmessage = (event) => {
        const parsed: unknown = JSON.parse(String(event.data))
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          settled = true
          window.clearTimeout(timeout)
          socket.close()
          reject(new Error('WebSocket 返回了非对象帧'))
          return
        }
        const payload = parsed as Record<string, unknown>
        messages.push(payload)
        if (payload.type === 'response') {
          settled = true
          window.clearTimeout(timeout)
          const result = {
            protocolAccepted: socket.protocol.startsWith('bearer.'),
            messageTypes: messages.map((item) => String(item.type || '')),
            final: payload,
          }
          socket.close()
          resolve(result)
        }
      }
    }),
    {
      url: `${backendBaseUrl.replace(/^http/, 'ws')}/api/chat/ws/${sessionId}`,
      protocol: `bearer.${token}`,
      timeoutMs: 60_000,
    },
  )
}

test.describe.serial('聊天三传输与新 Agent 协调器发布门禁', () => {
  test('non-stream 返回结构化终态', async ({ request }) => {
    const sessionId = await createConversation(request, 'non-stream')
    const response = await request.post('/api/chat', {
      headers: { Authorization: `Bearer ${getApiKey()}` },
      data: {
        session_id: sessionId,
        message: '请执行 non-stream 新协调器传输门禁',
        mode: 'non-stream',
      },
      timeout: 60_000,
    })

    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('application/json')
    const payload = asRecord(await response.json(), 'non-stream 响应')
    expect(['completed', 'success', 'error', 'cancelled']).toContain(payload.status)
    expect(payload.session_id).toBe(sessionId)
    if (payload.status === 'error') {
      const error = asRecord(payload.error, 'non-stream 结构化错误')
      expect(error.code).toEqual(expect.any(String))
      expect(error.message).toEqual(expect.any(String))
    }
  })

  test('SSE 透传新协调器计划并以 DONE 帧结束', async ({ request }) => {
    const sessionId = await createConversation(request, 'SSE')
    const response = await request.post('/api/chat', {
      headers: { Authorization: `Bearer ${getApiKey()}` },
      data: {
        session_id: sessionId,
        message: '请执行 SSE 新协调器传输门禁',
        mode: 'stream',
      },
      timeout: 60_000,
    })

    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain('text/event-stream')
    const body = await response.text()
    const events = parseSseEvents(body)
    const eventTypes = events.map((event) => String(event.type || ''))
    expect(eventTypes).toContain('status')
    expect(eventTypes).toContain('plan')
    expect(eventTypes).toContain('error')
    expect(body).toContain('data: [DONE]')

    const planEvent = events.find((event) => event.type === 'plan')
    expect(planEvent).toBeDefined()
    expect(readCoordinatorPurposeFromPlan(planEvent!)).toBe(coordinatorPurpose)
  })

  test('WebSocket 接受子协议并返回新协调器执行结果', async ({ page, request }) => {
    const sessionId = await createConversation(request, 'WebSocket')
    const { token } = await loginAsAdminApi(request)
    const result = await probeWebSocket(page, sessionId, token)

    expect(result.protocolAccepted).toBe(true)
    expect(result.messageTypes).toContain('response_chunk')
    expect(result.messageTypes).toContain('response')
    expect(readCoordinatorPurposeFromResponse(result.final)).toBe(coordinatorPurpose)
  })
})
