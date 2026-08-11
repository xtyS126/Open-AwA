import '@testing-library/jest-dom/vitest'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Sidebar from '@/shared/components/Sidebar/Sidebar'
import { RouterTestProvider as MemoryRouter } from '@/shared/routing/testing'
import { useI18nStore } from '@/i18n'
import { useIssueFeedbackStore } from '@/shared/store/issueFeedbackStore'

vi.mock('@/shared/api/api', () => ({
  authAPI: { getMe: vi.fn().mockResolvedValue({ data: {} }) },
}))

vi.mock('@/shared/components/UserFloatingArea', () => ({
  UserFloatingArea: () => <div data-testid="sidebar-account-entry" />,
}))

const SIDEBAR_COLLAPSED_STORAGE_KEY = 'openawa.sidebar.subnav-collapsed'
const originalMatchMedia = window.matchMedia

function installMatchMediaWithViewport(width: number) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: vi.fn((query: string) => {
      const minWidthMatch = query.match(/min-width:\s*(\d+(?:\.\d+)?)/)
      const maxWidthMatch = query.match(/max-width:\s*(\d+(?:\.\d+)?)/)
      const minWidth = minWidthMatch ? Number(minWidthMatch[1]) : null
      const maxWidth = maxWidthMatch ? Number(maxWidthMatch[1]) : null
      const matches = (minWidth === null || width >= minWidth)
        && (maxWidth === null || width <= maxWidth)

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
    }),
  })
}

describe('Sidebar 五域投影', () => {
  beforeEach(() => {
    window.localStorage.clear()
    useI18nStore.getState().setLocale('zh-CN')
    useIssueFeedbackStore.setState({
      isOpen: false,
      submitting: false,
      draft: { issue_type: 'bug', title: '', content: '', page_url: '' },
    })
  })

  afterEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: originalMatchMedia,
    })
  })

  it('从统一清单投影五个一级域与当前域子导航', () => {
    render(
      <MemoryRouter initialEntries={['/automations/flows']}>
        <Sidebar />
      </MemoryRouter>,
    )

    const primary = screen.getByRole('navigation', { name: '工作域' })
    expect(within(primary).getAllByRole('link')).toHaveLength(5)
    expect(within(primary).getByRole('link', { name: '自动化' }))
      .toHaveAttribute('aria-current', 'page')

    const secondary = screen.getByRole('navigation', { name: '自动化子导航' })
    expect(within(secondary).getByRole('link', { name: '流程' }))
      .toHaveAttribute('aria-current', 'page')
    expect(within(secondary).getByRole('link', { name: '运行' }))
      .toHaveAttribute('href', '/automations/runs')
  })

  it('账户和设置不出现在五域或领域子导航中', () => {
    render(
      <MemoryRouter initialEntries={['/assistant']}>
        <Sidebar />
      </MemoryRouter>,
    )

    expect(screen.queryByRole('link', { name: '设置' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '账户' })).not.toBeInTheDocument()
  })

  it('账户和设置页不错误选中助手工作域', () => {
    render(
      <MemoryRouter initialEntries={['/settings/general']}>
        <Sidebar />
      </MemoryRouter>,
    )

    const domainNavigation = screen.getByRole('navigation', { name: '工作域' })
    expect(within(domainNavigation).queryByRole('link', { current: 'page' }))
      .not.toBeInTheDocument()
    expect(screen.getByTestId('sidebar')).toHaveAttribute('data-collapsed', 'true')
    expect(screen.queryByRole('navigation', { name: '助手子导航' })).not.toBeInTheDocument()
  })

  it('侧栏不再渲染与顶部头像重复的账户入口', () => {
    render(
      <MemoryRouter initialEntries={['/assistant']}>
        <Sidebar />
      </MemoryRouter>,
    )

    expect(screen.queryByTestId('sidebar-account-entry')).not.toBeInTheDocument()
  })

  it('旧路径在迁移期仍能选中对应工作域', () => {
    render(
      <MemoryRouter initialEntries={['/vibe-coding']}>
        <Sidebar />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: '工作台' }))
      .toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Agents' }))
      .toHaveAttribute('aria-current', 'page')
  })

  it('折叠按钮只收起当前领域子导航', () => {
    render(
      <MemoryRouter initialEntries={['/library/knowledge']}>
        <Sidebar />
      </MemoryRouter>,
    )

    const sidebar = screen.getByTestId('sidebar')
    fireEvent.click(screen.getByRole('button', { name: '收起子导航' }))

    expect(sidebar).toHaveAttribute('data-collapsed', 'true')
    expect(screen.queryByRole('navigation', { name: '资源库子导航' })).not.toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: '工作域' })).toBeInTheDocument()
  })

  it('1024 到 1439 视口按当前设备保存并恢复子导航折叠偏好', () => {
    installMatchMediaWithViewport(1200)
    const firstRender = render(
      <MemoryRouter initialEntries={['/library/knowledge']}>
        <Sidebar />
      </MemoryRouter>,
    )

    const firstSidebar = screen.getByTestId('sidebar')
    expect(firstSidebar).toHaveAttribute('data-layout', 'collapsible')
    expect(firstSidebar).toHaveAttribute('data-collapsed', 'false')

    fireEvent.click(screen.getByRole('button', { name: '收起子导航' }))
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)).toBe('true')
    firstRender.unmount()

    render(
      <MemoryRouter initialEntries={['/library/knowledge']}>
        <Sidebar />
      </MemoryRouter>,
    )

    expect(screen.getByTestId('sidebar')).toHaveAttribute('data-collapsed', 'true')
  })

  it('768 到 1023 临时面板不覆盖桌面折叠偏好', () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'true')
    installMatchMediaWithViewport(900)
    const tabletRender = render(
      <MemoryRouter initialEntries={['/automations/flows']}>
        <Sidebar />
      </MemoryRouter>,
    )

    const tabletSidebar = screen.getByTestId('sidebar')
    expect(tabletSidebar).toHaveAttribute('data-layout', 'temporary')
    expect(tabletSidebar).toHaveAttribute('data-collapsed', 'true')
    fireEvent.click(screen.getByRole('button', { name: '展开子导航' }))
    expect(tabletSidebar).toHaveAttribute('data-collapsed', 'false')
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)).toBe('true')
    tabletRender.unmount()

    installMatchMediaWithViewport(1200)
    render(
      <MemoryRouter initialEntries={['/automations/flows']}>
        <Sidebar />
      </MemoryRouter>,
    )

    expect(screen.getByTestId('sidebar')).toHaveAttribute('data-collapsed', 'true')
  })

  it('1440 及以上宽屏忽略中型桌面偏好并默认展开', () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'true')
    installMatchMediaWithViewport(1440)

    render(
      <MemoryRouter initialEntries={['/assistant']}>
        <Sidebar />
      </MemoryRouter>,
    )

    const sidebar = screen.getByTestId('sidebar')
    expect(sidebar).toHaveAttribute('data-layout', 'wide')
    expect(sidebar).toHaveAttribute('data-collapsed', 'false')
  })

  it('问题反馈入口继续打开全局反馈面板', () => {
    render(
      <MemoryRouter initialEntries={['/assistant']}>
        <Sidebar />
      </MemoryRouter>,
    )

    act(() => {
      fireEvent.click(screen.getByRole('button', { name: '问题反馈' }))
    })

    expect(useIssueFeedbackStore.getState().isOpen).toBe(true)
  })
})
