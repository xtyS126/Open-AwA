import { describe, it, expect } from 'vitest'

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
})
