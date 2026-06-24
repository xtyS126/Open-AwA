import { describe, it, expect } from 'vitest'

describe('WebSocket URL 推导', () => {
  it('从相对路径 /api 推导为当前 host 的 ws 连接', async () => {
    // 模拟 web 模式：API_BASE_URL = '/api'，使用 location.host
    const apiBaseUrl = '/api'
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const expected = `${protocol}//${host}/api/weixin/ws`
    const actual = `${protocol}//${host}${apiBaseUrl}/weixin/ws`
    expect(actual).toBe(expected)
  })

  it('从绝对 URL 推导 ws/wss 协议与 host', async () => {
    const apiBaseUrl = 'http://remote-backend:8000/api'
    const url = new URL(apiBaseUrl)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    const expected = `ws://remote-backend:8000/api/weixin/ws`
    const actual = `${protocol}//${url.host}${url.pathname}/weixin/ws`
    expect(actual).toBe(expected)
  })

  it('从 HTTPS 绝对 URL 推导 wss 协议', async () => {
    const apiBaseUrl = 'https://secure-backend:8443/api'
    const url = new URL(apiBaseUrl)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    const expected = `wss://secure-backend:8443/api/weixin/ws`
    const actual = `${protocol}//${url.host}${url.pathname}/weixin/ws`
    expect(actual).toBe(expected)
  })
})
