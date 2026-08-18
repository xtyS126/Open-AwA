/**
 * IPC 处理器注册入口
 * 集中注册所有主进程 IPC 处理器
 */
import { registerBackendIpcHandlers } from './backend'
import { registerWindowIpcHandlers } from './window'
import { registerAppIpcHandlers } from './app'
import { registerNotificationIpcHandlers } from './notification'
import { registerAutostartIpcHandlers } from './autostart'
import { registerUpdateIpcHandlers } from './update'
import { registerVoiceIpcHandlers } from './voice'
import { registerPetIpcHandlers } from './pet'
import { registerFsIpcHandlers } from './fs'
import { registerShellIpcHandlers } from './shell'
import { registerDialogIpcHandlers } from './dialog'
import { registerClipboardIpcHandlers } from './clipboard'
import { registerCompanionIpcHandlers } from './companion'

export function registerAllIpcHandlers(): void {
  registerBackendIpcHandlers()
  registerWindowIpcHandlers()
  registerAppIpcHandlers()
  registerNotificationIpcHandlers()
  registerAutostartIpcHandlers()
  registerUpdateIpcHandlers()
  registerVoiceIpcHandlers()
  registerPetIpcHandlers()
  registerFsIpcHandlers()
  registerShellIpcHandlers()
  registerDialogIpcHandlers()
  registerClipboardIpcHandlers()
  registerCompanionIpcHandlers()
}