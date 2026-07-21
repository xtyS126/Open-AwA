/**
 * 开发模式启动脚本
 * 1. 启动 frontend dev server
 * 2. 设置 OPENAWA_FRONTEND_URL 环境变量
 * 3. 启动 electron 主进程
 */
import { spawn } from 'node:child_process'
import path from 'node:path'

// __file__ = lib/desktop/scripts/dev.ts；上溯 3 级到项目根，再进入 lib/frontend
const frontendDir = path.resolve(__dirname, '..', '..', '..', 'lib', 'frontend')
const frontendPort = process.env.OPENAWA_FRONTEND_PORT || '5173'
const frontendUrl = `http://localhost:${frontendPort}`

console.log('[dev] 启动 frontend dev server...')

// 启动 frontend dev server
const frontendProcess = spawn('npm', ['run', 'dev'], {
  cwd: frontendDir,
  stdio: 'inherit',
  shell: true,
})

// 等待 frontend 启动后启动 electron
setTimeout(() => {
  console.log('[dev] 启动 electron 主进程...')

  const env = {
    ...process.env,
    OPENAWA_FRONTEND_URL: frontendUrl,
  }

  const electronProcess = spawn('npx', ['electron', '.'], {
    cwd: path.resolve(__dirname, '..'),
    stdio: 'inherit',
    shell: true,
    env,
  })

  // electron 退出时关闭 frontend
  electronProcess.on('close', () => {
    console.log('[dev] electron 退出，关闭 frontend dev server...')
    frontendProcess.kill()
    process.exit(0)
  })
}, 5000)

// Ctrl+C 时清理
process.on('SIGINT', () => {
  frontendProcess.kill()
  process.exit(0)
})
