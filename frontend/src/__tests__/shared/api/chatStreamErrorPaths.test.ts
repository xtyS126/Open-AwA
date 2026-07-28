/**
 * sendMessageStream SSE 中途失败错误路径测试。
 *
 * 覆盖点：
 *   - HTTP 5xx 服务端错误：抛 createStreamError 携带 errorMessage + errorCode
 *   - 网络层错误（fetch reject）：透传原始 Error
 *   - SSE 流中推送 type=error 事件：onError 回调被调用，错误携带 code/message/retryable
 *   - 流读取过程中 reader.read() 抛错：整体 reject 且释放 reader 锁
 *   - 响应超过 10MB 上限：抛"响应超过 10MB 上限，已中止"并 cancel reader
 *   - AbortError（用户主动取消）：透传 DOMException
 *
 * Mock：
 *   - axios：避免真实 HTTP 客户端
 *   - @/shared/api/client：getCachedCsrfToken / refreshCsrfToken / API_BASE_URL
 *   - @/shared/utils/logger：避免日志污染测试输出
 *   - 全局 fetch：可控的 Response mock
 */
import { describe, expect, it, vi } from 'vitest'

const { fakeApiInstance } = vi.hoisted(() => {
  const apiInstanceMock = vi.fn() as unknown as {
    interceptors: unknown
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
    put: ReturnType<typeof vi.fn>
    delete: ReturnType<typeof vi.fn>
  }
  ;(apiInstanceMock as unknown as { interceptors: unknown }).interceptors = {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  }
  ;(apiInstanceMock as unknown as { get: ReturnType<typeof vi.fn> }).get = vi.fn()
  ;(apiInstanceMock as unknown as { post: ReturnType<typeof vi.fn> }).post = vi.fn()
  ;(apiInstanceMock as unknown as { put: ReturnType<typeof vi.fn> }).put = vi.fn()
  ;(apiInstanceMock as unknown as { delete: ReturnType<typeof vi.fn> }).delete = vi.fn()
  return { fakeApiInstance: apiInstanceMock }
})

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => fakeApiInstance),
    AxiosHeaders: { from: vi.fn((h: Record<string, unknown> = {}) => h) },
  },
}))

vi.mock('js-cookie', () => ({
  default: { get: vi.fn(() => '') },
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: { info: vi.fn(), warning: vi.fn(), error: vi.fn(), debug: vi.fn() },
  generateRequestId: vi.fn(() => 'req-test'),
  setCurrentRequestId: vi.fn(),
}))

vi.mock('@/shared/api/client', () => ({
  api: fakeApiInstance,
  getCachedApiKey: vi.fn(() => 'test-api-key'),
  getCachedCsrfToken: vi.fn(() => 'test-csrf-token'),
  refreshCsrfToken: vi.fn().mockResolvedValue(undefined),
  setTempApiKey: vi.fn(),
  persistApiKey: vi.fn(),
  clearCachedApiKey: vi.fn(),
  getApiErrorDetail: vi.fn(),
  logStreamParseWarning: vi.fn(),
  API_BASE_URL: 'http://localhost:8000',
}))

import * as apiModule from '@/shared/api/api'

/** 构造一个 mock fetch Response */
function buildResponse(opts: {
  ok: boolean
  status: number
  body?: ReadableStream<Uint8Array> | null
  headers?: Record<string, string>
  json?: () => Promise<unknown>
}): Response {
  const headers = new Headers(opts.headers || {})
  return {
    ok: opts.ok,
    status: opts.status,
    headers,
    body: opts.body ?? null,
    json: opts.json ?? (async () => ({})),
  } as unknown as Response
}

/** 把字符串编码成 Uint8Array */
function encode(text: string): Uint8Array {
  return new TextEncoder().encode(text)
}

/** 构造一个 mock reader，按 chunks 顺序返回，最后返回 done=true */
function buildReader(chunks: Uint8Array[], options?: { failOnCall?: number; error?: Error }) {
  let i = 0
  let readCalls = 0
  const releaseLock = vi.fn()
  const cancel = vi.fn().mockResolvedValue(undefined)
  return {
    releaseLock,
    cancel,
    read: vi.fn(async () => {
      readCalls += 1
      if (options?.failOnCall === readCalls && options?.error) {
        throw options.error
      }
      if (i < chunks.length) {
        const value = chunks[i]
        i += 1
        return { value, done: false }
      }
      return { value: undefined, done: true }
    }),
  }
}

describe('sendMessageStream - SSE 中途失败错误路径', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('HTTP 500 服务端错误：抛 createStreamError 携带 errorMessage + errorCode', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      buildResponse({
        ok: false,
        status: 500,
        json: async () => ({
          detail: 'Internal Server Error',
          error: { code: 'internal_server_error', message: 'Internal Server Error', retryable: true },
        }),
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      apiModule.chatAPI.sendMessageStream('hello', 'session-500')
    ).rejects.toThrow('Internal Server Error')

    const error = await apiModule.chatAPI.sendMessageStream('hello', 'session-500').catch((e) => e)
    expect(error).toBeInstanceOf(Error)
    expect((error as Error & { code?: string }).code).toBe('internal_server_error')
  })

  it('网络层错误（fetch reject）：透传原始 Error', async () => {
    const networkError = new TypeError('Failed to fetch')
    const fetchMock = vi.fn().mockRejectedValue(networkError)
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      apiModule.chatAPI.sendMessageStream('hello', 'session-network')
    ).rejects.toThrow('Failed to fetch')
  })

  it('SSE 流中推送 type=error 事件：onError 回调被调用，错误携带 code/message/retryable', async () => {
    const errorEventData = encode(
      'data: {"type":"error","error":{"code":"llm_call_failed","message":"LLM 服务暂不可用","retryable":true}}\n\n'
    )
    const reader = buildReader([errorEventData])
    const fetchMock = vi.fn().mockResolvedValue(
      buildResponse({
        ok: true,
        status: 200,
        body: { getReader: () => reader } as unknown as ReadableStream<Uint8Array>,
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    const onError = vi.fn()
    const onEvent = vi.fn()

    await apiModule.chatAPI.sendMessageStream(
      'hello',
      'session-error-event',
      undefined,
      undefined,
      onEvent,
      onError
    )

    expect(onError).toHaveBeenCalledTimes(1)
    const error = onError.mock.calls[0][0] as Error & { code?: string; retryable?: boolean }
    expect(error).toBeInstanceOf(Error)
    expect(error.message).toBe('LLM 服务暂不可用')
    expect(error.code).toBe('llm_call_failed')
    expect(error.retryable).toBe(true)
    // 错误事件不应触发 onEvent
    expect(onEvent).not.toHaveBeenCalled()
    // 释放 reader 锁
    expect(reader.releaseLock).toHaveBeenCalled()
  })

  it('流读取过程中 reader.read() 抛错：整体 reject 且释放 reader 锁', async () => {
    const reader = buildReader([encode('data: {"type":"chunk","content":"partial"}\n\n')], {
      failOnCall: 2,
      error: new Error('stream broken mid-flight'),
    })
    const fetchMock = vi.fn().mockResolvedValue(
      buildResponse({
        ok: true,
        status: 200,
        body: { getReader: () => reader } as unknown as ReadableStream<Uint8Array>,
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      apiModule.chatAPI.sendMessageStream('hello', 'session-broken-stream')
    ).rejects.toThrow('stream broken mid-flight')

    expect(reader.releaseLock).toHaveBeenCalled()
  })

  it('响应超过 10MB 上限：抛"响应超过 10MB 上限，已中止"并 cancel reader', async () => {
    // 构造一个超过 10MB 的 chunk
    const hugeChunk = new Uint8Array(11 * 1024 * 1024)
    const reader = buildReader([hugeChunk])
    const fetchMock = vi.fn().mockResolvedValue(
      buildResponse({
        ok: true,
        status: 200,
        body: { getReader: () => reader } as unknown as ReadableStream<Uint8Array>,
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      apiModule.chatAPI.sendMessageStream('hello', 'session-oversize')
    ).rejects.toThrow('响应超过 10MB 上限，已中止')

    // 应当 cancel reader 主动关闭流
    expect(reader.cancel).toHaveBeenCalled()
  })

  it('AbortError（用户主动取消）：透传 DOMException AbortError', async () => {
    const abortError = new DOMException('The user aborted a request.', 'AbortError')
    const fetchMock = vi.fn().mockRejectedValue(abortError)
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      apiModule.chatAPI.sendMessageStream('hello', 'session-aborted')
    ).rejects.toThrow('The user aborted a request.')

    const caught = await apiModule.chatAPI.sendMessageStream('hello', 'session-aborted').catch((e) => e)
    expect(caught).toBeInstanceOf(DOMException)
    expect((caught as DOMException).name).toBe('AbortError')
  })

  it('CSRF token 失效：自动 refreshCsrfToken 并重发一次', async () => {
    // 动态导入 client mock，便于在测试中切换 getCachedCsrfToken 的返回值
    const clientModule = await import('@/shared/api/client')
    const refreshCsrfTokenMock = clientModule.refreshCsrfToken as ReturnType<typeof vi.fn>
    const getCachedCsrfTokenMock = clientModule.getCachedCsrfToken as ReturnType<typeof vi.fn>

    // refreshCsrfToken 调用后，getCachedCsrfToken 切换返回新 token（模拟真实缓存行为）
    refreshCsrfTokenMock.mockImplementation(async () => {
      getCachedCsrfTokenMock.mockReturnValue('refreshed-csrf-token')
    })

    const reader = buildReader([
      encode('data: {"type":"chunk","content":"after retry"}\n\n'),
      encode('data: [DONE]\n\n'),
    ])

    const firstResponse = buildResponse({
      ok: false,
      status: 403,
      json: async () => ({
        error: { code: 'missing_csrf_token', message: 'CSRF token missing' },
      }),
    })
    const secondResponse = buildResponse({
      ok: true,
      status: 200,
      body: { getReader: () => reader } as unknown as ReadableStream<Uint8Array>,
    })

    const fetchMock = vi.fn()
      .mockResolvedValueOnce(firstResponse)
      .mockResolvedValueOnce(secondResponse)
    vi.stubGlobal('fetch', fetchMock)

    const onEvent = vi.fn()
    await apiModule.chatAPI.sendMessageStream(
      'hello',
      'session-csrf-retry',
      undefined,
      undefined,
      onEvent
    )

    // 应当发起两次 fetch（首次 + CSRF 重试）
    expect(fetchMock).toHaveBeenCalledTimes(2)
    // refreshCsrfToken 应被调用
    expect(refreshCsrfTokenMock).toHaveBeenCalled()
    // 第二次 fetch 的 headers 应携带新 token（通过 fetchMock 第二次调用的参数验证）
    const secondCallArgs = fetchMock.mock.calls[1]
    const secondHeaders = secondCallArgs[1]?.headers as Record<string, string>
    expect(secondHeaders['X-CSRF-Token']).toBe('refreshed-csrf-token')
  })
})
