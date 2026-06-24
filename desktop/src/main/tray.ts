/**
 * 系统托盘设置
 */
import { Tray, Menu, nativeImage, app } from 'electron'
import path from 'node:path'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getMinimizeToTray } from '../shared/config-store'
import { getMainWindow } from './window'

/** 托盘实例 */
let tray: Tray | null = null

/** 创建托盘图标（使用占位图标，后续替换） */
function createTrayIcon(): Electron.NativeImage {
  // 使用内置图标或占位图标
  // 实际项目中应替换为 resources/icons/tray.png
  const iconPath = path.join(__dirname, '..', '..', 'resources', 'icons', 'tray.png')
  try {
    return nativeImage.createFromPath(iconPath)
  } catch {
    // 占位：空图标
    return nativeImage.createEmpty()
  }
}

/** 设置系统托盘 */
export function setupTray(): void {
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
