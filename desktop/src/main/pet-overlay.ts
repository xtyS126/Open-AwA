/**
 * 宠物悬浮窗生命周期管理
 * 负责创建、显示、隐藏、销毁宠物悬浮窗 BrowserWindow
 * 支持位置持久化（electron-store）与开发/生产模式页面加载
 */
import { BrowserWindow, screen } from 'electron'
import path from 'node:path'
import log from 'electron-log'
import { getPetConfig, setPetConfig } from '../shared/config-store'

/** 宠物悬浮窗引用 */
let petOverlay: BrowserWindow | null = null

/** 获取宠物悬浮窗实例 */
export function getPetOverlay(): BrowserWindow | null {
  return petOverlay
}

/**
 * 创建宠物悬浮窗
 * - transparent: true, frame: false, alwaysOnTop: true, skipTaskbar: true
 * - focusable: false（不抢焦点，点击事件通过 setWindowOpenHandler 穿透）
 * - 默认大小 250x250，默认位置屏幕右下角
 * - webPreferences: preload 指向 pet-overlay.js，sandbox 模式
 */
export function createPetOverlay(): BrowserWindow {
  if (petOverlay && !petOverlay.isDestroyed()) {
    log.info('[pet-overlay] 悬浮窗已存在，返回现有实例')
    return petOverlay
  }

  const config = getPetConfig()
  const display = screen.getPrimaryDisplay()
  const { width: screenWidth, height: screenHeight } = display.workAreaSize

  // 恢复持久化位置，未配置时默认右下角
  const x = config.position.x >= 0 ? config.position.x : screenWidth - config.size - 20
  const y = config.position.y >= 0 ? config.position.y : screenHeight - config.size - 20

  const win = new BrowserWindow({
    width: config.size,
    height: config.size,
    x,
    y,
    transparent: true,
    frame: false,
    alwaysOnTop: config.alwaysOnTop,
    skipTaskbar: true,
    focusable: false,
    show: false,
    resizable: false,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'pet-overlay.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: false,
      // 安全加固
      webSecurity: true,
      allowRunningInsecureContent: false,
    },
  })

  // 防止焦点被捕获（即使 focusable: false 在某些平台仍可能获取焦点）
  win.setAlwaysOnTop(config.alwaysOnTop, 'screen-saver')

  // 窗口关闭时保存位置
  win.on('close', () => {
    if (!win.isDestroyed()) {
      const [wx, wy] = win.getPosition()
      const currentConfig = getPetConfig()
      setPetConfig({
        ...currentConfig,
        position: { x: wx, y: wy },
      })
    }
  })

  // closed 时清空全局引用
  win.on('closed', () => {
    petOverlay = null
  })

  // 加载内容
  const frontendUrl = process.env.OPENAWA_FRONTEND_URL
  if (frontendUrl) {
    // 开发模式：加载 Vite dev server 的 /pet-overlay 路由
    win.loadURL(`${frontendUrl}/pet-overlay`)
  } else {
    // 生产模式：加载本地 frontend 产物，通过 query 参数标识宠物悬浮窗
    // 路由模块在初始化时会检测 overlay=pet 参数并替换为 /pet-overlay 路径
    const frontendPath = path.join(__dirname, '..', '..', 'resources', 'frontend', 'index.html')
    win.loadFile(frontendPath, { query: { overlay: 'pet' } })
  }

  petOverlay = win

  log.info('[pet-overlay] 宠物悬浮窗已创建', { x, y, size: config.size })
  return win
}

/** 显示宠物悬浮窗 */
export function showPetOverlay(): void {
  const win = getPetOverlay()
  if (win && !win.isDestroyed()) {
    win.show()
    log.info('[pet-overlay] 悬浮窗已显示')
  } else {
    log.warn('[pet-overlay] 无法显示：悬浮窗不存在或已销毁')
  }
}

/** 隐藏宠物悬浮窗 */
export function hidePetOverlay(): void {
  const win = getPetOverlay()
  if (win && !win.isDestroyed()) {
    win.hide()
    log.info('[pet-overlay] 悬浮窗已隐藏')
  }
}

/** 切换宠物悬浮窗显示/隐藏 */
export function togglePetOverlay(): void {
  const win = getPetOverlay()
  if (win && !win.isDestroyed()) {
    if (win.isVisible()) {
      win.hide()
      log.info('[pet-overlay] 悬浮窗已隐藏（toggle）')
    } else {
      win.show()
      log.info('[pet-overlay] 悬浮窗已显示（toggle）')
    }
  }
}

/** 销毁宠物悬浮窗 */
export function destroyPetOverlay(): void {
  if (petOverlay && !petOverlay.isDestroyed()) {
    petOverlay.close()
    petOverlay = null
    log.info('[pet-overlay] 悬浮窗已销毁')
  }
}