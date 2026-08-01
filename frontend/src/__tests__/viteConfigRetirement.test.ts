import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'


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
})
