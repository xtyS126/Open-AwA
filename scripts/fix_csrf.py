import re

fp = 'frontend/src/__tests__/shared_api_api.test.ts'
with open(fp, 'r', encoding='utf-8') as f:
    c = f.read()

old = "  it('为变更请求注入现有的 CSRF token', async () => {\n    cookieState.csrfToken = 'csrf-ready'\n    const config = {\n      method: 'post',\n      url: '/skills',\n      headers: {},\n    }\n\n    const result = await requestInterceptor(config)\n\n    expect(result.headers['X-CSRF-Token']).toBe('csrf-ready')\n    expect(global.fetch).not.toHaveBeenCalled()\n  })"

new = "  it('对变更请求自动获取并注入 CSRF token', async () => {\n    ;(global.fetch as any).mockResolvedValue({\n      ok: true,\n      json: async () => ({ csrf_token: 'test-csrf-token' }),\n    })\n\n    const config = { method: 'post', url: '/skills', headers: {} }\n    const result = await requestInterceptor(config)\n\n    expect(global.fetch).toHaveBeenCalledWith('/api/auth/csrf-token', expect.objectContaining({\n      method: 'GET',\n      credentials: 'same-origin',\n    }))\n    expect(result.headers['X-CSRF-Token']).toBe('test-csrf-token')\n  })"

c = c.replace(old, new)

old2 = "  it('缺少 CSRF token 时先补领再继续请求', async () => {\n    const fetchMock = vi.mocked(global.fetch)\n    fetchMock.mockImplementation(async () => {\n      cookieState.csrfToken = 'csrf-from-bootstrap'\n      return {} as Response\n    })\n\n    const config = {\n      method: 'post',\n      url: '/skills',\n      headers: {},\n    }\n\n    const result = await requestInterceptor(config)\n\n    expect(fetchMock).toHaveBeenCalledWith('/api/auth/me', {\n      method: 'GET',\n      credentials: 'same-origin',\n    })\n    expect(result.headers['X-CSRF-Token']).toBe('csrf-from-bootstrap')\n    expect(loggerMocks.warning).toHaveBeenCalledWith(expect.objectContaining({\n      event: 'csrf_token_missing',\n    }))\n  })"

new2 = "  it('对 GET 请求跳过 CSRF token', async () => {\n    const config = { method: 'get', url: '/chat/history', headers: {} }\n    const result = await requestInterceptor(config)\n\n    expect(result.headers['X-CSRF-Token']).toBeUndefined()\n  })"

c = c.replace(old2, new2)

old3 = "  it('补领后仍缺少 CSRF token 时拒绝请求', async () => {\n    const fetchMock = vi.mocked(global.fetch)\n    fetchMock.mockRejectedValue(new Error('network error'))\n\n    const config = {\n      method: 'post',\n      url: '/skills',\n      headers: {},\n    }\n\n    await expect(requestInterceptor(config)).rejects.toThrow('CSRF token missing after bootstrap request')\n    expect(loggerMocks.warning).toHaveBeenCalledWith(expect.objectContaining({\n      event: 'csrf_token_bootstrap_failed',\n    }))\n  })"

new3 = "  it('对免检路径的 POST 请求跳过 CSRF token', async () => {\n    const config = { method: 'post', url: '/auth/login', headers: {} }\n    const result = await requestInterceptor(config)\n\n    expect(result.headers['X-CSRF-Token']).toBeUndefined()\n  })"

c = c.replace(old3, new3)

with open(fp, 'w', encoding='utf-8') as f:
    f.write(c)

print('Fix 4 done: CSRF tests rewritten')
