/**
 * 全局快捷键注册
 */
import { globalShortcut } from 'electron'
import log from 'electron-log'
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

/**
 * 注册单个快捷键，检查返回值
 * - 注册成功才 push 到 registeredAccelerators
 * - 失败时记录 warning（可能被其他应用占用）
 */
function registerOne(accelerator: string, callback: () => void): void {
  const ok = globalShortcut.register(accelerator, callback)
  if (ok) {
    registeredAccelerators.push(accelerator)
  } else {
    log.warn(`全局快捷键注册失败（可能被其他应用占用）: ${accelerator}`)
  }
}

/** 注册全局快捷键 */
export function registerGlobalShortcuts(): void {
  // Ctrl+Shift+O：显示并聚焦主窗口
  registerOne('CommandOrControl+Shift+O', () => {
    showAndFocusMainWindow()
  })

  // Ctrl+Shift+N：显示主窗口并新建会话
  registerOne('CommandOrControl+Shift+N', () => {
    showAndFocusMainWindow()
    const win = getMainWindow()
    win?.webContents.send(IPC_CHANNELS.ACTION_NEW_CHAT)
  })
}

/** 注销所有全局快捷键 */
export function unregisterAllShortcuts(): void {
  for (const accelerator of registeredAccelerators) {
    globalShortcut.unregister(accelerator)
  }
  registeredAccelerators.length = 0
}
