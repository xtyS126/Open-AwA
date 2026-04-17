import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MarketplacePage from '@/features/plugins/MarketplacePage'
import { getPlugins, installPlugin, searchPlugins } from '@/features/plugins/marketplaceApi'

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
  })

  it('应加载插件并支持分类筛选与返回按钮', async () => {
    render(<MarketplacePage />)

    await waitFor(() => {
      expect(getPlugins).toHaveBeenCalledWith({ category: undefined, page: 1, page_size: 12 })
      expect(screen.getByText('Alpha Plugin')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('工具'))

    await waitFor(() => {
      expect(getPlugins).toHaveBeenLastCalledWith({ category: 'tool', page: 1, page_size: 12 })
    })

    fireEvent.click(screen.getByText('返回插件管理'))
    expect(mockNavigate).toHaveBeenCalledWith('/plugins')
  })

  it('应支持搜索并展示搜索结果', async () => {
    render(<MarketplacePage />)

    await waitFor(() => {
      expect(screen.getByText('搜索')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('搜索插件名称、描述或标签...'), {
      target: { value: 'search keyword' },
    })
    fireEvent.click(screen.getByText('搜索'))

    await waitFor(() => {
      expect(searchPlugins).toHaveBeenCalledWith('search keyword')
      expect(screen.getByText('Search Plugin')).toBeInTheDocument()
    })
  })

  it('应在安装成功后显示已安装状态', async () => {
    render(<MarketplacePage />)

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
    render(<MarketplacePage />)

    await waitFor(() => {
      expect(screen.getByText('安装')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('安装'))

    await waitFor(() => {
      expect(globalThis.alert).toHaveBeenCalledWith('安装失败: 服务异常')
    })
  })
})
