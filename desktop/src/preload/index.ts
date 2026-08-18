/**
 * 预加载脚本
 * 通过 contextBridge 暴露白名单 API 给渲染进程
 * 严格隔离：不暴露 ipcRenderer 原始对象
 *
 * 注意：本脚本在 sandbox: true 下运行，禁止 import 任何依赖 Node.js 内建模块
 * （fs/path/child_process 等）或依赖它们的第三方包（如 electron-store），
 * 也禁止 import 相对路径模块（sandbox preload 的 require 仅支持受限的内建模块）。
 * 因此所有 IPC 通道名在此文件内联为字符串字面量，不得 import ../shared/*。
 */
import { contextBridge, ipcRenderer } from 'electron'

/** 允许渲染进程调用的 IPC 通道白名单（内联字符串，避免 sandbox 下相对路径 require 失败） */
const ALLOWED_INVOKE_CHANNELS = new Set<string>([
  'backend:get-url',
  'backend:set-url',
  'backend:test-connection',
  'window:minimize',
  'window:maximize',
  'window:close',
  'window:is-maximized',
  'notification:show',
  'app:get-version',
  'app:get-platform',
  'app:is-desktop',
  'update:check',
  'update:download',
  'update:install-and-restart',
  'autostart:get',
  'autostart:set',
  'companion:notify',
  'voice:start-listening',
  'voice:stop-listening',
  'voice:permission-request',
  'voice:audio-chunk',
  'fs:open-file',
  'fs:save-file',
  'fs:read-file',
  'fs:write-file',
  'shell:open-external',
  'shell:show-item',
  'dialog:message',
  'dialog:confirm',
  'dialog:error',
  'clipboard:read',
  'clipboard:write',
  'pet:show',
  'pet:hide',
  'pet:toggle',
  'pet:set-position',
  'pet:play-animation',
  'pet:set-expression',
  'pet:get-config',
  'pet:set-config',
])

/** 允许渲染进程监听的 IPC 通道白名单 */
const ALLOWED_ON_CHANNELS = new Set<string>([
  'backend:url-changed',
  'notification:clicked',
  'update:status-changed',
  'action:new-chat',
  'window:maximize-state-changed',
  'companion:notify-clicked',
  'pet:clicked',
])

/** 应用版本（sandbox 下 app 模块不可用，使用固定值，版本由主进程 app:get-version 提供） */
const appVersion = '1.0.0'
// process.defaultApp 在未打包（dev）时为 true；打包后为 undefined，据此判断 isPackaged
const isPackaged = process.defaultApp === undefined

// 注入后端信息：url 留空，由渲染进程通过 backend:get-url 拉取
// 这样可避免 preload 顶层读取 electron-store 导致 sandbox 下崩溃
contextBridge.exposeInMainWorld('__OPENAWA_BACKEND__', {
  url: '',
  version: appVersion,
})

// 注入桌面端 API
contextBridge.exposeInMainWorld('__OPENAWA_DESKTOP__', {
  platform: process.platform,
  isPackaged,
  ipc: {
    /** 调用主进程 IPC（白名单校验） */
    invoke: (channel: string, ...args: unknown[]): Promise<unknown> => {
      if (!ALLOWED_INVOKE_CHANNELS.has(channel)) {
        return Promise.reject(new Error(`IPC 通道未授权: ${channel}`))
      }
      return ipcRenderer.invoke(channel, ...args)
    },
    /** 监听主进程事件（白名单校验） */
    on: (channel: string, listener: (...args: unknown[]) => void): (() => void) => {
      if (!ALLOWED_ON_CHANNELS.has(channel)) {
        throw new Error(`IPC 监听通道未授权: ${channel}`)
      }
      const handler = (_event: Electron.IpcRendererEvent, ...args: unknown[]): void => {
        listener(...args)
      }
      ipcRenderer.on(channel, handler)
      return () => {
        ipcRenderer.removeListener(channel, handler)
      }
    },
  },
})