import '@testing-library/jest-dom/vitest'
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import Sidebar from '@/shared/components/Sidebar/Sidebar'
import { RouterTestProvider as MemoryRouter } from '@/shared/routing/testing'
import { useI18nStore } from '@/i18n'
import { useIssueFeedbackStore } from '@/shared/store/issueFeedbackStore'
import { useMobileNavStore } from '@/shared/store/mobileNavStore'
import { useAuthStore } from '@/shared/store/authStore'
import styles from '@/shared/components/Sidebar/Sidebar.module.css'

vi.mock('@/shared/api/api', () => ({
  pluginsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  weixinAPI: { getConfig: vi.fn().mockResolvedValue({ data: {} }) },
  authAPI: { getMe: vi.fn().mockResolvedValue({ data: {} }), logout: vi.fn().mockResolvedValue({ data: {} }) },
  billingAPI: { getSummary: vi.fn().mockResolvedValue({ data: {} }) },
  chatAPI: { getHistory: vi.fn().mockResolvedValue({ data: [] }) },
  modelsAPI: { getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }) },
  memoryAPI: { getShortTerm: vi.fn().mockResolvedValue({ data: [] }), getLongTerm: vi.fn().mockResolvedValue({ data: [] }) },
  experiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  fileExperiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  skillsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  promptsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  logsAPI: { query: vi.fn().mockResolvedValue({ data: { records: [], total: 0 } }) },
  behaviorAPI: { getStats: vi.fn().mockResolvedValue({ data: {} }) },
  conversationAPI: { getRecordsPreview: vi.fn().mockResolvedValue({ data: { records: [], count: 0 } }) }
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }),
    updateConfiguration: vi.fn().mockResolvedValue({ data: {} })
  }
}))

describe('Sidebar', () => {
  beforeEach(() => {
    useI18nStore.getState().setLocale('zh-CN')
    // 重置问题反馈 store 状态
    useIssueFeedbackStore.setState({
      isOpen: false,
      submitting: false,
      draft: { issue_type: 'bug', title: '', content: '', page_url: '' },
    })
  })

  it('展示导航链接：定时任务、插件等模块入口', () => {
    render(
      <MemoryRouter initialEntries={['/plugins/manage']}>
        <Sidebar />
      </MemoryRouter>
    )

    expect(screen.getByRole('link', { name: '定时任务' })).toHaveAttribute('href', '/scheduled-tasks')
    expect(screen.getByRole('link', { name: '插件管理' })).toHaveAttribute('href', '/plugins/manage')
  })

  it('任意插件子路由都应高亮同一个插件入口', () => {
    render(
      <MemoryRouter initialEntries={['/plugins/config/test-plugin']}>
        <Sidebar />
      </MemoryRouter>
    )

    const pluginLink = screen.getByRole('link', { name: '插件管理' })
    expect(pluginLink.className).toMatch(/active/)
  })

  it('点击问题反馈按钮打开反馈面板', () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    )

    const feedbackBtn = screen.getByTestId('sidebar-issue-feedback-btn')
    expect(feedbackBtn).toBeInTheDocument()

    act(() => {
      fireEvent.click(feedbackBtn)
    })

    expect(useIssueFeedbackStore.getState().isOpen).toBe(true)
  })
})

/**
 * Sidebar 移动端滑动手势与遮罩测试
 *
 * 验证点：
 * 1. 抽屉打开（mobile-open 类）后锁定 body 滚动（overflow: hidden）
 * 2. 向左滑动超过 60px 阈值时抽屉关闭
 * 3. 向左滑动未达阈值时抽屉保持打开
 * 4. 点击遮罩层关闭抽屉
 * 5. 未打开抽屉时 touchStart 不记录起点，touchEnd 不触发关闭
 *
 * 抽屉打开方式：左上角汉堡按钮已移除，统一经底部 Tab Bar "更多"入口
 * （useMobileNavStore.openDrawer）打开，与真实交互路径一致。
 */
describe('Sidebar 移动端滑动手势与遮罩', () => {
  beforeEach(() => {
    useI18nStore.getState().setLocale('zh-CN')
  })

  afterEach(() => {
    document.body.style.overflow = ''
    useMobileNavStore.getState().closeDrawer()
  })

  /** 渲染 Sidebar 并返回 aside 元素与遮罩层 */
  function renderSidebar() {
    const utils = render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    )
    const aside = utils.container.querySelector('aside')
    if (!aside) throw new Error('aside 元素未渲染')
    const overlay = utils.container.querySelector(`.${styles['mobile-overlay']}`) as HTMLElement | null
    return { ...utils, aside, overlay }
  }

  /** 经共享 store 打开抽屉（与底部 Tab Bar "更多"按钮同路径） */
  function openDrawer() {
    act(() => {
      useMobileNavStore.getState().openDrawer()
    })
  }

  /** 模拟一次完整的 touchStart -> touchMove -> touchEnd 序列 */
  function simulateSwipe(
    aside: HTMLElement,
    startX: number,
    endX: number,
  ) {
    act(() => {
      aside.dispatchEvent(
        new TouchEvent('touchstart', {
          bubbles: true,
          touches: [{ clientX: startX } as Touch],
        }),
      )
    })
    act(() => {
      aside.dispatchEvent(
        new TouchEvent('touchmove', {
          bubbles: true,
          touches: [{ clientX: endX } as Touch],
        }),
      )
    })
    act(() => {
      aside.dispatchEvent(new TouchEvent('touchend', { bubbles: true }))
    })
  }

  it('抽屉打开后锁定 body 滚动', () => {
    const { aside } = renderSidebar()

    openDrawer()

    expect(aside.className).toContain(styles['mobile-open'])
    expect(aside.className).toContain('mobile-open')
    expect(document.body.style.overflow).toBe('hidden')
  })

  it('向左滑动超过 60px 阈值时抽屉关闭', () => {
    const { aside } = renderSidebar()

    // 先打开抽屉
    openDrawer()
    expect(aside.className).toContain('mobile-open')

    // 向左滑动 100px（超过 60px 阈值）
    simulateSwipe(aside, 200, 100)

    expect(aside.className).not.toContain('mobile-open')
  })

  it('同一批触摸事件中向左滑动超过阈值时抽屉关闭', () => {
    const { aside } = renderSidebar()

    openDrawer()

    act(() => {
      aside.dispatchEvent(new TouchEvent('touchstart', {
        bubbles: true,
        touches: [{ clientX: 200 } as Touch],
      }))
      aside.dispatchEvent(new TouchEvent('touchmove', {
        bubbles: true,
        touches: [{ clientX: 100 } as Touch],
      }))
      aside.dispatchEvent(new TouchEvent('touchend', { bubbles: true }))
    })

    expect(aside.className).not.toContain('mobile-open')
  })

  it('向左滑动未达 60px 阈值时抽屉保持打开', () => {
    const { aside } = renderSidebar()

    // 先打开抽屉
    openDrawer()
    expect(aside.className).toContain('mobile-open')

    // 向左滑动 40px（未达 60px 阈值）
    simulateSwipe(aside, 200, 160)

    expect(aside.className).toContain('mobile-open')
  })

  it('向右滑动（offset > 0）不应触发关闭，且不更新 dragOffset', () => {
    const { aside } = renderSidebar()

    openDrawer()
    expect(aside.className).toContain('mobile-open')

    // 向右滑动 50px（offset > 0，handleTouchMove 中 if (offset < 0) 不满足）
    simulateSwipe(aside, 100, 150)

    expect(aside.className).toContain('mobile-open')
  })

  it('抽屉未打开时 touchStart 不响应，touchEnd 不触发关闭', () => {
    const { aside } = renderSidebar()

    // 抽屉初始未打开
    expect(aside.className).not.toContain('mobile-open')

    // 直接模拟 touch 序列（无起点记录）
    simulateSwipe(aside, 200, 50)

    // 仍应保持关闭状态（不应误打开）
    expect(aside.className).not.toContain('mobile-open')
  })

  it('点击遮罩层关闭抽屉', () => {
    const { aside, overlay } = renderSidebar()
    expect(overlay).toBeTruthy()

    openDrawer()
    expect(aside.className).toContain('mobile-open')

    act(() => {
      overlay?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(aside.className).not.toContain('mobile-open')
  })

  it('抽屉关闭后 body 滚动锁定恢复', async () => {
    const { aside } = renderSidebar()

    // 打开抽屉锁定滚动
    openDrawer()
    expect(document.body.style.overflow).toBe('hidden')

    // 滑动关闭
    simulateSwipe(aside, 200, 100)

    // body 滚动应恢复正常
    await waitFor(() => {
      expect(document.body.style.overflow).not.toBe('hidden')
    })
  })
})

/**
 * Sidebar 移动端用户菜单测试
 *
 * 验证点：
 * 1. 点击头像弹出用户菜单（不再整页跳转 /user，停留当前页）
 * 2. 点击遮罩关闭菜单
 * 3. 点击"用户中心"菜单项关闭菜单并进入用户中心
 */
describe('Sidebar 移动端用户菜单', () => {
  beforeEach(() => {
    useI18nStore.getState().setLocale('zh-CN')
    // 注入已登录用户，否则 MobileUserArea 不渲染
    useAuthStore.setState({
      user: { id: '1', username: 'admin', role: 'owner' },
      isAuthenticated: true,
      isInitialized: true,
    })
  })

  afterEach(() => {
    useAuthStore.setState({ user: null, isAuthenticated: false })
  })

  function renderSidebarWithUser() {
    return render(
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
      </MemoryRouter>
    )
  }

  it('点击头像打开用户菜单，停留在当前页（不整页跳转）', () => {
    renderSidebarWithUser()

    // 菜单初始不可见
    expect(screen.queryByTestId('user-menu')).not.toBeInTheDocument()

    act(() => {
      fireEvent.click(screen.getByTestId('mobile-user-area'))
    })

    // 菜单出现，含用户中心与退出登录菜单项
    expect(screen.getByTestId('user-menu')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '用户中心' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '退出登录' })).toBeInTheDocument()
  })

  it('点击遮罩关闭用户菜单', () => {
    renderSidebarWithUser()

    act(() => {
      fireEvent.click(screen.getByTestId('mobile-user-area'))
    })
    expect(screen.getByTestId('user-menu')).toBeInTheDocument()

    act(() => {
      fireEvent.click(screen.getByTestId('user-menu-overlay'))
    })
    expect(screen.queryByTestId('user-menu')).not.toBeInTheDocument()
  })

  it('点击"用户中心"菜单项关闭菜单', () => {
    renderSidebarWithUser()

    act(() => {
      fireEvent.click(screen.getByTestId('mobile-user-area'))
    })
    expect(screen.getByTestId('user-menu')).toBeInTheDocument()

    act(() => {
      fireEvent.click(screen.getByRole('menuitem', { name: '用户中心' }))
    })
    expect(screen.queryByTestId('user-menu')).not.toBeInTheDocument()
  })

  it('非聊天页（设置/记忆/技能等）不渲染头像用户区', () => {
    // 记忆页
    const memory = render(
      <MemoryRouter initialEntries={['/memory']}>
        <Sidebar />
      </MemoryRouter>
    )
    expect(screen.queryByTestId('mobile-user-area')).not.toBeInTheDocument()
    memory.unmount()

    // 技能页
    const skills = render(
      <MemoryRouter initialEntries={['/skills']}>
        <Sidebar />
      </MemoryRouter>
    )
    expect(screen.queryByTestId('mobile-user-area')).not.toBeInTheDocument()
    skills.unmount()

    // 设置页
    render(
      <MemoryRouter initialEntries={['/settings']}>
        <Sidebar />
      </MemoryRouter>
    )
    expect(screen.queryByTestId('mobile-user-area')).not.toBeInTheDocument()
  })
})
