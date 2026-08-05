import { create } from 'zustand'

/**
 * 移动端导航状态：底部 Tab Bar 的"更多"入口与 Sidebar 抽屉共享同一开关。
 *
 * 桌面端使用 Sidebar 自身 local state 即可；移动端底部 Tab Bar（MobileTabBar）
 * 需要从组件外部打开抽屉，因此把开关提升到全局 store，Sidebar 与 Tab Bar 双向同步。
 */
interface MobileNavState {
  /** 移动端抽屉是否打开 */
  drawerOpen: boolean
  openDrawer: () => void
  closeDrawer: () => void
  toggleDrawer: () => void
}

export const useMobileNavStore = create<MobileNavState>((set) => ({
  drawerOpen: false,
  openDrawer: () => set({ drawerOpen: true }),
  closeDrawer: () => set({ drawerOpen: false }),
  toggleDrawer: () => set((state) => ({ drawerOpen: !state.drawerOpen })),
}))

/**
 * 仅供测试重置模块级单例状态，避免跨用例污染。
 */
export function resetMobileNavForTests() {
  useMobileNavStore.setState({ drawerOpen: false })
}
