/**
 * 窗口创建与管理
 */
import { BrowserWindow } from 'electron'
import path from 'node:path'
import log from 'electron-log'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getWindowBounds, setWindowBounds, getIsMaximized, setIsMaximized } from '../shared/config-store'

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
    },
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
