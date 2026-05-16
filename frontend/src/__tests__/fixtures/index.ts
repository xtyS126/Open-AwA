/**
 * 前端测试 Fixtures — 标准化的模拟数据工厂
 * 为所有测试用例提供一致的测试数据构造工具
 */

import type { ChatMessage, AssistantThoughtSegment, AssistantReplySegment, ToolEventMeta, ConversationSessionSummary } from '../../features/chat/types'
import type { ChatStreamEvent, ChatResponsePayload } from '../../shared/api/api'
import type { BillingModelConfiguration } from '../../shared/types/api'
import type { ModelOption } from '../../features/chat/store/chatStore'

/** 生成唯一 ID */
let _counter = 0
function uid(prefix = 'test'): string {
  return `${prefix}-${Date.now()}-${++_counter}`
}

// ===== 聊天消息 fixtures =====

export function createTestUserMessage(content = '你好，这是一条测试消息'): ChatMessage {
  return {
    id: uid('msg'),
    role: 'user',
    content,
    timestamp: new Date(),
  }
}

export function createTestAssistantReply(content = '好的，已收到你的消息。'): ChatMessage {
  const segments: (AssistantThoughtSegment | AssistantReplySegment)[] = [
    {
      kind: 'reply' as const,
      content,
    },
  ]
  return {
    id: uid('msg'),
    role: 'assistant',
    content,
    timestamp: new Date(),
    segments,
  }
}

export function createTestAssistantThought(reasoningContent: string, toolEvents: ToolEventMeta[] = []): ChatMessage {
  const segments: (AssistantThoughtSegment | AssistantReplySegment)[] = [
    {
      kind: 'thought' as const,
      reasoningContent,
      toolEvents,
      steps: [],
      usage: { tokens: 500, cost: 0.005, duration: 1500 },
    },
    {
      kind: 'reply' as const,
      content: '基于以上分析，这是我的回答。',
    },
  ]
  return {
    id: uid('msg'),
    role: 'assistant',
    content: '基于以上分析，这是我的回答。',
    reasoning_content: reasoningContent,
    timestamp: new Date(),
    toolEvents,
    segments,
  }
}

export function createTestToolEvent(name = 'search', status: 'completed' | 'running' | 'error' = 'completed'): ToolEventMeta {
  return {
    id: uid('tool'),
    kind: 'tool_call',
    name,
    status,
    detail: `执行工具: ${name}`,
    input: { query: '测试查询' },
    output: status === 'completed' ? { results: ['结果1', '结果2'] } : undefined,
  }
}

// ===== 会话 fixtures =====

export function createTestConversationSummary(
  sessionId = uid('sess'),
  title = '测试会话',
  messageCount = 5,
): ConversationSessionSummary {
  const now = new Date().toISOString()
  return {
    session_id: sessionId,
    user_id: 'test-user-001',
    title,
    summary: `${title}的摘要内容`,
    last_message_preview: '最后一条消息的预览...',
    last_message_role: 'assistant',
    message_count: messageCount,
    created_at: now,
    updated_at: now,
    last_message_at: now,
    deleted_at: null,
    restored_at: null,
    purge_after: null,
    conversation_metadata: {},
  }
}

// ===== API 响应 fixtures =====

export function createTestChatResponse(content = 'AI 回复内容'): ChatResponsePayload {
  return {
    status: 'success',
    response: content,
    reasoning_content: null,
    session_id: uid('sess'),
    error: null,
    request_id: uid('req'),
  }
}

export function createTestChatStreamEvent(type = 'chunk', content = '流式内容片段'): ChatStreamEvent {
  return {
    type,
    content,
    reasoning_content: null,
    message: null,
    result: null,
    task: null,
    tool: null,
    usage: null,
    team: null,
  }
}

export function createTestErrorResponse(statusCode = 400, message = '请求参数错误') {
  return {
    error: {
      code: `http_${statusCode}`,
      message,
      status_code: statusCode,
    },
  }
}

// ===== 模型配置 fixtures =====

export function createTestModelOption(
  provider = 'openai',
  model = 'gpt-4o',
  displayName = 'GPT-4o',
): ModelOption {
  return {
    id: `${provider}:${model}`,
    provider,
    model,
    display_name: displayName,
  }
}

export function createTestBillingModelConfig(
  provider = 'openai',
  model = 'gpt-4o',
): BillingModelConfiguration {
  return {
    id: 1,
    provider,
    model,
    display_name: model.toUpperCase(),
    description: `${provider} 的 ${model} 模型`,
    icon: null,
    api_endpoint: `https://api.${provider}.com/v1`,
    api_key: 'test-api-key-placeholder',
    has_api_key: true,
    selected_models: [model],
    is_active: true,
    is_default: provider === 'openai',
    sort_order: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }
}

// ===== Store 状态 fixtures =====

export function createTestChatStoreState() {
  return {
    messages: [
      createTestUserMessage('你好'),
      createTestAssistantReply('你好！有什么可以帮助你的？'),
    ],
    conversations: [
      createTestConversationSummary('sess-1', '第一个会话'),
      createTestConversationSummary('sess-2', '第二个会话', 3),
    ],
    conversationsTotal: 2,
    conversationsHasMore: false,
    sessionId: 'sess-1',
    isLoading: false,
    outputMode: 'stream' as const,
    thinkingEnabled: false,
    thinkingDepth: 3,
    selectedModel: 'openai:gpt-4o',
    modelOptions: [
      createTestModelOption('openai', 'gpt-4o'),
      createTestModelOption('openai', 'gpt-4o-mini', 'GPT-4o Mini'),
      createTestModelOption('deepseek', 'deepseek-chat', 'DeepSeek Chat'),
    ],
    modelLoading: false,
    modelError: null,
  }
}

export function createTestAuthStoreState() {
  return {
    user: { username: 'testuser' },
    token: 'test-jwt-token-xxxxx',
    isAuthenticated: true,
    isInitialized: true,
  }
}

export function createTestThemeStoreState() {
  return {
    theme: 'light' as const,
    config: {
      fontFamily: 'Inter',
      fontSize: '14px',
      themeColor: '#4f46e5',
      backgroundImage: '',
      logoIcon: '',
    },
  }
}
