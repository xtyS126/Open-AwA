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
import { setupTray } from './tray'
import { registerGlobalShortcuts, unregisterAllShortcuts } from './shortcuts'
import { initAutoUpdater } from './updater'
import { getBackendUrl } from '../shared/config-store'

// 配置日志
log.transports.file.level = 'info'
log.transports.console.level = 'info'
log.transports.file.resolvePathFn = () => path.join(app.getPath('userData'), 'logs', 'main.log')

// 全局异常处理
process.on('uncaughtException', (error) => {
  log.error('uncaughtException:', error)
  dialog.showErrorBox('应用错误', `发生未预期错误：\n${error.message}\n\n应用将退出。`)
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

// 退出时注销全局快捷键
app.on('will-quit', () => {
  unregisterAllShortcuts()
})

/** 显示引导窗口 */
function showOnboardingWindow(): void {
  const onboardingWin = new BrowserWindow({
    width: 480,
    height: 400,
    resizable: false,
    minimizable: false,
    maximizable: false,
    show: false,
    webPreferences: {
      contextIsolation: false,
      nodeIntegration: true,
    },
  })

  onboardingWin.loadFile(path.join(__dirname, '..', '..', 'resources', 'onboarding.html'))
  onboardingWin.once('ready-to-show', () => {
    onboardingWin.show()
  })

  // 监听后端 URL 设置成功事件（由 backend.ts 的 handleSetUrl 发送）
  ipcMain.once('backend:url-saved', () => {
    onboardingWin.close()
    startMainWindow()
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
