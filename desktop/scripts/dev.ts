/**
 * 开发模式启动脚本
 * 1. 启动 frontend dev server
 * 2. 设置 OPENAWA_FRONTEND_URL 环境变量
 * 3. 启动 electron 主进程
 */
import { spawn } from 'node:child_process'
import path from 'node:path'

// 脚本通过 npm run dev 从 desktop 目录执行，process.cwd() 即 desktop 根目录
// 注意：desktop 包为 CommonJS，此处不可使用 import.meta
const desktopDir = process.cwd()
const frontendDir = path.resolve(desktopDir, '..', 'frontend')
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
    cwd: desktopDir,
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
