/**
 * IPC 通道名常量集中定义
 * 格式：<域>:<动作>
 * 所有主进程与渲染进程通信必须使用此处定义的通道名
 */

export const IPC_CHANNELS = {
  // 后端地址管理
  BACKEND_GET_URL: 'backend:get-url',
  BACKEND_SET_URL: 'backend:set-url',
  BACKEND_TEST_CONNECTION: 'backend:test-connection',
  BACKEND_URL_CHANGED: 'backend:url-changed',

  // 窗口控制
  WINDOW_MINIMIZE: 'window:minimize',
  WINDOW_MAXIMIZE: 'window:maximize',
  WINDOW_CLOSE: 'window:close',
  WINDOW_IS_MAXIMIZED: 'window:is-maximized',
  WINDOW_MAXIMIZE_STATE_CHANGED: 'window:maximize-state-changed',

  // 系统通知
  NOTIFICATION_SHOW: 'notification:show',
  NOTIFICATION_CLICKED: 'notification:clicked',

  // 应用信息
  APP_GET_VERSION: 'app:get-version',
  APP_GET_PLATFORM: 'app:get-platform',

  // 自动更新
  UPDATE_CHECK: 'update:check',
  UPDATE_DOWNLOAD: 'update:download',
  UPDATE_INSTALL_AND_RESTART: 'update:install-and-restart',
  UPDATE_STATUS_CHANGED: 'update:status-changed',

  // 动作（全局快捷键/托盘菜单触发）
  ACTION_NEW_CHAT: 'action:new-chat',

  // 开机自启
  AUTOSTART_GET: 'autostart:get',
  AUTOSTART_SET: 'autostart:set',
} as const

/** IPC 通道名类型 */
export type IpcChannel = typeof IPC_CHANNELS[keyof typeof IPC_CHANNELS]
