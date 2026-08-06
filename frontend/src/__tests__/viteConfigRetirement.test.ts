import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'
import type { ConfigEnv } from 'vite'

import viteConfig from '../../vite.config'


describe('Vite 构建冗余退役门禁', () => {
  it('不再生成部署层未消费的预压缩副本', () => {
    const configSource = readFileSync(
      resolve(process.cwd(), 'vite.config.ts'),
      'utf8',
    )

    expect(configSource).not.toContain('vite-plugin-compression')
    expect(configSource).not.toContain("ext: '.gz'")
    expect(configSource).not.toContain("ext: '.br'")
  })

  it('代理目标已包含 api 前缀时不会重复拼接', async () => {
    const previousTarget = process.env.OPENAWA_API_PROXY_TARGET
    process.env.OPENAWA_API_PROXY_TARGET = 'http://localhost:8000/api/'

    try {
      const configEnv: ConfigEnv = {
        command: 'serve',
        mode: 'development',
        isSsrBuild: false,
        isPreview: false,
      }
      const resolvedConfig = typeof viteConfig === 'function'
        ? await viteConfig(configEnv)
        : viteConfig
      const proxyOptions = resolvedConfig.server?.proxy?.['/api']

      expect(proxyOptions).toBeTypeOf('object')
      expect(proxyOptions && typeof proxyOptions === 'object' ? proxyOptions.target : undefined)
        .toBe('http://localhost:8000')
    } finally {
      if (previousTarget === undefined) {
        delete process.env.OPENAWA_API_PROXY_TARGET
      } else {
        process.env.OPENAWA_API_PROXY_TARGET = previousTarget
      }
    }
  })
})
