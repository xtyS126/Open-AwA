/**
 * 系统托盘设置
 */
import { Tray, Menu, nativeImage, app } from 'electron'
import path from 'node:path'
import fs from 'node:fs'
import log from 'electron-log'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getMainWindow } from './window'

/** 托盘实例 */
let tray: Tray | null = null

/** 创建托盘图标（路径不存在时回退空图标并记录 warning，不再静默） */
function createTrayIcon(): Electron.NativeImage {
  const iconPath = path.join(__dirname, '..', '..', 'resources', 'icons', 'tray.png')
  if (!fs.existsSync(iconPath)) {
    // 图标资源缺失时记录 warning，便于用户/开发者发现
    // 不抛错以保证应用可用，回退到空图标
    log.warn(`托盘图标不存在: ${iconPath}，回退到空图标。请放置图标资源以正常显示托盘。`)
    return nativeImage.createEmpty()
  }
  return nativeImage.createFromPath(iconPath)
}

/** 设置系统托盘 */
export function setupTray(): void {
  // 防止重复创建托盘
  if (tray) {
    return
  }
  const icon = createTrayIcon()
  tray = new Tray(icon)
  tray.setToolTip('Open-AwA')

  // 右键菜单
  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click: () => {
        const win = getMainWindow()
        if (win) {
          if (win.isMinimized()) win.restore()
          win.show()
          win.focus()
        }
      },
    },
    {
      label: '新建会话',
      click: () => {
        const win = getMainWindow()
        if (win) {
          if (win.isMinimized()) win.restore()
          win.show()
          win.focus()
          win.webContents.send(IPC_CHANNELS.ACTION_NEW_CHAT)
        }
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => app.quit(),
    },
  ])

  tray.setContextMenu(contextMenu)

  // 双击托盘图标：显示/隐藏主窗口
  tray.on('double-click', () => {
    const win = getMainWindow()
    if (!win) return
    if (win.isVisible() && win.isFocused()) {
      win.hide()
    } else {
      if (win.isMinimized()) win.restore()
      win.show()
      win.focus()
    }
  })
}

/** 获取托盘实例 */
export function getTray(): Tray | null {
  return tray
}

/** 销毁托盘（在 will-quit 中调用，避免 Windows 退出后图标残留） */
export function destroyTray(): void {
  if (tray) {
    tray.destroy()
    tray = null
  }
}
