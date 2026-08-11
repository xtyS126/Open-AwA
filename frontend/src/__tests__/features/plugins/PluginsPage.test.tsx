import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import { RouterTestProvider as BrowserRouter } from '@/shared/routing/testing'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PluginsPage from '@/features/plugins/PluginsPage'
import { pluginsAPI } from '@/shared/api/api'
import { getPlugins, searchPlugins, installPlugin, getPluginRating } from '@/features/plugins/marketplaceApi'

// 拦截 useNavigate，便于在内置插件"设置"按钮跳转测试中断言路由
const mockNavigate = vi.fn()

vi.mock('@/shared/routing', async () => {
  const actual = await vi.importActual<typeof import('@/shared/routing')>('@/shared/routing')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

vi.mock('@/shared/api/api', () => ({
  pluginsAPI: {
    getAll: vi.fn(),
    toggle: vi.fn(),
    uninstall: vi.fn(),
    getPermissions: vi.fn(),
    authorizePermissions: vi.fn(),
    revokePermissions: vi.fn(),
    upload: vi.fn(),
    importFromUrl: vi.fn(),
    // discover 用于本地插件扫描，mock 后避免触发真实网络请求
    discover: vi.fn(),
    install: vi.fn(),
  },
}))

vi.mock('@/features/plugins/marketplaceApi', () => ({
  getPlugins: vi.fn(),
  searchPlugins: vi.fn(),
  installPlugin: vi.fn(),
  // 评分摘要查询：默认返回空评分，避免市场 Tab loadRatings 触发未处理拒绝
  getPluginRating: vi.fn(),
}))

const getAllMock = pluginsAPI.getAll as ReturnType<typeof vi.fn>
const uninstallMock = pluginsAPI.uninstall as ReturnType<typeof vi.fn>
const discoverMock = pluginsAPI.discover as ReturnType<typeof vi.fn>
const toggleMock = pluginsAPI.toggle as ReturnType<typeof vi.fn>
const getPermissionsMock = pluginsAPI.getPermissions as ReturnType<typeof vi.fn>
const authorizePermissionsMock = pluginsAPI.authorizePermissions as ReturnType<typeof vi.fn>
const revokePermissionsMock = pluginsAPI.revokePermissions as ReturnType<typeof vi.fn>
const uploadMock = pluginsAPI.upload as ReturnType<typeof vi.fn>
const importFromUrlMock = pluginsAPI.importFromUrl as ReturnType<typeof vi.fn>

// 每个测试独立的 QueryClient 实例，避免缓存污染（usePluginList 现已使用 TanStack Query）
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 0,
      },
    },
  })
}

/** 包裹 QueryClientProvider 的渲染辅助函数 */
function renderWithProviders(ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>,
  )
}

describe('PluginsPage permissions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('alert', vi.fn())
    getAllMock.mockResolvedValue({
      data: [
        {
          id: 'plugin-1',
          name: 'permission-plugin',
          version: '1.0.0',
          enabled: true,
        },
      ],
    })
    uninstallMock.mockResolvedValue({ data: { message: 'ok' } })
    getPermissionsMock.mockResolvedValue({
      data: {
        plugin_id: 'plugin-1',
        plugin_name: 'permission-plugin',
        requested_permissions: ['network:http'],
        granted_permissions: [],
        missing_permissions: ['network:http'],
      },
    })
    authorizePermissionsMock.mockResolvedValue({
      data: {
        plugin_id: 'plugin-1',
        plugin_name: 'permission-plugin',
        requested_permissions: ['network:http'],
        granted_permissions: ['network:http'],
        missing_permissions: [],
        message: '权限授权成功',
      },
    })
    revokePermissionsMock.mockResolvedValue({
      data: {
        plugin_id: 'plugin-1',
        plugin_name: 'permission-plugin',
        requested_permissions: ['network:http'],
        granted_permissions: [],
        missing_permissions: ['network:http'],
        message: '权限撤销成功',
      },
    })
  })

  afterEach(() => {
    cleanup()
  })

  it('应显示权限弹窗并可授权缺失权限', async () => {
    renderWithProviders(<PluginsPage />)

    // 等待 usePluginList 的 queryFn 完成并渲染插件卡片（包含「权限」按钮）
    const permissionButton = await screen.findByText('权限')
    fireEvent.click(permissionButton)

    await waitFor(() => {
      expect(pluginsAPI.getPermissions).toHaveBeenCalledWith('plugin-1')
      expect(screen.getByText('插件权限')).toBeInTheDocument()
      expect(screen.getByText('network:http')).toBeInTheDocument()
      expect(screen.getByText('待授权')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('授权缺失权限'))

    await waitFor(() => {
      expect(pluginsAPI.authorizePermissions).toHaveBeenCalledWith('plugin-1', ['network:http'])
      expect(screen.getByText('权限授权成功')).toBeInTheDocument()
    })
  })

  it('应支持撤销已授权权限', async () => {
    getPermissionsMock
      .mockResolvedValueOnce({
        data: {
          plugin_id: 'plugin-1',
          plugin_name: 'permission-plugin',
          requested_permissions: ['network:http'],
          granted_permissions: ['network:http'],
          missing_permissions: [],
        },
      })
      .mockResolvedValueOnce({
        data: {
          plugin_id: 'plugin-1',
          plugin_name: 'permission-plugin',
          requested_permissions: ['network:http'],
          granted_permissions: [],
          missing_permissions: ['network:http'],
        },
      })

    renderWithProviders(<PluginsPage />)

    // 等待 usePluginList 的 queryFn 完成并渲染插件卡片（包含「权限」按钮）
    const permissionButton = await screen.findByText('权限')
    fireEvent.click(permissionButton)

    await waitFor(() => {
      expect(screen.getByText('撤销')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('撤销'))

    await waitFor(() => {
      expect(pluginsAPI.revokePermissions).toHaveBeenCalledWith('plugin-1', ['network:http'])
      expect(screen.getByText('已撤销权限: network:http')).toBeInTheDocument()
    })
  })

  it('应支持搜索与批量删除并显示 Toast', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    getAllMock.mockResolvedValue({
      data: [
        { id: 'plugin-1', name: 'alpha-plugin', version: '1.0.0', enabled: true, description: 'first' },
        { id: 'plugin-2', name: 'beta-plugin', version: '1.0.0', enabled: true, description: 'second' },
      ],
    })

    renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(pluginsAPI.getAll).toHaveBeenCalled()
      expect(screen.getByText('alpha-plugin')).toBeInTheDocument()
      expect(screen.getByText('beta-plugin')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('搜索插件名称 / 版本 / 作者 / 简介'), {
      target: { value: 'alpha' },
    })

    expect(screen.getByText('alpha-plugin')).toBeInTheDocument()
    expect(screen.queryByText('beta-plugin')).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('全选当前结果'))
    fireEvent.click(screen.getByText('批量删除(1)'))

    await waitFor(() => {
      expect(pluginsAPI.uninstall).toHaveBeenCalledWith('plugin-1')
      expect(screen.getByText('已批量删除 1 个插件')).toBeInTheDocument()
    })
  })

  it('应支持从 config 回退解析作者与简介', async () => {
    getAllMock.mockResolvedValue({
      data: [
        {
          id: 'plugin-3',
          name: 'fallback-plugin',
          version: '2.0.0',
          enabled: true,
          config: {
            author: 'config-author',
            description:
              '这是一个来自配置的超长简介，用于覆盖简介回退逻辑。这段文字会超过八十个字符，以便展示查看简介与收起简介按钮并验证交互。',
          },
        },
      ],
    })

    renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(screen.getByText('作者：config-author')).toBeInTheDocument()
      expect(
        screen.getByText(
          '这是一个来自配置的超长简介，用于覆盖简介回退逻辑。这段文字会超过八十个字符，以便展示查看简介与收起简介按钮并验证交互。',
        ),
      ).toBeInTheDocument()
    })
  })
})

// ============================================================================
// SubTask 15.6: 内置插件分区测试 —— 覆盖分组渲染、按钮禁用、交互拦截
// 内置插件判定：source === 'builtin' 且 is_uninstallable === true
// 内置插件特征：禁用/启用按钮被禁用 + 不渲染卸载按钮 + 不渲染复选框 + Shield 徽章
// ============================================================================

describe('PluginsPage builtin plugins section', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('alert', vi.fn())
    vi.stubGlobal('confirm', vi.fn(() => true))

    // 默认 mock 数据：2 个用户插件 + 1 个内置插件（bilibili-toolkit-builtin）
    getAllMock.mockResolvedValue({
      data: [
        {
          id: 'user-1',
          name: 'alpha-plugin',
          version: '1.0.0',
          enabled: true,
          source: 'user',
        },
        {
          id: 'user-2',
          name: 'beta-plugin',
          version: '2.0.0',
          enabled: false,
          source: 'user',
        },
        {
          id: 'builtin-1',
          name: 'bilibili-toolkit-builtin',
          version: '0.3.147',
          enabled: true,
          source: 'builtin',
          category: 'builtin',
          is_uninstallable: true,
        },
      ],
    })
    // discover mock 返回空数组，避免本地插件区域渲染干扰断言
    discoverMock.mockResolvedValue({ data: [] })
    uninstallMock.mockResolvedValue({ data: { message: 'ok' } })
    toggleMock.mockResolvedValue({ data: { message: 'ok' } })
    getPermissionsMock.mockResolvedValue({
      data: {
        plugin_id: 'builtin-1',
        plugin_name: 'bilibili-toolkit-builtin',
        requested_permissions: [],
        granted_permissions: [],
        missing_permissions: [],
      },
    })
  })

  afterEach(() => {
    cleanup()
  })

  // ==================== 分组渲染测试（5 个用例）====================
  describe('分组渲染', () => {
    it('renders user plugins section: 应渲染用户插件分区标题', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('用户插件')).toBeInTheDocument()
      })
    })

    it('renders builtin plugins section: 应渲染系统内置插件分区标题与描述', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        // 分区标题来自 i18n key plugins.section.builtin
        expect(screen.getByText('系统内置插件')).toBeInTheDocument()
        // 分区描述来自 i18n key plugins.section.builtin.description
        expect(screen.getByText('系统自带插件，不可卸载')).toBeInTheDocument()
      })
    })

    it('hides builtin section when no builtin plugins: 无内置插件时不渲染内置分区', async () => {
      // mock 数据全部为用户插件，无 source=builtin
      getAllMock.mockResolvedValue({
        data: [
          { id: 'user-1', name: 'alpha-plugin', version: '1.0.0', enabled: true, source: 'user' },
          { id: 'user-2', name: 'beta-plugin', version: '2.0.0', enabled: true, source: 'user' },
        ],
      })

      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('用户插件')).toBeInTheDocument()
        // 内置插件分区应完全不渲染（实现为 builtinPlugins.length > 0 才渲染）
        expect(screen.queryByText('系统内置插件')).not.toBeInTheDocument()
      })
    })

    it('renders correct count badge for each section: 各分区计数徽章正确', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('bilibili-toolkit-builtin')).toBeInTheDocument()
      })

      // 通过分区标题定位 section 容器，再在容器内查找计数徽章
      const userSection = screen.getByText('用户插件').closest('section')!
      const builtinSection = screen.getByText('系统内置插件').closest('section')!
      // 用户插件分区计数徽章应为 2
      expect(within(userSection).getByText('2')).toBeInTheDocument()
      // 内置插件分区计数徽章应为 1
      expect(within(builtinSection).getByText('1')).toBeInTheDocument()
    })

    it('renders builtin plugin with correct name: 内置插件名称与版本正确渲染', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        // 卡片头部应显示完整的插件名称
        expect(screen.getByText('bilibili-toolkit-builtin')).toBeInTheDocument()
        // 版本徽章格式为 "v{version}"
        expect(screen.getByText('v0.3.147')).toBeInTheDocument()
      })
    })
  })

  // ==================== 按钮禁用测试（6 个用例）====================
  describe('按钮禁用', () => {
    it('does not render uninstall button for builtin plugin: 内置插件卡片不渲染卸载按钮', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('bilibili-toolkit-builtin')).toBeInTheDocument()
      })

      // 定位内置插件分区
      const builtinSection = screen.getByText('系统内置插件').closest('section')!
      // 实现为完全不渲染卸载按钮（{!isProtected && <button>...</button>}），而非 disabled
      expect(within(builtinSection).queryByText('卸载')).not.toBeInTheDocument()
    })

    it('disables toggle button for builtin plugin: 内置插件禁用按钮被禁用', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('bilibili-toolkit-builtin')).toBeInTheDocument()
      })

      const builtinSection = screen.getByText('系统内置插件').closest('section')!
      // bilibili-toolkit-builtin 已启用，显示"禁用"按钮
      const toggleButton = within(builtinSection).getByText('禁用').closest('button')!
      expect(toggleButton).toBeDisabled()
      // aria-disabled 与 aria-label 标识禁用原因
      expect(toggleButton).toHaveAttribute('aria-disabled', 'true')
      expect(toggleButton).toHaveAttribute('aria-label', '内置插件不可禁用')
    })

    it('does not render checkbox for builtin plugin: 内置插件卡片不渲染复选框', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('bilibili-toolkit-builtin')).toBeInTheDocument()
      })

      const builtinSection = screen.getByText('系统内置插件').closest('section')!
      // 内置插件不渲染复选框（不可参与批量删除）
      const checkboxes = within(builtinSection).queryAllByRole('checkbox')
      expect(checkboxes).toHaveLength(0)
    })

    it('shows tooltip explaining why button is disabled: 内置插件禁用按钮 Tooltip 提示文案正确', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('bilibili-toolkit-builtin')).toBeInTheDocument()
      })

      const builtinSection = screen.getByText('系统内置插件').closest('section')!
      const toggleButton = within(builtinSection).getByText('禁用').closest('button')!
      // Tooltip 是纯 CSS 实现（data-tip 属性始终存在于 DOM），无需 hover 即可断言
      // 禁用按钮被 Tooltip span 包裹，data-tip 应为 i18n 文案"内置插件不可禁用"
      const tooltipWrapper = toggleButton.parentElement
      expect(tooltipWrapper).toHaveAttribute('data-tip', '内置插件不可禁用')
    })

    it('keeps view config button enabled for builtin plugin: 内置插件设置按钮保持可用', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('bilibili-toolkit-builtin')).toBeInTheDocument()
      })

      const builtinSection = screen.getByText('系统内置插件').closest('section')!
      // "设置"按钮始终可点击（仅跳转配置页，不涉及禁用/卸载逻辑）
      const configButton = within(builtinSection).getByText('设置').closest('button')!
      expect(configButton).not.toBeDisabled()
    })

    it('keeps all action buttons enabled for user plugin: 用户插件禁用与卸载按钮均启用', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('alpha-plugin')).toBeInTheDocument()
      })

      const userSection = screen.getByText('用户插件').closest('section')!
      // alpha-plugin 已启用，"禁用"按钮应可点击
      const disableButton = within(userSection).getByText('禁用').closest('button')!
      expect(disableButton).not.toBeDisabled()
      // 用户插件应渲染"卸载"按钮且可点击（2 个用户插件各 1 个）
      const uninstallButtons = within(userSection).getAllByText('卸载')
      expect(uninstallButtons).toHaveLength(2)
      uninstallButtons.forEach((btn) => {
        const button = btn.closest('button')
        expect(button).not.toBeNull()
        expect(button!).not.toBeDisabled()
      })
    })
  })

  // ==================== 交互拦截测试（3 个用例）====================
  describe('交互拦截', () => {
    it('clicking toggle on builtin plugin does not call toggle api: 内置插件点击禁用按钮不触发 toggle API', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('bilibili-toolkit-builtin')).toBeInTheDocument()
      })

      const builtinSection = screen.getByText('系统内置插件').closest('section')!
      const toggleButton = within(builtinSection).getByText('禁用').closest('button')!

      // 按钮 disabled，fireEvent.click 不会触发 onClick 回调
      fireEvent.click(toggleButton)
      // toggle API 不应被调用（按钮层 + handler 层双重防护）
      expect(toggleMock).not.toHaveBeenCalled()
    })

    it('builtin plugin has no uninstall button so uninstall api never called: 内置插件无卸载按钮，uninstall API 不会被调用', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('bilibili-toolkit-builtin')).toBeInTheDocument()
      })

      const builtinSection = screen.getByText('系统内置插件').closest('section')!
      // 内置插件卡片不渲染"卸载"按钮，因此 uninstall API 永远不会被调用
      expect(within(builtinSection).queryByText('卸载')).not.toBeInTheDocument()
      expect(uninstallMock).not.toHaveBeenCalled()
    })

    it('clicking view config on builtin plugin navigates to config page: 内置插件点击设置按钮跳转到配置页', async () => {
      renderWithProviders(<PluginsPage />)

      await waitFor(() => {
        expect(screen.getByText('bilibili-toolkit-builtin')).toBeInTheDocument()
      })

      const builtinSection = screen.getByText('系统内置插件').closest('section')!
      const configButton = within(builtinSection).getByText('设置').closest('button')!

      // 点击"设置"按钮，应调用 navigate 跳转到配置页（而非打开 modal）
      fireEvent.click(configButton)
      expect(mockNavigate).toHaveBeenCalledWith('/library/capabilities/plugin/builtin-1/config')
    })
  })
})

// ============================================================================
// 市场 Tab 测试 —— 从 MarketplacePage.test.tsx 迁移
// 合并后通过点击「市场」Tab 切换至市场视图
// ============================================================================

describe('PluginsPage 市场 Tab', () => {
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
    // 本地插件相关 mock —— 默认空数据，避免本地插件区域渲染干扰断言
    getAllMock.mockResolvedValue({ data: [] })
    discoverMock.mockResolvedValue({ data: [] })
  })

  afterEach(() => {
    cleanup()
  })

  /** 切换到市场 Tab */
  function switchToMarket() {
    fireEvent.click(screen.getByText('市场'))
  }

  it('应加载市场插件并支持分类筛选', async () => {
    renderWithProviders(<PluginsPage />)

    // 先等待已安装 Tab 渲染完成
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })

    // 切换到市场 Tab
    switchToMarket()

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
    renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })

    switchToMarket()

    await waitFor(() => {
      expect(screen.getByText('Alpha Plugin')).toBeInTheDocument()
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
    renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })

    switchToMarket()

    await waitFor(() => {
      // 市场卡片中"安装"按钮应存在
      expect(screen.getByText('安装')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('安装'))

    await waitFor(() => {
      expect(installPlugin).toHaveBeenCalledWith('plugin-1')
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })
  })

  it('应在安装失败时提示错误', async () => {
    ;(installPlugin as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { data: { detail: '服务异常' } },
    })
    renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })

    switchToMarket()

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
// 市场 Tab 内置插件过滤测试
// 前端过滤逻辑：visiblePlugins = plugins.filter((p) => p.source !== 'builtin')
// 即使后端返回内置插件，前端也应过滤掉不展示
// ============================================================================

describe('PluginsPage 市场 Tab 内置插件过滤', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('alert', vi.fn())
    // 评分摘要查询：默认返回空评分，避免 loadRatings 未处理拒绝污染测试输出
    ;(getPluginRating as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { average_score: 0, total_count: 0, distribution: {}, user_score: null },
    })
    // 本地插件相关 mock —— 默认空数据，避免本地插件区域渲染干扰断言
    getAllMock.mockResolvedValue({ data: [] })
    discoverMock.mockResolvedValue({ data: [] })
  })

  afterEach(() => {
    cleanup()
  })

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

    renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('市场'))

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

    renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('市场'))

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

    renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('市场'))

    await waitFor(() => {
      // 内置插件被过滤后 visiblePlugins 为空，触发 EmptyState 渲染
      expect(screen.getByText('未找到匹配的插件')).toBeInTheDocument()
      expect(screen.getByText('尝试更换搜索关键词或筛选条件')).toBeInTheDocument()
    })
    // 内置插件名称不应出现在页面中
    expect(screen.queryByText('Builtin Only')).not.toBeInTheDocument()
  })
})

// ============================================================================
// 市场 Tab 本地安装工具栏测试 —— 从 MarketplacePage.test.tsx 迁移
// 职责：市场 Tab 集中承载 ZIP 上传 / URL 导入 / 本地可用插件扫描
// 覆盖：ZIP 扩展名与大小校验、URL 首尾空白处理、zip 导入成功、URL 空值校验
// ============================================================================

describe('PluginsPage 市场 Tab 本地安装工具栏', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('alert', vi.fn())
    // 市场列表返回空，避免在线插件卡片干扰本地安装断言
    ;(getPlugins as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { plugins: [], total: 0, page: 1, page_size: 12 },
    })
    ;(getPluginRating as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { average_score: 0, total_count: 0, distribution: {}, user_score: null },
    })
    // 已安装插件列表与本地发现均返回空，避免本地可用插件区域渲染干扰
    getAllMock.mockResolvedValue({ data: [] })
    discoverMock.mockResolvedValue({ data: [] })
  })

  afterEach(() => {
    cleanup()
  })

  it('应在本地导入时校验 zip 扩展名与文件大小', async () => {
    const { container } = renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('市场'))

    // 等待市场 Tab 渲染（file input 出现）
    await waitFor(() => {
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
      expect(fileInput).toBeInTheDocument()
    })

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement

    const invalidExtensionFile = new File(['content'], 'plugin.txt', { type: 'text/plain' })
    fireEvent.change(fileInput, { target: { files: [invalidExtensionFile] } })

    expect(globalThis.alert).toHaveBeenCalledWith('只支持 .zip 格式的插件包')
    expect(pluginsAPI.upload).not.toHaveBeenCalled()

    const oversizedFile = new File(['content'], 'plugin.zip', { type: 'application/zip' })
    Object.defineProperty(oversizedFile, 'size', { value: 51 * 1024 * 1024 })
    fireEvent.change(fileInput, { target: { files: [oversizedFile] } })

    expect(globalThis.alert).toHaveBeenCalledWith('插件包大小无效或已超过 50MB 限制')
    expect(pluginsAPI.upload).not.toHaveBeenCalled()
  })

  it('应在远程导入时去除 URL 首尾空白并成功调用接口', async () => {
    importFromUrlMock.mockResolvedValue({ data: { message: 'ok' } })

    renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('市场'))

    await waitFor(() => {
      expect(screen.getByPlaceholderText('输入远程 ZIP URL（支持白名单域名）')).toBeInTheDocument()
    })

    const urlInput = screen.getByPlaceholderText('输入远程 ZIP URL（支持白名单域名）')
    fireEvent.change(urlInput, { target: { value: '   https://example.com/plugin.zip   ' } })
    fireEvent.click(screen.getByText('URL 导入'))

    await waitFor(() => {
      expect(pluginsAPI.importFromUrl).toHaveBeenCalledWith('https://example.com/plugin.zip', 30)
      expect(screen.getByText('远程 URL 导入成功')).toBeInTheDocument()
    })
  })

  it('应在本地 zip 导入成功后刷新列表并提示成功', async () => {
    uploadMock.mockResolvedValue({ data: { message: 'ok' } })
    const { container } = renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('市场'))

    await waitFor(() => {
      const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
      expect(fileInput).toBeInTheDocument()
    })

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
    const zipFile = new File(['content'], 'demo-plugin.zip', { type: 'application/zip' })
    fireEvent.change(fileInput, { target: { files: [zipFile] } })

    await waitFor(() => {
      expect(pluginsAPI.upload).toHaveBeenCalledTimes(1)
      expect(screen.getByText('插件导入成功')).toBeInTheDocument()
    })
  })

  it('应在远程 URL 为空时给出提示且不发起导入请求', async () => {
    renderWithProviders(<PluginsPage />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /已安装/ })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('市场'))

    await waitFor(() => {
      expect(screen.getByPlaceholderText('输入远程 ZIP URL（支持白名单域名）')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('输入远程 ZIP URL（支持白名单域名）'), {
      target: { value: '   ' },
    })
    fireEvent.click(screen.getByText('URL 导入'))

    expect(pluginsAPI.importFromUrl).not.toHaveBeenCalled()
    expect(screen.getByText('请输入远程 URL')).toBeInTheDocument()
  })
})
