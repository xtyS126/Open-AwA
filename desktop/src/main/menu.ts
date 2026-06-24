/**
 * 原生菜单设置
 */
import { Menu, app } from 'electron'
import { IPC_CHANNELS } from '../shared/ipc-channels'
import { getMainWindow } from './window'

/** 构建菜单模板 */
function buildMenuTemplate(): Electron.MenuItemConstructorOptions[] {
  const isDev = !app.isPackaged

  return [
    {
      label: '文件',
      submenu: [
        {
          label: '新建会话',
          accelerator: 'CmdOrCtrl+N',
          click: () => {
            const win = getMainWindow()
            win?.webContents.send(IPC_CHANNELS.ACTION_NEW_CHAT)
          },
        },
        { type: 'separator' },
        {
          label: '退出',
          accelerator: 'CmdOrCtrl+Q',
          click: () => app.quit(),
        },
      ],
    },
    {
      label: '编辑',
      submenu: [
        { label: '撤销', role: 'undo', accelerator: 'CmdOrCtrl+Z' },
        { label: '重做', role: 'redo', accelerator: 'CmdOrCtrl+Shift+Z' },
        { type: 'separator' },
        { label: '复制', role: 'copy', accelerator: 'CmdOrCtrl+C' },
        { label: '粘贴', role: 'paste', accelerator: 'CmdOrCtrl+V' },
        { label: '全选', role: 'selectAll', accelerator: 'CmdOrCtrl+A' },
      ],
    },
    {
      label: '视图',
      submenu: [
        { label: '放大', role: 'zoomIn', accelerator: 'CmdOrCtrl+=' },
        { label: '缩小', role: 'zoomOut', accelerator: 'CmdOrCtrl+-' },
        { label: '重置缩放', role: 'resetZoom', accelerator: 'CmdOrCtrl+0' },
        { type: 'separator' },
        { label: '全屏', role: 'togglefullscreen', accelerator: 'F11' },
        { type: 'separator' },
        { label: '刷新', role: 'reload', accelerator: 'CmdOrCtrl+R' },
        { label: '强制刷新', role: 'forceReload', accelerator: 'CmdOrCtrl+Shift+R' },
      ],
    },
    {
      label: '窗口',
      submenu: [
        { label: '最小化', role: 'minimize' },
        { label: '关闭', role: 'close' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '关于',
          click: () => {
            const win = getMainWindow()
            // 可扩展为打开关于对话框
            win?.webContents.send(IPC_CHANNELS.ACTION_NEW_CHAT)
          },
        },
        {
          label: '检查更新',
          click: () => {
            const win = getMainWindow()
            win?.webContents.send(IPC_CHANNELS.UPDATE_STATUS_CHANGED, { status: 'checking' })
          },
        },
        ...(isDev ? [
          { type: 'separator' as const },
          {
            label: '开发者工具',
            accelerator: 'F12',
            click: () => {
              const win = getMainWindow()
              win?.webContents.toggleDevTools()
            },
          },
        ] : []),
      ],
    },
  ]
}

/** 设置应用菜单 */
export function setupMenu(): void {
  const template = buildMenuTemplate()
  const menu = Menu.buildFromTemplate(template)
  Menu.setApplicationMenu(menu)
}
