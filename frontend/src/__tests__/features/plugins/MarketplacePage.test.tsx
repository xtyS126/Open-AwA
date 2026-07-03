import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MarketplacePage from '@/features/plugins/MarketplacePage'
import { getPlugins, installPlugin, searchPlugins, getPluginRating } from '@/features/plugins/marketplaceApi'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

vi.mock('@/features/plugins/marketplaceApi', () => ({
  getPlugins: vi.fn(),
  searchPlugins: vi.fn(),
  installPlugin: vi.fn(),
  // 评分摘要查询：默认返回空评分，避免 MarketplacePage loadRatings 触发未处理拒绝
  getPluginRating: vi.fn(),
}))

describe('MarketplacePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('alert', vi.fn())
    ;(getPlugins as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        plugins: [
          {
            id: 'plugin-1',
            name: 'Alpha Plugin',
            description: 'alpha desc',
            author: 'alpha-author',
            version: '1.0.0',
            category: 'tool',
            tags: ['tool'],
            download_url: 'https://example.com/alpha.zip',
            icon: '',
            install_count: 10,
          },
        ],
        total: 1,
        page: 1,
        page_size: 12,
      },
    })
    ;(searchPlugins as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        plugins: [
          {
            id: 'plugin-2',
            name: 'Search Plugin',
            description: 'search desc',
            author: 'search-author',
            version: '1.2.3',
            category: 'tool',
            tags: ['search'],
            download_url: 'https://example.com/search.zip',
            icon: '',
            install_count: 3,
          },
        ],
        total: 1,
        page: 1,
        page_size: 12,
      },
    })
    ;(installPlugin as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { ok: true } })
    // 评分摘要查询：默认返回空评分（total_count=0 时组件渲染"暂无评分"）
    ;(getPluginRating as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { average_score: 0, total_count: 0, distribution: {}, user_score: null },
    })
  })

  function renderPage() {
    return render(
      <MemoryRouter initialEntries={['/plugins/marketplace']}>
        <MarketplacePage />
      </MemoryRouter>,
    )
  }

  it('应加载插件并支持分类筛选与返回按钮', async () => {
    renderPage()

    await waitFor(() => {
      expect(getPlugins).toHaveBeenCalledWith({ category: undefined, page: 1, page_size: 12 })
      expect(screen.getByText('Alpha Plugin')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('工具'))

    await waitFor(() => {
      expect(getPlugins).toHaveBeenLastCalledWith({ category: 'tool', page: 1, page_size: 12 })
    })
  })

  it('应支持搜索并展示搜索结果', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('搜索')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('搜索插件名称、描述或标签...'), {
      target: { value: 'search keyword' },
    })
    fireEvent.click(screen.getByText('搜索'))

    await waitFor(() => {
      expect(searchPlugins).toHaveBeenCalled()
    })
  })

  it('应在安装成功后显示已安装状态', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('安装')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('安装'))

    await waitFor(() => {
      expect(installPlugin).toHaveBeenCalledWith('plugin-1')
      expect(screen.getByText('已安装')).toBeInTheDocument()
    })
  })

  it('应在安装失败时提示错误', async () => {
    ;(installPlugin as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { data: { detail: '服务异常' } },
    })
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('安装')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('安装'))

    await waitFor(() => {
      expect(globalThis.alert).toHaveBeenCalledWith('安装失败: 服务异常')
    })
  })
})

// ============================================================================
// SubTask 15.6: 插件市场内置插件过滤测试
// 前端过滤逻辑：visiblePlugins = plugins.filter((p) => p.source !== 'builtin')
// 即使后端返回内置插件，前端也应过滤掉不展示
// ============================================================================

describe('MarketplacePage builtin plugin filtering', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('alert', vi.fn())
    // 评分摘要查询：默认返回空评分，避免 loadRatings 未处理拒绝污染测试输出
    ;(getPluginRating as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { average_score: 0, total_count: 0, distribution: {}, user_score: null },
    })
  })

  function renderPage() {
    return render(
      <MemoryRouter initialEntries={['/plugins/marketplace']}>
        <MarketplacePage />
      </MemoryRouter>,
    )
  }

  it('does not show builtin plugins in marketplace: 内置插件不显示在市场列表', async () => {
    ;(getPlugins as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        plugins: [
          {
            id: 'user-1',
            name: 'User Plugin',
            description: 'user desc',
            author: 'user-author',
            version: '1.0.0',
            category: 'tool',
            tags: ['tool'],
            download_url: 'https://example.com/user.zip',
            icon: '',
            install_count: 5,
            source: 'user',
          },
          {
            id: 'builtin-1',
            name: 'Builtin Plugin',
            description: 'builtin desc',
            author: 'system',
            version: '0.3.147',
            category: 'builtin',
            tags: [],
            download_url: '',
            icon: '',
            install_count: 0,
            source: 'builtin',
          },
        ],
        total: 2,
        page: 1,
        page_size: 12,
      },
    })

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('User Plugin')).toBeInTheDocument()
    })
    // 内置插件应被前端过滤掉，不出现在市场列表中
    expect(screen.queryByText('Builtin Plugin')).not.toBeInTheDocument()
  })

  it('shows all user plugins in marketplace: 用户插件全部展示', async () => {
    ;(getPlugins as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        plugins: [
          {
            id: 'u1',
            name: 'User Alpha',
            description: 'alpha desc',
            author: 'author-a',
            version: '1.0.0',
            category: 'tool',
            tags: [],
            download_url: '',
            icon: '',
            install_count: 0,
            source: 'user',
          },
          {
            id: 'u2',
            name: 'User Beta',
            description: 'beta desc',
            author: 'author-b',
            version: '2.0.0',
            category: 'tool',
            tags: [],
            download_url: '',
            icon: '',
            install_count: 0,
            source: 'user',
          },
        ],
        total: 2,
        page: 1,
        page_size: 12,
      },
    })

    renderPage()

    await waitFor(() => {
      // 两个用户插件都应展示在市场列表中
      expect(screen.getByText('User Alpha')).toBeInTheDocument()
      expect(screen.getByText('User Beta')).toBeInTheDocument()
    })
  })

  it('shows empty state when only builtin plugins exist: 仅内置插件时显示空状态', async () => {
    ;(getPlugins as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        plugins: [
          {
            id: 'b1',
            name: 'Builtin Only',
            description: 'should be hidden',
            author: 'system',
            version: '1.0.0',
            category: 'builtin',
            tags: [],
            download_url: '',
            icon: '',
            install_count: 0,
            source: 'builtin',
          },
        ],
        total: 1,
        page: 1,
        page_size: 12,
      },
    })

    renderPage()

    await waitFor(() => {
      // 内置插件被过滤后 visiblePlugins 为空，触发 EmptyState 渲染
      expect(screen.getByText('未找到匹配的插件')).toBeInTheDocument()
      expect(screen.getByText('尝试更换搜索关键词或筛选条件')).toBeInTheDocument()
    })
    // 内置插件名称不应出现在页面中
    expect(screen.queryByText('Builtin Only')).not.toBeInTheDocument()
  })
})
