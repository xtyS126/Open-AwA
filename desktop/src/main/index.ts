/**
 * Electron 主进程入口
 * 负责 app 生命周期、单实例锁、初始化各模块、异常处理与日志
 */
import { app, BrowserWindow, ipcMain, dialog } from 'electron'
import path from 'node:path'
import log from 'electron-log'
import { createMainWindow, getMainWindow } from './window'
import { registerAllIpcHandlers } from './ipc'
import { setupMenu } from './menu'
import { setupTray, destroyTray } from './tray'
import { registerGlobalShortcuts, unregisterAllShortcuts } from './shortcuts'
import { initAutoUpdater, disposeAutoUpdater } from './updater'
import { getBackendUrl } from '../shared/config-store'

// 配置日志
log.transports.file.level = 'info'
log.transports.console.level = 'info'
log.transports.file.resolvePathFn = () => path.join(app.getPath('userData'), 'logs', 'main.log')

// 全局异常处理
process.on('uncaughtException', (error) => {
  log.error('uncaughtException:', error)
  // app.quit 可能再次抛错导致循环，加保护
  try {
    dialog.showErrorBox('应用错误', `发生未预期错误：\n${error.message}\n\n应用将退出。`)
  } catch (dialogErr) {
    log.error('显示错误对话框失败:', dialogErr)
  }
  app.quit()
})

process.on('unhandledRejection', (reason) => {
  log.error('unhandledRejection:', reason)
})

// 单实例锁：防止多开
const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const win = getMainWindow()
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

  app.whenReady().then(() => {
    // 注册所有 IPC 处理器
    registerAllIpcHandlers()

    // 检查后端 URL 是否已配置
    const backendUrl = process.env.OPENAWA_BACKEND_URL || getBackendUrl()
    if (!backendUrl) {
      // 首次启动：显示引导页
      showOnboardingWindow()
    } else {
      // 已配置：直接创建主窗口
      startMainWindow()
    }

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        const url = process.env.OPENAWA_BACKEND_URL || getBackendUrl()
        if (url) {
          startMainWindow()
        } else {
          // 未配置过：重新引导
          showOnboardingWindow()
        }
      }
    })
  })
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// 退出时清理资源：注销全局快捷键 + 销毁托盘 + 清理更新定时器
app.on('will-quit', () => {
  unregisterAllShortcuts()
  destroyTray()
  disposeAutoUpdater()
})

/** 引导窗口引用 */
let onboardingWindow: BrowserWindow | null = null

/** 显示引导窗口 */
function showOnboardingWindow(): void {
  // 防止重复创建引导窗口
  if (onboardingWindow) {
    onboardingWindow.focus()
    return
  }

  const onboardingWin = new BrowserWindow({
    width: 480,
    height: 400,
    resizable: false,
    minimizable: false,
    maximizable: false,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'onboarding.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  onboardingWindow = onboardingWin

  onboardingWin.loadFile(path.join(__dirname, '..', '..', 'resources', 'onboarding.html'))
  onboardingWin.once('ready-to-show', () => {
    onboardingWin.show()
  })

  // 监听后端 URL 设置成功事件（由 backend.ts 的 handleSetUrl 发送）
  const onUrlSaved = (): void => {
    onboardingWin.close()
    startMainWindow()
  }
  ipcMain.once('backend:url-saved', onUrlSaved)

  // 用户直接关闭引导窗口（点 X）时：清理 once 监听器并退出应用
  // 否则监听器永远不会触发，应用卡死在无窗口状态
  onboardingWin.on('closed', () => {
    ipcMain.removeListener('backend:url-saved', onUrlSaved)
    onboardingWindow = null
    // 若主窗口尚未启动（即用户未保存就关窗），退出应用
    if (!getMainWindow()) {
      app.quit()
    }
  })
}

/** 启动主窗口及所有桌面功能 */
function startMainWindow(): void {
  createMainWindow()
  setupMenu()
  setupTray()
  registerGlobalShortcuts()
  initAutoUpdater()
}
