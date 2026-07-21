/**
 * 测试 setup：mock electron 模块
 */
import { vi } from 'vitest'

// mock electron 模块
vi.mock('electron', () => {
  // 创建 BrowserWindow 实例 mock，包含窗口管理所需的方法
  const createBrowserWindowInstance = () => ({
    loadURL: vi.fn(),
    loadFile: vi.fn(),
    on: vi.fn(),
    once: vi.fn(),
    off: vi.fn(),
    show: vi.fn(),
    close: vi.fn(),
    destroy: vi.fn(),
    minimize: vi.fn(),
    maximize: vi.fn(),
    unmaximize: vi.fn(),
    restore: vi.fn(),
    focus: vi.fn(),
    hide: vi.fn(),
    isMinimized: vi.fn(() => false),
    isMaximized: vi.fn(() => false),
    isFocused: vi.fn(() => false),
    isVisible: vi.fn(() => true),
    isDestroyed: vi.fn(() => false),
    getPosition: vi.fn(() => [0, 0]),
    getSize: vi.fn(() => [1280, 800]),
    setBounds: vi.fn(),
    getBounds: vi.fn(() => ({ x: 0, y: 0, width: 1280, height: 800 })),
    setMinimumSize: vi.fn(),
    setMaximumSize: vi.fn(),
    setBackgroundColor: vi.fn(),
    reload: vi.fn(),
    webContents: {
      openDevTools: vi.fn(),
      closeDevTools: vi.fn(),
      send: vi.fn(),
      on: vi.fn(),
      once: vi.fn(),
      off: vi.fn(),
    },
  })

  const BrowserWindow = vi.fn(() => createBrowserWindowInstance())
  // 静态方法
  ;(BrowserWindow as unknown as { getAllWindows: () => unknown[] }).getAllWindows = vi.fn(() => [])
  ;(BrowserWindow as unknown as { fromWebContents: () => null }).fromWebContents = vi.fn(() => null)
  ;(BrowserWindow as unknown as { getFocusedWindow: () => null }).getFocusedWindow = vi.fn(() => null)

  return {
    app: {
      isPackaged: false,
      getPath: vi.fn((name: string) => `/tmp/openawa-test/${name}`),
      getVersion: vi.fn(() => '1.0.0-test'),
      whenReady: vi.fn(() => Promise.resolve()),
      quit: vi.fn(),
      exit: vi.fn(),
      requestSingleInstanceLock: vi.fn(() => true),
      on: vi.fn(),
      off: vi.fn(),
      once: vi.fn(),
      setLoginItemSettings: vi.fn(),
      showAboutPanel: vi.fn(),
    },
    BrowserWindow,
    ipcMain: {
      handle: vi.fn(),
      on: vi.fn(),
      off: vi.fn(),
      once: vi.fn(),
      emit: vi.fn(),
      removeHandler: vi.fn(),
    },
    ipcRenderer: {
      invoke: vi.fn(),
      on: vi.fn(),
      off: vi.fn(),
      removeListener: vi.fn(),
    },
    contextBridge: {
      exposeInMainWorld: vi.fn(),
    },
    nativeTheme: {
      themeSource: 'system',
      on: vi.fn(),
      off: vi.fn(),
    },
    // Notification 构造函数 + 静态方法 isSupported
    Notification: (() => {
      const N = vi.fn()
      ;(N as unknown as { isSupported: () => boolean }).isSupported = vi.fn(() => true)
      return N
    })(),
    globalShortcut: {
      register: vi.fn(),
      unregister: vi.fn(),
      unregisterAll: vi.fn(),
      isRegistered: vi.fn(() => false),
    },
    Tray: vi.fn(() => ({
      setToolTip: vi.fn(),
      setContextMenu: vi.fn(),
      on: vi.fn(),
      destroy: vi.fn(),
    })),
    nativeImage: {
      createFromPath: vi.fn(() => ({})),
      createEmpty: vi.fn(() => ({})),
    },
    Menu: {
      buildFromTemplate: vi.fn(),
      setApplicationMenu: vi.fn(),
    },
    shell: {
      openExternal: vi.fn(),
    },
  }
})

// mock electron-store
// 模拟真实 electron-store 行为：支持构造函数 defaults 选项与点号路径访问嵌套属性
vi.mock('electron-store', () => {
  // 内部扁平存储
  const store = new Map<string, unknown>()
  // 构造函数传入的默认配置
  let defaults: Record<string, unknown> = {}

  // 按点号路径从对象中取嵌套属性
  const getByPath = (obj: unknown, path: string): unknown => {
    const parts = path.split('.')
    let current: unknown = obj
    for (const part of parts) {
      if (current === null || current === undefined) {
        return undefined
      }
      current = (current as Record<string, unknown>)[part]
    }
    return current
  }

  return {
    default: class {
      constructor(options?: { defaults?: Record<string, unknown> }) {
        if (options?.defaults) {
          defaults = options.defaults
        }
      }
      get(key: string, defaultValue?: unknown) {
        if (store.has(key)) return store.get(key)
        // 尝试从 defaults 中按点号路径查找
        const fromDefaults = getByPath(defaults, key)
        if (fromDefaults !== undefined) return fromDefaults
        return defaultValue
      }
      set(key: string, value: unknown) {
        store.set(key, value)
      }
      delete(key: string) {
        store.delete(key)
      }
      clear() {
        store.clear()
      }
      has(key: string) {
        return store.has(key)
      }
      get store() {
        return Object.fromEntries(store)
      }
      set store(value) {
        store.clear()
        for (const [k, v] of Object.entries(value)) {
          store.set(k, v)
        }
      }
    },
  }
})

// mock electron-log（主进程日志）
vi.mock('electron-log', () => {
  const log = {
    transports: {
      file: { level: 'info', resolvePathFn: () => '/tmp/openawa-test/main.log' },
      console: { level: 'info' },
    },
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  }
  return { default: log }
})

// mock electron-updater（自动更新）
vi.mock('electron-updater', () => ({
  autoUpdater: {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    setFeedURL: vi.fn(),
    on: vi.fn(),
    checkForUpdates: vi.fn(() => Promise.resolve()),
    downloadUpdate: vi.fn(() => Promise.resolve()),
    quitAndInstall: vi.fn(),
  },
}))

// mock fs.existsSync（tray.ts 检查图标是否存在）
// 默认返回 false 走空图标回退路径，测试不需要真实图标文件
vi.mock('node:fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs')>()
  return {
    ...actual,
    existsSync: vi.fn(() => false),
  }
})
