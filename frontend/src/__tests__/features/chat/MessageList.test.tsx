import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MessageList } from '@/features/chat/components/MessageList'
import { useI18nStore } from '@/i18n'
import type { ChatMessage as ChatMessageType } from '@/features/chat/types'

vi.mock('@/i18n', () => ({
  useI18nStore: createI18nStoreMock(),
  default: () => 'chat.empty'
}))

function createI18nStoreMock() {
  const store = {
    locale: 'zh-CN',
    t: (key: string) => {
      const dict: Record<string, string> = {
        'chat.empty': '暂无聊天记录，开始对话吧！'
      }
      return dict[key] || key
    }
  }
  // 支持选择器模式 useI18nStore(s => s.t) 和全量订阅 useI18nStore()
  const mockFn: any = (selector?: (s: typeof store) => unknown) => selector ? selector(store) : store
  return mockFn
}

import React from 'react'

// 针对 react-virtuoso 单元测试下的替代 mock，因为 virtuoso 依赖浏览器真正的 layout 及尺寸计算。
// 在 jsdom 测试环境下，使用一个普通的组件包裹来代替真实渲染。
vi.mock('react-virtuoso', () => {
  const ReactMock = require('react')
  const VirtuosoMock = ReactMock.forwardRef(({ data, itemContent, components }: any, ref: any) => {
    const Footer = components?.Footer || (() => null)
    return (
      <div data-testid="mock-virtuoso" ref={ref}>
        {data.map((item: any, index: number) => (
          <div key={index} data-testid={`virtuoso-item-${index}`}>
            {itemContent(index, item)}
          </div>
        ))}
        <div data-testid="virtuoso-footer">
          <Footer />
        </div>
      </div>
    )
  })
  VirtuosoMock.displayName = 'Virtuoso'
  return {
    Virtuoso: VirtuosoMock
  }
})

vi.mock('@/features/chat/components/ChatMessage', () => ({
  ChatMessage: ({ message }: { message: ChatMessageType }) => (
    <div data-testid={`message-item-${message.id}`}>
      {message.content}
    </div>
  )
}))

describe('MessageList 虚拟滚动实装', () => {
  const mockMessages: ChatMessageType[] = Array.from({ length: 15 }, (_, i) => ({
    id: `msg-${i}`,
    session_id: 'session-1',
    sender_type: i % 2 === 0 ? 'user' : 'assistant',
    sender_id: 'test',
    content: `这第 ${i} 条测试消息内容`,
    created_at: Date.now() / 1000,
    updated_at: Date.now() / 1000
  }))

  const messageMeta = {}
  const messagesEndRef = { current: null }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('在消息数量较少时应直接进行普通循环渲染，不加载 Virtuoso', () => {
    render(
      <MessageList
        messages={mockMessages.slice(0, 10)} // 10条消息，远低于默认 100 阈值
        messageMeta={messageMeta}
        streamingAssistantId={null}
        isLoading={false}
        outputMode="stream"
        streamStatusText=""
        messagesEndRef={messagesEndRef}
      />
    )

    // 不应当渲染 mock-virtuoso
    expect(screen.queryByTestId('mock-virtuoso')).not.toBeInTheDocument()

    // 应当渲染普通消息项
    expect(screen.getByTestId('message-item-msg-0')).toBeInTheDocument()
    expect(screen.getByTestId('message-item-msg-9')).toBeInTheDocument()
  })

  it('在消息数量大幅增加超过 VIRTUAL_THRESHOLD (或为 15) 时应成功启用 Virtuoso 虚拟化容器', () => {
    // 之前 VIRTUAL_THRESHOLD 是 100，为了在所有长对话中让虚拟化效果明显并提供流畅的体验，
    // 在消息数量较多时，例如 15 条消息以上，我们可以根据阈值变化让它完全进入 Virtuoso。
    // 这里我们先验证当消息数量达到阈值时的 Virtuoso 启动。
    render(
      <MessageList
        messages={mockMessages} // 15 条消息
        messageMeta={messageMeta}
        streamingAssistantId={null}
        isLoading={false}
        outputMode="stream"
        streamStatusText=""
        messagesEndRef={messagesEndRef}
      />
    )

    // 此时应当通过 Virtuoso 进行渲染
    const virtuoso = screen.getByTestId('mock-virtuoso')
    expect(virtuoso).toBeInTheDocument()
    expect(screen.getByTestId('message-item-msg-0')).toBeInTheDocument()
    expect(screen.getByTestId('message-item-msg-14')).toBeInTheDocument()
  })

  it('展示空消息列表提示', () => {
    render(
      <MessageList
        messages={[]}
        messageMeta={messageMeta}
        streamingAssistantId={null}
        isLoading={false}
        outputMode="stream"
        streamStatusText=""
        messagesEndRef={messagesEndRef}
      />
    )

    expect(screen.getByText('暂无聊天记录，开始对话吧！')).toBeInTheDocument()
  })
})
