import { describe, it, expect, vi } from 'vitest'

// mock electron-store 在 setup.ts 中已定义
describe('窗口管理', () => {
  it('createMainWindow 返回 BrowserWindow 实例', async () => {
    const { createMainWindow } = await import('../src/main/window')
    const win = createMainWindow()
    expect(win).toBeDefined()
    expect(win.loadURL).toBeDefined()
    expect(win.loadFile).toBeDefined()
  })

  it('开发模式加载 dev server URL', async () => {
    process.env.OPENAWA_FRONTEND_URL = 'http://localhost:5173'
    const { createMainWindow } = await import('../src/main/window')
    const win = createMainWindow()
    expect(win.loadURL).toBeDefined()
    delete process.env.OPENAWA_FRONTEND_URL
  })

  it('attachWindowEventBridge 注册最大化/关闭/closed 事件监听器', async () => {
    const { attachWindowEventBridge } = await import('../src/main/window')
    const win = {
      on: vi.fn(),
      once: vi.fn(),
      webContents: { on: vi.fn() },
    }
    attachWindowEventBridge(win as unknown as Electron.BrowserWindow)
    // maximize、unmaximize、close、closed 共 4 个 on 事件
    expect(win.on).toHaveBeenCalledWith('maximize', expect.any(Function))
    expect(win.on).toHaveBeenCalledWith('unmaximize', expect.any(Function))
    expect(win.on).toHaveBeenCalledWith('close', expect.any(Function))
    expect(win.on).toHaveBeenCalledWith('closed', expect.any(Function))
    // ready-to-show 通过 once 注册
    expect(win.once).toHaveBeenCalledWith('ready-to-show', expect.any(Function))
    // render-process-gone 通过 webContents.on 注册
    expect(win.webContents.on).toHaveBeenCalledWith('render-process-gone', expect.any(Function))
  })
})
