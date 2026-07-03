/**
 * FilePreviewPane 文件预览面板单元测试。
 *
 * 覆盖点：
 *   - 空状态展示
 *   - 路径输入框渲染
 *   - 按扩展名分发：.md 走 markdown HTML 渲染
 *   - 按扩展名分发：.png 走 blob 图片渲染
 *   - 未知扩展名走 download 类型，显示下载链接
 *   - 加载失败时错误提示
 *
 * Mock：@/shared/api/client 的 api.get 方法。
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, it, expect, vi } from 'vitest'
import FilePreviewPane from '@/features/vibe-coding/components/FilePreviewPane'

// 通过 vi.hoisted 提升的 mock 定义，确保在 vi.mock 调用前可用
const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
}))

vi.mock('@/shared/api/client', () => ({
  // 复用 API_BASE_URL 默认值，避免破坏 URL 解析
  API_BASE_URL: '/api',
  api: {
    get: apiMocks.get,
  },
}))

describe('FilePreviewPane', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // jsdom 未实现 URL.createObjectURL / revokeObjectURL，图片预览测试需要
    if (typeof URL.createObjectURL !== 'function') {
      URL.createObjectURL = vi.fn(() => 'blob:mock-url')
    }
    if (typeof URL.revokeObjectURL !== 'function') {
      URL.revokeObjectURL = vi.fn()
    }
  })

  it('renders empty state when no file path', () => {
    render(<FilePreviewPane filePath={null} />)

    // 空状态文案来自 i18n: vibeCoding.filePreview.empty
    expect(screen.getByText('请输入文件路径预览')).toBeInTheDocument()
  })

  it('renders path input', () => {
    render(<FilePreviewPane filePath={null} />)

    // 路径输入框 placeholder 来自 i18n: vibeCoding.filePreview.pathPlaceholder
    expect(screen.getByPlaceholderText('输入文件绝对路径')).toBeInTheDocument()
  })

  it('loads markdown preview for .md files', async () => {
    apiMocks.get.mockResolvedValue({
      data: {
        type: 'markdown',
        html: '<h1 id="title">标题内容</h1>',
      },
    })

    render(<FilePreviewPane filePath="/tmp/readme.md" />)

    // markdown HTML 通过 dangerouslySetInnerHTML 注入，等待渲染完成
    await waitFor(() => {
      const heading = screen.getByText('标题内容')
      expect(heading).toBeInTheDocument()
      expect(heading.tagName).toBe('H1')
    })

    // 验证 api.get 以 markdown 路径调用
    expect(apiMocks.get).toHaveBeenCalledWith(
      '/coding/preview/file',
      expect.objectContaining({
        params: { path: '/tmp/readme.md' },
      })
    )
  })

  it('loads image preview for .png files', async () => {
    // 构造一个 Blob 模拟二进制图片响应
    const blob = new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: 'image/png' })
    apiMocks.get.mockResolvedValue({ data: blob })

    render(<FilePreviewPane filePath="/tmp/screenshot.png" />)

    // 验证图片标签渲染并指向 blob URL
    const img = await screen.findByAltText('/tmp/screenshot.png')
    expect(img).toBeInTheDocument()
    expect(img.tagName).toBe('IMG')
    expect(img.getAttribute('src')).toMatch(/^blob:/)

    // 二进制路径应使用 responseType: 'blob'
    expect(apiMocks.get).toHaveBeenCalledWith(
      '/coding/preview/file',
      expect.objectContaining({
        params: { path: '/tmp/screenshot.png' },
        responseType: 'blob',
      })
    )
  })

  it('shows unsupported message for unknown extensions', async () => {
    // 未知扩展名 .xyz 后端返回 download 类型，应展示不支持提示与下载链接
    apiMocks.get.mockResolvedValue({
      data: {
        type: 'download',
        url: '/coding/download/test.xyz',
      },
    })

    render(<FilePreviewPane filePath="/tmp/archive.xyz" />)

    // 等待加载完成，验证不支持提示文案与下载链接
    await waitFor(() => {
      expect(screen.getByText('不支持预览此文件类型')).toBeInTheDocument()
    })
    const downloadLink = screen.getByText('下载文件').closest('a')
    expect(downloadLink).not.toBeNull()
    // URL 应被解析为完整地址（基于 /api 前缀）
    expect(downloadLink?.getAttribute('href')).toContain('/coding/download/test.xyz')
  })

  it('handles load error gracefully', async () => {
    // 模拟 api.get 抛出错误
    apiMocks.get.mockRejectedValue(new Error('网络错误：503'))

    render(<FilePreviewPane filePath="/tmp/broken.md" />)

    // 验证错误提示显示，文案来自 i18n: vibeCoding.filePreview.error
    await waitFor(() => {
      const errorTexts = screen.getAllByText(/加载失败/)
      expect(errorTexts.length).toBeGreaterThan(0)
    })
  })
})
