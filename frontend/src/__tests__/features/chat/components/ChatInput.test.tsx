import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

// mock useVisualViewport，避免 jsdom 缺失 visualViewport API
vi.mock('@/shared/hooks/useVisualViewport', () => ({
  useVisualViewport: () => ({
    height: null,
    width: null,
    isKeyboardOpen: false,
    offsetTop: 0,
  }),
}))

// mock logger，避免测试输出噪声
vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}))

import { ChatInput, type FileAttachment } from '@/features/chat/components/ChatInput'

/** 保存原生 FileReader，便于 afterEach 恢复 */
const OriginalFileReader = globalThis.FileReader

/**
 * 安装 MockFileReader，可通过 setFailureFor 控制哪些文件名触发 onerror。
 * 默认所有文件 readAsDataURL 异步触发 onload 返回 base64 字符串。
 */
function installMockFileReader(options: { failFor?: Set<string> } = {}) {
  const failFor = options.failFor ?? new Set<string>()
  const callLog: string[] = []

  class MockFileReader {
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    result: string | null = null
    error: DOMException | null = null

    readAsDataURL(file: File) {
      callLog.push(file.name)
      // 异步触发，模拟真实 FileReader 行为
      setTimeout(() => {
        if (failFor.has(file.name)) {
          this.error = new DOMException('mock read error', 'ReadError')
          this.onerror?.()
        } else {
          // 模拟 data URL：data:<mime>;base64,<base64-encoded content>
          this.result = `data:${file.type};base64,${btoa(file.name)}`
          this.onload?.()
        }
      }, 0)
    }
  }

  Object.defineProperty(globalThis, 'FileReader', {
    writable: true,
    configurable: true,
    value: MockFileReader,
  })

  return {
    callLog,
    restore: () => {
      Object.defineProperty(globalThis, 'FileReader', {
        writable: true,
        configurable: true,
        value: OriginalFileReader,
      })
    },
  }
}

/** 构造 File 对象 */
function makeFile(name: string, type: string): File {
  return new File([name], name, { type })
}

/** 通过 file input 触发附件添加 */
function addFilesViaInput(input: HTMLElement, files: File[]) {
  fireEvent.change(input, { target: { files } })
}

describe('ChatInput - 附件并行编码', () => {
  let mockUrl: ReturnType<typeof vi.fn>
  let revokeUrl: ReturnType<typeof vi.fn>

  beforeEach(() => {
    mockUrl = vi.fn(() => 'blob:mock-url')
    revokeUrl = vi.fn()
    Object.defineProperty(globalThis.URL, 'createObjectURL', {
      writable: true,
      configurable: true,
      value: mockUrl,
    })
    Object.defineProperty(globalThis.URL, 'revokeObjectURL', {
      writable: true,
      configurable: true,
      value: revokeUrl,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('多个附件并行编码（验证 Promise.all 被调用）', async () => {
    const fileReaderMock = installMockFileReader()

    // 监视 Promise.all 调用，同时保持原生行为（mockImplementation 调用原始实现）
    const originalPromiseAll = Promise.all.bind(Promise)
    const promiseAllSpy = vi.spyOn(Promise, 'all').mockImplementation(<T,>(iterable: Iterable<T | PromiseLike<T>>) =>
      originalPromiseAll(iterable as Iterable<T | PromiseLike<T>>)
    )

    const onSend = vi.fn(() => Promise.resolve())

    render(
      <ChatInput
        onSend={onSend}
        isLoading={false}
        streamingAssistantId={null}
        onAbort={vi.fn()}
      />
    )

    const fileInput = document.querySelector('input[type="file"]') as HTMLElement
    expect(fileInput).toBeInTheDocument()

    // 加入 3 个图片附件
    const files = [
      makeFile('a.png', 'image/png'),
      makeFile('b.png', 'image/png'),
      makeFile('c.png', 'image/png'),
    ]
    addFilesViaInput(fileInput, files)

    // 等待附件预览渲染
    await waitFor(() => {
      expect(screen.getByText('a.png')).toBeInTheDocument()
    })

    // 输入文本并点击发送
    const textarea = screen.getByTestId('chat-input-textarea') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '发送消息' } })
    const sendButton = screen.getByRole('button', { name: /send/i })
    fireEvent.click(sendButton)

    // 等待 onSend 被调用（异步 base64 编码完成后）
    await waitFor(() => {
      expect(onSend).toHaveBeenCalledTimes(1)
    })

    // Promise.all 应被调用至少一次（用于并行编码附件）
    expect(promiseAllSpy).toHaveBeenCalled()

    // onSend 接收的 attachments 应全部包含 base64Data
    const callArgs = onSend.mock.calls[0]
    const sentContent = callArgs[0] as string
    const sentAttachments = callArgs[1] as FileAttachment[]

    expect(sentContent).toBe('发送消息')
    expect(sentAttachments).toHaveLength(3)
    for (const att of sentAttachments) {
      expect(att.base64Data).toBeDefined()
      expect(att.base64Data).not.toBe('')
      expect(att.mimeType).toBe('image/png')
    }

    // FileReader 应被调用 3 次（每个附件一次）
    expect(fileReaderMock.callLog).toHaveLength(3)
    expect(fileReaderMock.callLog).toEqual(expect.arrayContaining(['a.png', 'b.png', 'c.png']))

    fileReaderMock.restore()
  })

  it('单个附件编码失败时跳过该附件（保留其他附件）', async () => {
    // 让 b.png 编码失败
    const fileReaderMock = installMockFileReader({ failFor: new Set(['b.png']) })

    const onSend = vi.fn(() => Promise.resolve())

    render(
      <ChatInput
        onSend={onSend}
        isLoading={false}
        streamingAssistantId={null}
        onAbort={vi.fn()}
      />
    )

    const fileInput = document.querySelector('input[type="file"]') as HTMLElement

    // 加入 3 个图片附件，其中 b.png 会失败
    const files = [
      makeFile('a.png', 'image/png'),
      makeFile('b.png', 'image/png'),
      makeFile('c.png', 'image/png'),
    ]
    addFilesViaInput(fileInput, files)

    await waitFor(() => {
      expect(screen.getByText('a.png')).toBeInTheDocument()
    })

    const textarea = screen.getByTestId('chat-input-textarea') as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: '发送消息' } })
    const sendButton = screen.getByRole('button', { name: /send/i })
    fireEvent.click(sendButton)

    // 等待 onSend 被调用
    await waitFor(() => {
      expect(onSend).toHaveBeenCalledTimes(1)
    }, { timeout: 2000 })

    // onSend 接收的 attachments 应只有 2 个（b.png 失败被跳过）
    const callArgs = onSend.mock.calls[0]
    const sentAttachments = callArgs[1] as FileAttachment[]

    expect(sentAttachments).toHaveLength(2)
    const sentNames = sentAttachments.map((a) => a.file.name)
    expect(sentNames).toEqual(expect.arrayContaining(['a.png', 'c.png']))
    expect(sentNames).not.toContain('b.png')

    // 被保留的附件仍应有 base64Data
    for (const att of sentAttachments) {
      expect(att.base64Data).toBeDefined()
      expect(att.base64Data).not.toBe('')
    }

    // FileReader 应被调用 3 次（每个附件都尝试编码）
    expect(fileReaderMock.callLog).toHaveLength(3)

    fileReaderMock.restore()
  })
})
