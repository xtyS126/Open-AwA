import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import ChatPage from '@/features/chat/ChatPage'

if (!HTMLElement.prototype.scrollIntoView) {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    value: () => {},
    writable: true
  })
}

// 模拟 chatStore —— 模型选择已迁至全局 store
const mockAddMessage = vi.fn()
const mockSetLoading = vi.fn()
const mockClearMessages = vi.fn()
const mockSetOutputMode = vi.fn()
const mockUpdateLastMessage = vi.fn()

vi.mock('@/features/chat/store/chatStore', () => ({
  useChatStore: vi.fn(() => ({
    messages: [],
    addMessage: mockAddMessage,
    updateLastMessage: mockUpdateLastMessage,
    setLoading: mockSetLoading,
    isLoading: false,
    clearMessages: mockClearMessages,
    sessionId: 'default',
    outputMode: 'stream',
    setOutputMode: mockSetOutputMode,
    selectedModel: 'openai:gpt-4',
  }))
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
  }
}))

describe('ChatPage', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  describe('Basic Rendering', () => {
    it('should render chat page with header', () => {
      render(<ChatPage />)
      expect(screen.getByText('AI 助手')).toBeInTheDocument()
    })

    it('should render output mode selector', () => {
      render(<ChatPage />)
      expect(screen.getByText('流式传输')).toBeInTheDocument()
      expect(screen.getByText('直接输出')).toBeInTheDocument()
    })

    it('should render new conversation button', () => {
      render(<ChatPage />)
      expect(screen.getByText('新对话')).toBeInTheDocument()
    })

    it('should render empty state message', () => {
      render(<ChatPage />)
      expect(screen.getByText(/有什么可以帮助你的吗/)).toBeInTheDocument()
    })

    it('should render input field and send button', () => {
      render(<ChatPage />)
      expect(screen.getByPlaceholderText('输入你的问题...')).toBeInTheDocument()
      expect(screen.getByText('发送')).toBeInTheDocument()
    })
  })

  describe('Model Selector Migration', () => {
    it('should not render model dropdown (migrated to settings)', () => {
      render(<ChatPage />)
      // 模型选择器已迁移至设置页面，聊天页不应包含模型下拉框
      const selects = screen.getAllByRole('combobox')
      // 只有输出模式选择器，不应有模型选择器
      expect(selects.length).toBe(1)
    })

    it('should display current model name from global store', () => {
      render(<ChatPage />)
      // 当前选中模型名称应在 header 以紧凑标签显示
      expect(screen.getByText('gpt-4')).toBeInTheDocument()
    })
  })

  describe('User Interaction', () => {
    it('should clear messages when clicking new conversation button', () => {
      render(<ChatPage />)
      fireEvent.click(screen.getByText('新对话'))
      expect(mockClearMessages).toHaveBeenCalled()
    })

    it('should disable send button when input is empty', () => {
      render(<ChatPage />)
      const sendBtn = screen.getByText('发送')
      expect(sendBtn).toBeDisabled()
    })
  })
})
