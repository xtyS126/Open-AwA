/**
 * 窗口创建与管理
 */
import { BrowserWindow } from 'electron'
import path from 'node:path'
import { getWindowBounds, setWindowBounds, getIsMaximized, setIsMaximized } from '../shared/config-store'

/** 主窗口引用 */
let mainWindow: BrowserWindow | null = null

/** 获取主窗口 */
export function getMainWindow(): BrowserWindow | null {
  return mainWindow
}

/** 设置主窗口引用 */
export function setMainWindow(win: BrowserWindow | null): void {
  mainWindow = win
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

  // 窗口关闭时保存边界
  win.on('close', () => {
    if (!win.isMaximized() && !win.isMinimized()) {
      const [x, y] = win.getPosition()
      const [width, height] = win.getSize()
      setWindowBounds({ x, y, width, height })
    }
    setIsMaximized(win.isMaximized())
  })

  // 最大化状态变化时保存
  win.on('maximize', () => setIsMaximized(true))
  win.on('unmaximize', () => setIsMaximized(false))

  // 窗口准备好后显示（避免白屏）
  win.once('ready-to-show', () => {
    win.show()
  })

  // 渲染进程崩溃处理
  win.webContents.on('render-process-gone', (_event, details) => {
    console.error('渲染进程崩溃:', details)
    win.reload()
  })

  // 加载内容
  const frontendUrl = process.env.OPENAWA_FRONTEND_URL
  if (frontendUrl) {
    // 开发模式：加载 dev server
    win.loadURL(frontendUrl)
    // 自动打开开发者工具
    win.webContents.openDevTools()
  } else {
    // 生产模式：加载本地 frontend dist
    const frontendPath = path.join(__dirname, '..', '..', 'resources', 'frontend', 'dist', 'index.html')
    win.loadFile(frontendPath)
  }

  mainWindow = win
  return win
}
