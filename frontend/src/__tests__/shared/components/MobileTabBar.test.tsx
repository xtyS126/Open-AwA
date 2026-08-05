import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { MobileTabBar } from '@/shared/components/MobileTabBar/MobileTabBar'
import { RouterTestProvider as MemoryRouter } from '@/shared/routing/testing'
import { useI18nStore } from '@/i18n'
import { resetMobileNavForTests, useMobileNavStore } from '@/shared/store/mobileNavStore'

/**
 * 安装 matchMedia mock：根据传入视口宽度解析 min-width / max-width 判定 matches。
 * 注意：useBreakpoint 在 matchMedia 缺失时默认最小断点（isMobile=true），
 * 因此模拟桌面视口必须显式安装匹配 min-width: 1024px 的 mock。
 */
function installViewport(width: number): void {
  const matchMedia = vi.fn((query: string) => {
    const minWidthMatch = query.match(/min-width:\s*(\d+(?:\.\d+)?)/)
    const maxWidthMatch = query.match(/max-width:\s*(\d+(?:\.\d+)?)/)
    const minWidth = minWidthMatch ? parseFloat(minWidthMatch[1]) : null
    const maxWidth = maxWidthMatch ? parseFloat(maxWidthMatch[1]) : null
    let matches = true
    if (minWidth !== null) matches = matches && width >= minWidth
    if (maxWidth !== null) matches = matches && width <= maxWidth
    return {
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }
  })

  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: matchMedia,
  })
}

describe('MobileTabBar', () => {
  beforeEach(() => {
    useI18nStore.getState().setLocale('zh-CN')
    resetMobileNavForTests()
    // 默认模拟 390px 手机视口
    installViewport(390)
  })

  afterEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: undefined,
    })
  })

  it('移动端渲染四个直达 Tab 与更多入口', () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <MobileTabBar />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: /聊天/ })).toHaveAttribute('href', '/chat')
    expect(screen.getByRole('link', { name: /记忆/ })).toHaveAttribute('href', '/memory')
    expect(screen.getByRole('link', { name: /技能/ })).toHaveAttribute('href', '/skills')
    expect(screen.getByRole('link', { name: /设置/ })).toHaveAttribute('href', '/settings')
    expect(screen.getByTestId('tab-more')).toBeInTheDocument()
  })

  it('聊天子路由 /chat/:id 时聊天 Tab 保持激活态', () => {
    render(
      <MemoryRouter initialEntries={['/chat/abc-123']}>
        <MobileTabBar />
      </MemoryRouter>,
    )

    const chatTab = screen.getByRole('link', { name: /聊天/ })
    expect(chatTab).toHaveAttribute('aria-current', 'page')
    const memoryTab = screen.getByRole('link', { name: /记忆/ })
    expect(memoryTab).not.toHaveAttribute('aria-current')
  })

  it('点击"更多"打开移动端抽屉开关', () => {
    render(
      <MemoryRouter initialEntries={['/memory']}>
        <MobileTabBar />
      </MemoryRouter>,
    )

    const moreBtn = screen.getByTestId('tab-more')
    fireEvent.click(moreBtn)
    expect(useMobileNavStore.getState().drawerOpen).toBe(true)

    // 抽屉开关重置后关闭
    resetMobileNavForTests()
    expect(useMobileNavStore.getState().drawerOpen).toBe(false)
  })

  it('桌面视口（≥1024px）不渲染', () => {
    // 桌面视口：min-width: 1024px 命中 → isDesktop=true → isMobile=false
    installViewport(1440)

    const { container } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <MobileTabBar />
      </MemoryRouter>,
    )

    expect(container.querySelector('nav')).toBeNull()
  })
})
