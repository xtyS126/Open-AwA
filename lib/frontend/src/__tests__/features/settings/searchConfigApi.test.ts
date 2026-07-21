/**
 * searchConfigApi 模块单元测试
 *
 * 测试目标：
 *   - getSearchConfig：GET /api/search/config 的调用、返回值与错误传播
 *   - updateSearchConfig：PUT /api/search/config 的调用、payload、错误归一化
 *   - testSearchConfig：POST /api/search/test 的调用、返回值与错误归一化
 *   - SearchConfigError：构造、继承链与字段访问
 *
 * 设计要点：
 *   - mock @/shared/api/api 的默认导出，避免真实网络请求
 *   - 错误断言聚焦 SearchConfigError 的 detail / status 字段
 *   - 每个 beforeEach 重置 mock 调用记录，确保测试隔离
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getSearchConfig,
  updateSearchConfig,
  testSearchConfig,
  SearchConfigError,
} from '@/shared/api/searchConfigApi'
import type {
  SearchConfig,
  SearchConfigTest,
  SearchConfigUpdate,
  SearchTestResult,
} from '@/shared/api/searchConfigApi'

/** 提升到 vi.mock 之前的 mock 对象，确保工厂函数可访问 */
const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  default: apiMocks,
}))

/** 构造类 axios 错误对象 */
function makeAxiosError(
  status: number,
  data: unknown,
  message: string = 'Request failed',
): unknown {
  return {
    response: { status, data },
    message,
    isAxiosError: true,
  }
}

describe('searchConfigApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('getSearchConfig', () => {
    it('调用 GET /api/search/config', async () => {
      apiMocks.get.mockResolvedValue({ data: makeConfig() })

      await getSearchConfig()

      expect(apiMocks.get).toHaveBeenCalledWith('/search/config')
      expect(apiMocks.get).toHaveBeenCalledTimes(1)
    })

    it('成功时返回 SearchConfig 对象', async () => {
      const config = makeConfig({
        provider: 'searxng',
        base_url: 'http://192.168.2.10:7653/',
        api_key_set: true,
        extra_config: { allow_private_network: true },
      })
      apiMocks.get.mockResolvedValue({ data: config })

      const result = await getSearchConfig()

      expect(result).toEqual(config)
      expect(result.provider).toBe('searxng')
      expect(result.api_key_set).toBe(true)
    })

    it('后端返回 401 时抛出错误', async () => {
      apiMocks.get.mockRejectedValue(
        makeAxiosError(401, { detail: 'Unauthorized' }, 'Request failed with status code 401'),
      )

      // getSearchConfig 未做错误归一化，会直接抛出 axios 错误
      await expect(getSearchConfig()).rejects.toThrow()
    })
  })

  describe('updateSearchConfig', () => {
    it('使用正确的 payload 调用 PUT /api/search/config', async () => {
      const payload: SearchConfigUpdate = {
        provider: 'searxng',
        base_url: 'http://192.168.2.10:7653/',
        api_key: 'sk-xxx',
        extra_config: { allow_private_network: true },
      }
      apiMocks.put.mockResolvedValue({ data: makeConfig() })

      await updateSearchConfig(payload)

      expect(apiMocks.put).toHaveBeenCalledWith('/search/config', payload)
      expect(apiMocks.put).toHaveBeenCalledTimes(1)
    })

    it('成功时返回更新后的 SearchConfig', async () => {
      const updated = makeConfig({
        provider: 'searxng',
        base_url: 'http://192.168.2.10:7653/',
        api_key_set: true,
        extra_config: { allow_private_network: true },
      })
      apiMocks.put.mockResolvedValue({ data: updated })

      const result = await updateSearchConfig({
        provider: 'searxng',
        base_url: 'http://192.168.2.10:7653/',
      })

      expect(result).toEqual(updated)
      expect(result.api_key_set).toBe(true)
    })

    it('后端返回 403 SSRF 拒绝时抛出携带 detail 的 SearchConfigError', async () => {
      apiMocks.put.mockRejectedValue(
        makeAxiosError(403, { detail: '不允许配置内网地址' }),
      )

      await expect(
        updateSearchConfig({
          provider: 'searxng',
          base_url: 'http://192.168.2.10:7653/',
        }),
      ).rejects.toThrow(SearchConfigError)

      try {
        await updateSearchConfig({
          provider: 'searxng',
          base_url: 'http://192.168.2.10:7653/',
        })
      } catch (err) {
        expect(err).toBeInstanceOf(SearchConfigError)
        const searchErr = err as SearchConfigError
        expect(searchErr.detail).toContain('不允许配置内网地址')
        expect(searchErr.status).toBe(403)
      }
    })

    it('后端返回 422 校验错误时抛出错误', async () => {
      apiMocks.put.mockRejectedValue(
        makeAxiosError(422, {
          detail: [{ msg: 'field required', loc: ['body', 'provider'] }],
        }),
      )

      await expect(
        updateSearchConfig({ provider: 'searxng' }),
      ).rejects.toThrow(SearchConfigError)
    })

    it('api_key 为 undefined 时不发送该字段（避免覆盖为空）', async () => {
      apiMocks.put.mockResolvedValue({ data: makeConfig() })

      // 显式不传 api_key 字段
      const payload: SearchConfigUpdate = {
        provider: 'searxng',
        base_url: 'http://192.168.2.10:7653/',
        extra_config: { allow_private_network: true },
      }
      await updateSearchConfig(payload)

      const sentPayload = apiMocks.put.mock.calls[0][1] as SearchConfigUpdate
      expect(sentPayload.api_key).toBeUndefined()
      // api_key 字段应不存在或为 undefined，确保不会把后端已存的 Key 覆盖为空
      expect('api_key' in sentPayload).toBe(false)
    })
  })

  describe('testSearchConfig', () => {
    it('使用正确的 payload 调用 POST /api/search/test', async () => {
      const payload: SearchConfigTest = {
        provider: 'searxng',
        base_url: 'http://192.168.2.10:7653/',
        api_key: 'sk-xxx',
        extra_config: { allow_private_network: true },
      }
      apiMocks.post.mockResolvedValue({ data: makeSuccessResult() })

      await testSearchConfig(payload)

      expect(apiMocks.post).toHaveBeenCalledWith('/search/test', payload)
      expect(apiMocks.post).toHaveBeenCalledTimes(1)
    })

    it('成功时返回 SearchTestResult', async () => {
      const result = makeSuccessResult()
      apiMocks.post.mockResolvedValue({ data: result })

      const actual = await testSearchConfig({ provider: 'searxng' })

      expect(actual).toEqual(result)
      expect(actual.success).toBe(true)
      expect(actual.latency_ms).toBe(50)
      expect(actual.sample_results).toHaveLength(1)
    })

    it('后端返回失败结果时正常返回（不抛错）', async () => {
      const failureResult = makeFailureResult()
      apiMocks.post.mockResolvedValue({ data: failureResult })

      const actual = await testSearchConfig({ provider: 'searxng' })

      expect(actual).toEqual(failureResult)
      expect(actual.success).toBe(false)
      expect(actual.error).toBe('timeout')
    })

    it('网络错误时抛出 SearchConfigError', async () => {
      // 模拟 axios ECONNREFUSED：无 response 字段
      apiMocks.post.mockRejectedValue(new Error('Network Error'))

      await expect(
        testSearchConfig({ provider: 'searxng' }),
      ).rejects.toThrow(SearchConfigError)

      try {
        await testSearchConfig({ provider: 'searxng' })
      } catch (err) {
        expect(err).toBeInstanceOf(SearchConfigError)
        const searchErr = err as SearchConfigError
        expect(searchErr.detail).toBe('Network Error')
      }
    })
  })

  describe('SearchConfigError 类', () => {
    it('使用 message 与 detail 构造', () => {
      const error = new SearchConfigError('msg', 'detail')

      expect(error.message).toBe('msg')
      expect(error.detail).toBe('detail')
    })

    it('是 Error 的实例', () => {
      const error = new SearchConfigError('msg', 'detail')

      expect(error).toBeInstanceOf(Error)
    })

    it('是 SearchConfigError 的实例', () => {
      const error = new SearchConfigError('msg', 'detail')

      expect(error).toBeInstanceOf(SearchConfigError)
    })
  })
})

/** 构造测试用 SearchConfig */
function makeConfig(overrides: Partial<SearchConfig> = {}): SearchConfig {
  return {
    provider: 'searxng',
    base_url: 'http://192.168.2.10:7653/',
    api_key_set: false,
    enabled: true,
    extra_config: {},
    ...overrides,
  }
}

/** 构造测试成功结果 */
function makeSuccessResult(): SearchTestResult {
  return {
    success: true,
    latency_ms: 50,
    sample_results: [
      {
        title: '示例结果',
        url: 'https://example.com/sample',
        snippet: '这是示例摘要',
      },
    ],
  }
}

/** 构造测试失败结果 */
function makeFailureResult(): SearchTestResult {
  return {
    success: false,
    latency_ms: 5000,
    sample_results: [],
    error: 'timeout',
  }
}
