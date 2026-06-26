/**
 * 引导窗口预加载脚本
 * 仅暴露引导窗口所需的最小 API：测试连接、保存后端 URL
 * 不暴露 ipcRenderer 原始对象，符合最小权限原则
 */
import { contextBridge, ipcRenderer } from 'electron'
import { IPC_CHANNELS } from '../shared/ipc-channels'

/** 引导窗口允许调用的 IPC 通道白名单 */
const ALLOWED_CHANNELS = new Set<string>([
  IPC_CHANNELS.BACKEND_TEST_CONNECTION,
  IPC_CHANNELS.BACKEND_SET_URL,
])

contextBridge.exposeInMainWorld('__OPENAWA_ONBOARDING__', {
  /** 测试后端连通性 */
  testConnection: (url: string): Promise<unknown> => {
    if (!ALLOWED_CHANNELS.has(IPC_CHANNELS.BACKEND_TEST_CONNECTION)) {
      return Promise.reject(new Error('IPC 通道未授权'))
    }
    return ipcRenderer.invoke(IPC_CHANNELS.BACKEND_TEST_CONNECTION, { url })
  },
  /** 保存后端 URL */
  setUrl: (url: string): Promise<unknown> => {
    if (!ALLOWED_CHANNELS.has(IPC_CHANNELS.BACKEND_SET_URL)) {
      return Promise.reject(new Error('IPC 通道未授权'))
    }
    return ipcRenderer.invoke(IPC_CHANNELS.BACKEND_SET_URL, { url })
  },
})
