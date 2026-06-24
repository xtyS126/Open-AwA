/**
 * 全局快捷键注册
 */
import { globalShortcut } from 'electron'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getMainWindow } from './window'

/** 已注册的快捷键列表 */
const registeredAccelerators: string[] = []

/** 显示并聚焦主窗口 */
function showAndFocusMainWindow(): void {
  const win = getMainWindow()
  if (!win) return
  if (win.isMinimized()) win.restore()
  win.show()
  win.focus()
}

/** 注册全局快捷键 */
export function registerGlobalShortcuts(): void {
  // Ctrl+Shift+O：显示并聚焦主窗口
  const acceleratorShow = 'CommandOrControl+Shift+O'
  globalShortcut.register(acceleratorShow, () => {
    showAndFocusMainWindow()
  })
  registeredAccelerators.push(acceleratorShow)

  // Ctrl+Shift+N：显示主窗口并新建会话
  const acceleratorNewChat = 'CommandOrControl+Shift+N'
  globalShortcut.register(acceleratorNewChat, () => {
    showAndFocusMainWindow()
    const win = getMainWindow()
    win?.webContents.send(IPC_CHANNELS.ACTION_NEW_CHAT)
  })
  registeredAccelerators.push(acceleratorNewChat)
}

/** 注销所有全局快捷键 */
export function unregisterAllShortcuts(): void {
  for (const accelerator of registeredAccelerators) {
    globalShortcut.unregister(accelerator)
  }
  registeredAccelerators.length = 0
}
