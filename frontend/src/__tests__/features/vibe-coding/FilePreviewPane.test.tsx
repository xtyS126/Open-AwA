import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FilePreviewPane from '@/features/vibe-coding/components/FilePreviewPane'

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
}))

vi.mock('@/shared/api/client', () => ({
  API_BASE_URL: '/api',
  api: {
    get: apiMocks.get,
  },
}))

describe('FilePreviewPane', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.get.mockReset()
    if (typeof URL.createObjectURL !== 'function') {
      URL.createObjectURL = vi.fn(() => 'blob:mock-url')
    }
    if (typeof URL.revokeObjectURL !== 'function') {
      URL.revokeObjectURL = vi.fn()
    }
  })

  it('none 意图只显示空状态且不提供路径或端口输入', () => {
    render(<FilePreviewPane projectId={PROJECT_ID} intent={{ kind: 'none' }} />)

    expect(screen.getByText('请选择文件或创建网页预览')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('文件预览通过工作台项目别名只提交相对路径', async () => {
    apiMocks.get.mockResolvedValue({
      data: {
        type: 'markdown',
        html: '<h1>项目说明</h1>',
      },
    })

    render(
      <FilePreviewPane
        projectId={PROJECT_ID}
        intent={{ kind: 'file', relativePath: 'docs/README.md' }}
      />,
    )

    expect(await screen.findByText('项目说明')).toBeInTheDocument()
    expect(apiMocks.get).toHaveBeenCalledWith(
      `/workbench/projects/${PROJECT_ID}/files/preview`,
      expect.objectContaining({
        params: {
          path: 'docs/README.md',
        },
      }),
    )
  })

  it('二进制文件也使用认证 API 与项目标识', async () => {
    const blob = new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], {
      type: 'image/png',
    })
    apiMocks.get.mockResolvedValue({ data: blob })

    render(
      <FilePreviewPane
        projectId={PROJECT_ID}
        intent={{ kind: 'file', relativePath: 'assets/screenshot.png' }}
      />,
    )

    expect(await screen.findByAltText('assets/screenshot.png')).toHaveAttribute(
      'src',
      expect.stringMatching(/^blob:/),
    )
    expect(apiMocks.get).toHaveBeenCalledWith(
      `/workbench/projects/${PROJECT_ID}/files/preview`,
      expect.objectContaining({
        params: {
          path: 'assets/screenshot.png',
        },
        responseType: 'blob',
      }),
    )
  })

  it('下载降级通过认证 API 获取 Blob，不渲染裸链接', async () => {
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    apiMocks.get
      .mockResolvedValueOnce({
        data: {
          type: 'download',
          url: '/api/coding/download?path=archive.bin&project_id=project-a',
        },
      })
      .mockResolvedValueOnce({ data: new Blob(['download']) })

    render(
      <FilePreviewPane
        projectId={PROJECT_ID}
        intent={{ kind: 'file', relativePath: 'archive.bin' }}
      />,
    )

    const downloadButton = await screen.findByRole('button', { name: /下载/ })
    expect(screen.queryByRole('link', { name: /下载/ })).not.toBeInTheDocument()
    fireEvent.click(downloadButton)

    await waitFor(() => {
      expect(apiMocks.get).toHaveBeenLastCalledWith(
        '/coding/download?path=archive.bin&project_id=project-a',
        { responseType: 'blob' },
      )
      expect(clickSpy).toHaveBeenCalledTimes(1)
    })
    clickSpy.mockRestore()
  })

  it('网页预览只使用租约 URL 且 sandbox 不含 allow-same-origin', () => {
    render(
      <FilePreviewPane
        projectId={PROJECT_ID}
        intent={{ kind: 'web', previewId: 'preview-a' }}
      />,
    )

    const frame = screen.getByTitle('网页预览')
    expect(frame).toHaveAttribute(
      'src',
      `/api/workbench/projects/${PROJECT_ID}/previews/preview-a/`,
    )
    expect(frame).toHaveAttribute('sandbox', 'allow-scripts allow-forms')
    expect(frame.getAttribute('sandbox')).not.toContain('allow-same-origin')
    expect(frame.getAttribute('src')).not.toMatch(/:\d+|\/preview\/\d+/)
  })

  it('项目或文件意图变化后丢弃旧请求结果', async () => {
    let resolveOld: ((value: { data: { type: string; html: string } }) => void) | undefined
    const oldRequest = new Promise<{ data: { type: string; html: string } }>((resolve) => {
      resolveOld = resolve
    })
    apiMocks.get
      .mockReturnValueOnce(oldRequest)
      .mockResolvedValueOnce({ data: { type: 'markdown', html: '<h1>项目 B</h1>' } })

    const view = render(
      <FilePreviewPane
        projectId={PROJECT_ID}
        intent={{ kind: 'file', relativePath: 'README.md' }}
      />,
    )
    view.rerender(
      <FilePreviewPane
        projectId="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        intent={{ kind: 'file', relativePath: 'README.md' }}
      />,
    )

    expect(await screen.findByText('项目 B')).toBeInTheDocument()
    resolveOld?.({ data: { type: 'markdown', html: '<h1>项目 A</h1>' } })
    await oldRequest

    await waitFor(() => {
      expect(screen.queryByText('项目 A')).not.toBeInTheDocument()
    })
  })
})
