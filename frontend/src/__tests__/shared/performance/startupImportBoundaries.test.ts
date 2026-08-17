import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const readFrontendFile = (relativePath: string): string => (
  readFileSync(resolve(process.cwd(), relativePath), 'utf8')
)

describe('启动性能边界', () => {
  it('启动关键路径不通过兼容 API barrel 拉入无关业务模块', () => {
    const startupFiles = [
      'src/shared/hooks/useAppInitialization.ts',
      'src/shared/utils/preferenceSync.ts',
      'src/shared/components/GlobalTopBar/GlobalTopBar.tsx',
      'src/shared/components/UserFloatingArea.tsx',
    ]

    for (const relativePath of startupFiles) {
      const source = readFrontendFile(relativePath)
      expect(source, `${relativePath} 不得依赖兼容 API barrel`).not.toContain("from '@/shared/api/api'")
    }
  })

  it('非工作台路由不会静态加载 WorkbenchShell', () => {
    const routerSource = readFrontendFile('src/router/index.tsx')

    expect(routerSource).not.toMatch(/^import WorkbenchShell from ['"]@\/features\/workbench\/WorkbenchShell['"]/m)
    expect(routerSource).toContain("React.lazy(() => import('@/features/workbench/WorkbenchShell'))")
  })

  it('开发服务器保持 HTTP 以便旧同源 Worker 能获取退役脚本', () => {
    const viteSource = readFrontendFile('vite.config.ts')
    const packageJson = JSON.parse(readFrontendFile('package.json')) as {
      dependencies?: Record<string, string>
      devDependencies?: Record<string, string>
    }

    expect(viteSource).not.toContain('@vitejs/plugin-basic-ssl')
    expect(viteSource).not.toContain('basicSsl()')
    expect(packageJson.dependencies?.['@vitejs/plugin-basic-ssl']).toBeUndefined()
    expect(packageJson.devDependencies?.['@vitejs/plugin-basic-ssl']).toBeUndefined()
  })
})
