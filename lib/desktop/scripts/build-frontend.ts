/**
 * 构建前端并复制产物到 desktop/resources/frontend
 */
import { execSync } from 'node:child_process'
import { cpSync, mkdirSync, existsSync, rmSync } from 'node:fs'
import path from 'node:path'

// __file__ = lib/desktop/scripts/build-frontend.ts；上溯 3 级到项目根，再进入 lib/frontend
const frontendDir = path.resolve(__dirname, '..', '..', '..', 'lib', 'frontend')
const frontendDist = path.join(frontendDir, 'dist')
const targetDir = path.resolve(__dirname, '..', 'resources', 'frontend')

console.log('[build-frontend] 开始构建前端...')

// 1. 构建前端
console.log('[build-frontend] 执行 npm run build...')
execSync('npm run build', {
  cwd: frontendDir,
  stdio: 'inherit',
})

// 2. 验证前端产物
if (!existsSync(frontendDist)) {
  throw new Error('前端构建失败：dist 目录不存在')
}

// 3. 清理目标目录
if (existsSync(targetDir)) {
  console.log('[build-frontend] 清理旧产物...')
  rmSync(targetDir, { recursive: true, force: true })
}

// 4. 复制产物
console.log('[build-frontend] 复制产物到 resources/frontend...')
mkdirSync(path.dirname(targetDir), { recursive: true })
cpSync(frontendDist, targetDir, { recursive: true })

console.log('[build-frontend] 构建完成')
