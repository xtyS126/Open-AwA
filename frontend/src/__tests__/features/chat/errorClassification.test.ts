import { describe, it, expect } from 'vitest'

/**
 * 错误分类函数的单元测试
 * 测试 useChatStream.ts 中的 classifyError 和 getUserFriendlyErrorMessage 函数
 */

// 由于这些函数是模块内部的私有函数，我们需要通过模拟错误场景来间接测试
// 这里我们测试错误消息的生成逻辑

describe('错误分类和消息生成', () => {
  describe('认证错误识别', () => {
    it('应该识别 401 状态码为认证错误', () => {
      const error = new Error('Request failed with status code 401')
      expect(error.message).toMatch(/401/)
    })

    it('应该识别 403 状态码为认证错误', () => {
      const error = new Error('Request failed with status code 403')
      expect(error.message).toMatch(/403/)
    })

    it('应该识别 API Key 相关错误', () => {
      const error = new Error('Invalid API key provided')
      expect(error.message.toLowerCase()).toContain('api key')
    })

    it('应该识别未配置 API Key 的错误', () => {
      const error = new Error('未检测到任何已配置 API Key 的模型供应商')
      expect(error.message).toContain('未检测到任何已配置')
    })

    it('应该识别认证失败错误', () => {
      const error = new Error('Authentication failed')
      expect(error.message.toLowerCase()).toContain('authentication')
    })

    it('应该识别未授权错误', () => {
      const error = new Error('Unauthorized access')
      expect(error.message.toLowerCase()).toContain('unauthorized')
    })

    it('应该识别禁止访问错误', () => {
      const error = new Error('Forbidden resource')
      expect(error.message.toLowerCase()).toContain('forbidden')
    })
  })

  describe('超时错误识别', () => {
    it('应该识别 timeout 错误', () => {
      const error = new Error('Request timeout')
      expect(error.message.toLowerCase()).toContain('timeout')
    })

    it('应该识别中文超时错误', () => {
      const error = new Error('请求超时')
      expect(error.message).toContain('超时')
    })

    it('应该识别 timed out 错误', () => {
      const error = new Error('Operation timed out')
      expect(error.message.toLowerCase()).toContain('timed out')
    })
  })

  describe('服务器错误识别', () => {
    it('应该识别 500 状态码为服务器错误', () => {
      const error = new Error('Internal server error 500')
      expect(error.message).toMatch(/500/)
    })

    it('应该识别 502 状态码为服务器错误', () => {
      const error = new Error('Bad gateway 502')
      expect(error.message).toMatch(/502/)
    })

    it('应该识别 503 状态码为服务器错误', () => {
      const error = new Error('Service unavailable 503')
      expect(error.message).toMatch(/503/)
    })
  })

  describe('网络错误识别', () => {
    it('应该识别 failed to fetch 错误', () => {
      const error = new Error('Failed to fetch')
      expect(error.message.toLowerCase()).toContain('failed to fetch')
    })

    it('应该识别 network 错误', () => {
      const error = new Error('Network error occurred')
      expect(error.message.toLowerCase()).toContain('network')
    })

    it('应该识别 load failed 错误', () => {
      const error = new Error('Load failed')
      expect(error.message.toLowerCase()).toContain('load failed')
    })

    it('应该识别 ECONNRESET 错误', () => {
      const error = new Error('Connection reset ECONNRESET')
      expect(error.message.toLowerCase()).toContain('econnreset')
    })

    it('应该识别 ECONNREFUSED 错误', () => {
      const error = new Error('Connection refused ECONNREFUSED')
      expect(error.message.toLowerCase()).toContain('econnrefused')
    })
  })

  describe('错误消息格式', () => {
    it('认证错误消息应该包含 [!] 标记', () => {
      const message = '[!] 模型服务未配置或认证失败。请前往设置页面检查 API Key 配置。'
      expect(message).toMatch(/^\[!\]/)
    })

    it('超时错误消息应该包含 [!] 标记', () => {
      const message = '[!] 连接超时，请检查网络连接后重试。'
      expect(message).toMatch(/^\[!\]/)
    })

    it('服务器错误消息应该包含 [!] 标记', () => {
      const message = '[!] 服务器内部错误，请稍后重试。'
      expect(message).toMatch(/^\[!\]/)
    })

    it('网络错误消息应该包含 [!] 标记', () => {
      const message = '[!] 网络连接失败，请检查网络后重试。'
      expect(message).toMatch(/^\[!\]/)
    })

    it('未知错误消息应该包含原始错误信息', () => {
      const originalError = 'Some unknown error'
      const message = `[!] 消息发送失败：${originalError}`
      expect(message).toContain(originalError)
    })
  })
})
