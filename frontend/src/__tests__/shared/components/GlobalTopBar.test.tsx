import '@testing-library/jest-dom/vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from '@/layouts/AppShell'
import GlobalTopBar from '@/shared/components/GlobalTopBar/GlobalTopBar'
import { UserFloatingArea } from '@/shared/components/UserFloatingArea'
import { useAuthStore } from '@/shared/store/authStore'
import { renderWithRouter } from '@/shared/routing/testing'

vi.mock('@/shared/api/api', () => ({
  authAPI: { logout: vi.fn().mockResolvedValue({}) },
}))

vi.mock('@/shared/components/Sidebar/Sidebar', () => ({
  default: () => <aside data-testid="sidebar" />,
}))

vi.mock('@/shared/components/MobileTabBar/MobileTabBar', () => ({
  default: () => <nav data-testid="mobile-tab-bar" />,
}))

vi.mock('@/shared/components/IssueFeedbackPanel/IssueFeedbackPanel', () => ({
  default: () => <div data-testid="issue-feedback-panel" />,
}))

describe('GlobalTopBar', () => {
  beforeEach(() => {
    useAuthStore.setState({
      isInitialized: true,
      isAuthenticated: true,
      isSystemInitialized: true,
      needsServerSelection: false,
      user: { id: 1, username: 'tester', is_active: true, is_superuser: false },
    })
  })

  it('展示全局搜索、系统就绪状态和账户菜单', async () => {
    renderWithRouter(<GlobalTopBar />, { initialEntry: '/assistant' })

    expect(await screen.findByRole('button', { name: '前往 Open-AwA 助手' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '打开全局搜索' })).toBeInTheDocument()
    expect(screen.getByText('Ctrl K')).toBeInTheDocument()
    expect(screen.getByLabelText('系统状态：系统已就绪')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '打开账户菜单' })).toBeInTheDocument()
  })

  it('系统尚未初始化时不伪装为连接健康状态', async () => {
    useAuthStore.setState({ isSystemInitialized: false })
    renderWithRouter(<GlobalTopBar />, { initialEntry: '/assistant' })

    expect(await screen.findByLabelText('系统状态：系统未初始化')).toHaveTextContent('系统未初始化')
    expect(screen.queryByText('已连接')).not.toBeInTheDocument()
  })

  it('品牌入口使用软晶标记并返回助手工作域', async () => {
    const { router } = renderWithRouter(<GlobalTopBar />, { initialEntry: '/workbench/projects' })

    const brandEntry = await screen.findByRole('button', { name: '前往 Open-AwA 助手' })
    expect(brandEntry.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    fireEvent.click(brandEntry)

    await waitFor(() => {
      expect(router.state.location.href).toBe('/assistant')
    })
  })

  it('按 Ctrl+K 打开命令面板并可跳转到设置', async () => {
    const { router } = renderWithRouter(<GlobalTopBar />, { initialEntry: '/assistant' })

    await screen.findByRole('button', { name: '打开全局搜索' })
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    const dialog = await screen.findByRole('dialog', { name: '全局搜索' })
    fireEvent.change(screen.getByRole('combobox', { name: '搜索页面与功能' }), {
      target: { value: '设置' },
    })
    fireEvent.click(screen.getByRole('option', { name: '设置' }))

    await waitFor(() => {
      expect(router.state.location.href).toBe('/settings/general')
    })
    expect(dialog).not.toBeInTheDocument()
  })

  it('按 Meta+K 也能打开命令面板', async () => {
    renderWithRouter(<GlobalTopBar />, { initialEntry: '/assistant' })

    await screen.findByRole('button', { name: '打开全局搜索' })
    fireEvent.keyDown(window, { key: 'k', metaKey: true })

    expect(await screen.findByRole('dialog', { name: '全局搜索' })).toBeInTheDocument()
  })

  it('仅在非输入上下文响应斜杠快捷键', async () => {
    renderWithRouter(<GlobalTopBar />, { initialEntry: '/assistant' })

    await screen.findByRole('button', { name: '打开全局搜索' })
    const externalInput = document.createElement('input')
    document.body.appendChild(externalInput)
    externalInput.focus()
    fireEvent.keyDown(externalInput, { key: '/' })
    expect(screen.queryByRole('dialog', { name: '全局搜索' })).not.toBeInTheDocument()

    externalInput.blur()
    fireEvent.keyDown(window, { key: '/' })
    externalInput.remove()
    expect(await screen.findByRole('dialog', { name: '全局搜索' })).toBeInTheDocument()
  })

  it('支持方向键选择、Enter 激活、Esc 关闭并恢复触发元素焦点', async () => {
    const { router } = renderWithRouter(<GlobalTopBar />, { initialEntry: '/workbench/projects' })

    const brandEntry = await screen.findByRole('button', { name: '前往 Open-AwA 助手' })
    brandEntry.focus()
    fireEvent.keyDown(brandEntry, { key: '/' })
    const searchbox = await screen.findByRole('combobox', { name: '搜索页面与功能' })
    const options = screen.getAllByRole('option')
    expect(options[0]).toHaveAttribute('aria-selected', 'true')

    fireEvent.keyDown(searchbox, { key: 'ArrowDown' })
    expect(options[1]).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(searchbox, { key: 'ArrowUp' })
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(searchbox, { key: 'Escape' })

    await waitFor(() => {
      expect(brandEntry).toHaveFocus()
    })

    fireEvent.keyDown(brandEntry, { key: '/', code: 'Slash' })
    const reopenedSearchbox = await screen.findByRole('combobox', { name: '搜索页面与功能' })
    fireEvent.keyDown(reopenedSearchbox, { key: 'Enter' })

    await waitFor(() => {
      expect(router.state.location.href).toBe('/assistant')
    })
    expect(screen.queryByRole('dialog', { name: '全局搜索' })).not.toBeInTheDocument()
    await waitFor(() => {
      expect(brandEntry).toHaveFocus()
    })
  })

  it('搜索对话框用 Tab 和 Shift+Tab 圈闭焦点', async () => {
    renderWithRouter(<GlobalTopBar />, { initialEntry: '/assistant' })

    fireEvent.click(await screen.findByRole('button', { name: '打开全局搜索' }))
    const dialog = await screen.findByRole('dialog', { name: '全局搜索' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    const searchbox = await screen.findByRole('combobox', { name: '搜索页面与功能' })
    const closeButton = screen.getByRole('button', { name: '关闭全局搜索' })
    await waitFor(() => {
      expect(searchbox).toHaveFocus()
    })

    fireEvent.keyDown(searchbox, { key: 'Tab', shiftKey: true })
    expect(closeButton).toHaveFocus()
    fireEvent.keyDown(closeButton, { key: 'Tab' })
    expect(searchbox).toHaveFocus()
  })

  it('头像菜单提供账户、设置和切换服务器入口', async () => {
    renderWithRouter(<GlobalTopBar />, { initialEntry: '/assistant' })

    fireEvent.click(await screen.findByRole('button', { name: '打开账户菜单' }))

    expect(await screen.findByRole('menuitem', { name: '账户' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '设置' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '切换服务器' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '问题反馈' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '退出登录' })).toBeInTheDocument()
  })

  it('账户触发器公开菜单关系并在打开时聚焦首项', async () => {
    renderWithRouter(<GlobalTopBar />, { initialEntry: '/assistant' })

    const trigger = await screen.findByRole('button', { name: '打开账户菜单' })
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu')
    expect(trigger).toHaveAttribute('aria-controls', 'global-account-menu')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    fireEvent.keyDown(trigger, { key: 'ArrowDown' })
    const menu = await screen.findByRole('menu')
    expect(menu).toHaveAttribute('id', 'global-account-menu')
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    await waitFor(() => {
      expect(screen.getByRole('menuitem', { name: '账户' })).toHaveFocus()
    })
  })

  it('账户菜单支持循环方向键、首尾键和 Escape 焦点恢复', async () => {
    renderWithRouter(<GlobalTopBar />, { initialEntry: '/assistant' })

    const trigger = await screen.findByRole('button', { name: '打开账户菜单' })
    fireEvent.click(trigger)
    const menu = await screen.findByRole('menu')
    const accountItem = screen.getByRole('menuitem', { name: '账户' })
    const settingsItem = screen.getByRole('menuitem', { name: '设置' })
    const logoutItem = screen.getByRole('menuitem', { name: '退出登录' })
    accountItem.focus()

    fireEvent.keyDown(menu, { key: 'ArrowDown' })
    expect(settingsItem).toHaveFocus()
    fireEvent.keyDown(menu, { key: 'ArrowUp' })
    expect(accountItem).toHaveFocus()
    fireEvent.keyDown(menu, { key: 'ArrowUp' })
    expect(logoutItem).toHaveFocus()
    fireEvent.keyDown(menu, { key: 'Home' })
    expect(accountItem).toHaveFocus()
    fireEvent.keyDown(menu, { key: 'End' })
    expect(logoutItem).toHaveFocus()
    fireEvent.keyDown(menu, { key: 'Escape' })

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    await waitFor(() => {
      expect(trigger).toHaveFocus()
    })
  })

  it('点击账户区域外部会关闭菜单且不抢回外部焦点', async () => {
    renderWithRouter(<GlobalTopBar />, { initialEntry: '/assistant' })

    const trigger = await screen.findByRole('button', { name: '打开账户菜单' })
    fireEvent.click(trigger)
    expect(await screen.findByRole('menu')).toBeInTheDocument()
    const outsideButton = screen.getByRole('button', { name: '打开全局搜索' })
    fireEvent.mouseDown(outsideButton)
    outsideButton.focus()

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    await new Promise((resolve) => window.setTimeout(resolve, 0))
    expect(outsideButton).toHaveFocus()
  })

  it('在已登录壳层中位于主内容上方并共享可收缩工作区', async () => {
    renderWithRouter(<AppShell />, { initialEntry: '/assistant' })

    const topBar = await screen.findByRole('banner')
    const main = screen.getByRole('main')
    const workspace = topBar.closest('.app-workspace')

    expect(workspace).not.toBeNull()
    expect(workspace).toContainElement(main)
  })

  it('旧用户浮动入口直接跳转到账户页', async () => {
    const { router } = renderWithRouter(<UserFloatingArea />, { initialEntry: '/assistant' })

    fireEvent.click(await screen.findByRole('button', { name: '用户中心' }))

    await waitFor(() => {
      expect(router.state.location.href).toBe('/account')
    })
  })
})
