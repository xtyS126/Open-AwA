/**
 * 窗口创建与管理
 */
import { BrowserWindow, session } from 'electron'
import path from 'node:path'
import log from 'electron-log'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getWindowBounds, setWindowBounds, getIsMaximized, setIsMaximized } from '../shared/config-store'

/**
 * 为默认 session 注入 Content-Security-Policy 等安全响应头。
 *
 * 安全策略：
 * - default-src 'self'：默认仅允许同源资源
 * - script-src 'self'：禁止内联脚本与外部脚本，防御 XSS
 * - style-src 'self' 'unsafe-inline'：允许内联样式（React/Vite 需要）
 * - connect-src：限制可连接的源，包含本地后端与 HMR
 * - object-src 'none'：禁止 Flash/Plugin
 * - base-uri 'self'：禁止 <base> 标签劫持
 *
 * 该方法在 app ready 后、窗口创建前调用一次，对所有 BrowserWindow 生效。
 */
export function installSecurityHeaders(): void {
  // 生产模式 CSP（最严格）：禁用 unsafe-inline、禁用外部连接（除本地后端）
  const isDev = !!process.env.OPENAWA_FRONTEND_URL
  const styleSrc = isDev
    ? "'self' 'unsafe-inline' https://fonts.googleapis.com"
    : "'self' https://fonts.googleapis.com"
  const connectSrc = isDev
    ? "'self' http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*"
    : "'self' http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*"

  const csp = [
    "default-src 'self'",
    `script-src 'self'`,
    `style-src ${styleSrc}`,
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob: https:",
    `connect-src ${connectSrc}`,
    "frame-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ')

  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [csp],
        'X-Content-Type-Options': ['nosniff'],
        'X-Frame-Options': ['SAMEORIGIN'],
        'Referrer-Policy': ['strict-origin-when-cross-origin'],
      },
    })
  })

  // 禁用 Webview（防止任意 webview 标签打开外部内容）
  // 已通过 webPreferences 关闭 webviewTag，这里再次确保
  log.info('安全响应头已注入（CSP/X-Content-Type-Options/X-Frame-Options）')
}

/** 主窗口引用 */
let mainWindow: BrowserWindow | null = null

/** 获取主窗口 */
export function getMainWindow(): BrowserWindow | null {
  return mainWindow
}

/** 设置主窗口引用（仅用于测试注入） */
export function setMainWindow(win: BrowserWindow | null): void {
  mainWindow = win
}

/** 渲染进程崩溃后的最大 reload 次数，超过即停止避免死循环 */
const MAX_RENDER_PROCESS_RELOAD = 3
/** render-process-gone 计数（按窗口实例隔离，通过闭包） */
let renderProcessReloadCount = 0

/**
 * 附加窗口事件桥接
 * - 最大化状态持久化 + 向渲染进程广播
 * - 关闭时保存边界
 * - closed 时清空全局引用，避免调用已销毁窗口
 *
 * 注意：必须在窗口创建后立即调用，确保监听器正确注册。
 */
export function attachWindowEventBridge(win: BrowserWindow): void {
  // 最大化状态变化：持久化 + 广播给渲染进程（统一一处，避免重复监听）
  win.on('maximize', () => {
    setIsMaximized(true)
    if (!win.isDestroyed()) {
      win.webContents.send(IPC_CHANNELS.WINDOW_MAXIMIZE_STATE_CHANGED, { isMaximized: true })
    }
  })
  win.on('unmaximize', () => {
    setIsMaximized(false)
    if (!win.isDestroyed()) {
      win.webContents.send(IPC_CHANNELS.WINDOW_MAXIMIZE_STATE_CHANGED, { isMaximized: false })
    }
  })

  // 窗口关闭时保存边界
  win.on('close', () => {
    if (!win.isMaximized() && !win.isMinimized()) {
      const [x, y] = win.getPosition()
      const [width, height] = win.getSize()
      setWindowBounds({ x, y, width, height })
    }
    setIsMaximized(win.isMaximized())
  })

  // closed 时清空全局引用，防止托盘/快捷键调用已销毁窗口抛 "Object has been destroyed"
  win.on('closed', () => {
    if (mainWindow === win) {
      mainWindow = null
    }
    renderProcessReloadCount = 0
  })

  // 窗口准备好后显示（避免白屏）
  win.once('ready-to-show', () => {
    win.show()
  })

  // 渲染进程崩溃处理：带计数与退避，避免崩溃-reload 死循环
  win.webContents.on('render-process-gone', (_event, details) => {
    log.error('渲染进程崩溃:', details)
    if (renderProcessReloadCount >= MAX_RENDER_PROCESS_RELOAD) {
      log.error(`渲染进程已连续崩溃 ${MAX_RENDER_PROCESS_RELOAD} 次，停止自动 reload，请重启应用`)
      return
    }
    renderProcessReloadCount += 1
    win.reload()
  })
}

/**
 * 创建主窗口
 * - 开发模式：加载 dev server URL
 * - 生产模式：加载本地 frontend dist
 */
export function createMainWindow(): BrowserWindow {
  const bounds = getWindowBounds()
  const isMaximized = getIsMaximized()

  const win = new BrowserWindow({
    width: bounds.width,
    height: bounds.height,
    x: bounds.x ?? undefined,
    y: bounds.y ?? undefined,
    minWidth: 1024,
    minHeight: 600,
    show: false,
    backgroundColor: '#ffffff',
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // 安全加固：显式启用 webSecurity（同源策略）、禁用 insecure content
      webSecurity: true,
      allowRunningInsecureContent: false,
      // 禁用 webview 标签（防止任意嵌入外部页面）
      webviewTag: false,
    },
  })

  // 导航防护：仅允许同源导航，拒绝跳转到外部 URL
  // 防止恶意页面通过 window.location 或 <a target="_blank"> 将用户引导至钓鱼站点
  win.webContents.on('will-navigate', (event, url) => {
    const currentUrl = win.webContents.getURL()
    try {
      const current = new URL(currentUrl)
      const target = new URL(url)
      // 仅允许同源导航
      if (target.origin !== current.origin) {
        event.preventDefault()
        log.warning(`阻止导航到外部 URL: ${url}`)
      }
    } catch {
      event.preventDefault()
      log.warning(`阻止非法 URL 导航: ${url}`)
    }
  })

  // 外部链接默认在系统浏览器打开，而不是在应用窗口内导航
  win.webContents.setWindowOpenHandler(({ url }) => {
    const currentUrl = win.webContents.getURL()
    try {
      const current = new URL(currentUrl)
      const target = new URL(url)
      if (target.origin !== current.origin) {
        // 外部链接：交给系统浏览器
        require('electron').shell.openExternal(url)
        return { action: 'deny' }
      }
    } catch {
      return { action: 'deny' }
    }
    return { action: 'allow' }
  })

  // 最大化状态恢复
  if (isMaximized) {
    win.maximize()
  }

  // 附加所有窗口事件桥接（统一一处管理，避免分散监听）
  attachWindowEventBridge(win)

  // 加载内容
  const frontendUrl = process.env.OPENAWA_FRONTEND_URL
  if (frontendUrl) {
    // 开发模式：加载 dev server
    win.loadURL(frontendUrl)
    // 自动打开开发者工具
    win.webContents.openDevTools()
  } else {
    // 生产模式：加载本地 frontend
    // build-frontend.ts 把 frontend/dist 内容直接复制到 resources/frontend
    // 因此此处应为 resources/frontend/index.html，而非 resources/frontend/dist/index.html
    const frontendPath = path.join(__dirname, '..', '..', 'resources', 'frontend', 'index.html')
    win.loadFile(frontendPath)
  }

  mainWindow = win
  return win
}
