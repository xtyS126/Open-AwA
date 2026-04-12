import { useState, useRef, useEffect, useCallback } from 'react'
import { chatAPI } from '@/shared/api/api'
import { modelsAPI } from '@/features/settings/modelsApi'
import { useChatStore } from '@/features/chat/store/chatStore'
import { useAuthStore } from '@/shared/store/authStore'
import { appLogger } from '@/shared/utils/logger'
import { ReasoningContent } from './components/ReasoningContent'
import styles from './ChatPage.module.css'

function sanitizeDisplayedError(message: string): string {
  return String(message || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function ChatPage() {
  const [input, setInput] = useState('')
  const { messages, addMessage, updateLastMessage, setLoading, isLoading, clearMessages, sessionId, outputMode, setOutputMode } = useChatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [configurations, setConfigurations] = useState<{ id: string; provider: string; model: string; display_name: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [retryCount, setRetryCount] = useState(0)
  const retryTimeoutRef = useRef<number | null>(null)
  const retryCountRef = useRef(0)
  const activeRequestIdRef = useRef(0)
  const activeAbortControllerRef = useRef<AbortController | null>(null)
  const isMountedRef = useRef(true)

  // Buffer references for background throttling
  const bufferRef = useRef({
    content: '',
    reasoning: '',
    lastUpdateTime: Date.now()
  })

  const flushBuffer = useCallback(() => {
    if (bufferRef.current.content || bufferRef.current.reasoning) {
      updateLastMessage(bufferRef.current.content, bufferRef.current.reasoning)
      bufferRef.current.content = ''
      bufferRef.current.reasoning = ''
      bufferRef.current.lastUpdateTime = Date.now()
    }
  }, [updateLastMessage])

  const scrollToBottom = useCallback(() => {
    if (document.hidden) return
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      if (retryTimeoutRef.current !== null) {
        window.clearTimeout(retryTimeoutRef.current)
        retryTimeoutRef.current = null
      }
      activeAbortControllerRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        flushBuffer()
        // Adding a slight delay to ensure DOM is updated before scrolling
        setTimeout(scrollToBottom, 50)
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [flushBuffer, scrollToBottom])

  const loadConfigurations = useCallback(async () => {
    setError(null)
    
    try {
      const response = await modelsAPI.getProviders()
      const providersList = response.data.providers || []
      
      const flatConfigs: { id: string; provider: string; model: string; display_name: string }[] = []
      providersList.forEach((provider: { id: string; selected_models?: string[]; display_name?: string; name?: string }) => {
        const selected = provider.selected_models || []
        selected.forEach((modelName: string) => {
          flatConfigs.push({
            id: `${provider.id}:${modelName}`,
            provider: provider.id,
            model: modelName,
            display_name: `${provider.display_name || provider.name || provider.id} - ${modelName}`
          })
        })
      })

      if (!isMountedRef.current) {
        return
      }
      setConfigurations(flatConfigs)
      
      retryCountRef.current = 0
      if (isMountedRef.current) {
        setRetryCount(0)
      }
    } catch (err) {
      if (!isMountedRef.current) {
        return
      }
      appLogger.error({
        event: 'chat_model_load',
        module: 'chat_page',
        action: 'load_configurations',
        status: 'failure',
        message: 'failed to load model configurations',
        extra: { error: err instanceof Error ? err.message : String(err) },
      })
      setError('加载模型失败，请检查网络连接')
      
      if (retryCountRef.current < 3) {
        const nextRetry = retryCountRef.current + 1
        retryCountRef.current = nextRetry
        setRetryCount(nextRetry)
        retryTimeoutRef.current = window.setTimeout(() => {
          void loadConfigurations()
        }, 1000 * nextRetry)
      }
    }
  }, [])

  const { isAuthenticated } = useAuthStore()

  useEffect(() => {
    appLogger.info({
      event: 'page_view',
      module: 'chat_page',
      action: 'mount',
      status: 'success',
      message: 'chat page mounted',
    })
    if (isAuthenticated) {
      void loadConfigurations()
    }
  }, [loadConfigurations, isAuthenticated])

  const handleSend = async () => {
    if (!input.trim() || isLoading) return

    const userMessage = input.trim()
    const requestId = activeRequestIdRef.current + 1
    activeRequestIdRef.current = requestId
    activeAbortControllerRef.current?.abort()
    const abortController = new AbortController()
    activeAbortControllerRef.current = abortController
    let streamErrorHandled = false
    appLogger.info({
      event: 'chat_send',
      module: 'chat_page',
      action: 'send_message',
      status: 'start',
      message: 'chat send started',
      extra: { session_id: sessionId, input_length: userMessage.length, mode: outputMode },
    })
    setInput('')
    addMessage('user', userMessage)
    setLoading(true)

    try {
      const defaultModel = configurations.length > 0 ? configurations[0] : null
      const { provider, model } = defaultModel
        ? { provider: defaultModel.provider, model: defaultModel.model }
        : { provider: undefined, model: undefined }

      if (outputMode === 'stream') {
        let isFirstChunk = true
        bufferRef.current = { content: '', reasoning: '', lastUpdateTime: Date.now() }

        await chatAPI.sendMessageStream(
          userMessage,
          sessionId,
          provider,
          model,
          (content, reasoning) => {
            if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
              return
            }
            if (isFirstChunk) {
              setLoading(false)
              addMessage('assistant', content, reasoning)
              isFirstChunk = false
              bufferRef.current.lastUpdateTime = Date.now()
            } else {
              if (document.hidden) {
                // Background mode: throttle updates to prevent massive DOM manipulation
                bufferRef.current.content += content
                bufferRef.current.reasoning += reasoning
                const now = Date.now()
                if (now - bufferRef.current.lastUpdateTime > 1000) {
                  flushBuffer()
                }
              } else {
                // Foreground mode: instant update
                // If there's any remaining buffer, flush it with the new chunk
                if (bufferRef.current.content || bufferRef.current.reasoning) {
                  updateLastMessage(
                    bufferRef.current.content + content,
                    bufferRef.current.reasoning + reasoning
                  )
                  bufferRef.current.content = ''
                  bufferRef.current.reasoning = ''
                  bufferRef.current.lastUpdateTime = Date.now()
                } else {
                  updateLastMessage(content, reasoning)
                }
              }
            }
          },
          (error) => {
            if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
              return
            }
            streamErrorHandled = true
            flushBuffer()
            appLogger.error({
              event: 'chat_stream_error',
              module: 'chat_page',
              action: 'receive_stream',
              status: 'failure',
              message: 'chat stream error',
              extra: { error: error instanceof Error ? error.message : String(error) },
            })
            if (isFirstChunk) {
              setLoading(false)
              addMessage('assistant', `请求失败：${sanitizeDisplayedError(error.message)}`)
              isFirstChunk = false
            } else {
              updateLastMessage(`\n\n[流中断：${sanitizeDisplayedError(error.message)}]`)
            }
          },
          { signal: abortController.signal }
        )
        // Stream completed successfully, flush any remaining buffered data
        flushBuffer()

        if (!isMountedRef.current || activeRequestIdRef.current !== requestId || streamErrorHandled) {
          return
        }
      } else {
        const response = await chatAPI.sendMessage(userMessage, sessionId, provider, model, 'direct', {
          signal: abortController.signal,
        })
        if (!isMountedRef.current || activeRequestIdRef.current !== requestId) {
          return
        }
        const assistantText = response.data.response
        const backendError = response.data.error
        const reasoningContent = response.data.reasoning_content

        if (assistantText && assistantText.trim()) {
          addMessage('assistant', assistantText, reasoningContent || undefined)
        } else if (backendError?.message) {
          addMessage('assistant', `请求失败：${sanitizeDisplayedError(backendError.message)}`)
        } else {
          addMessage('assistant', '抱歉，当前未返回有效内容，请稍后重试。')
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }
      appLogger.error({
        event: 'chat_send',
        module: 'chat_page',
        action: 'send_message',
        status: 'failure',
        message: 'chat send failed',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      if (isMountedRef.current && activeRequestIdRef.current === requestId && !streamErrorHandled) {
        addMessage('assistant', '抱歉，发生了错误。请稍后重试。')
      }
    } finally {
      if (isMountedRef.current && activeRequestIdRef.current === requestId) {
        setLoading(false)
      }
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleRetry = () => {
    if (retryTimeoutRef.current !== null) {
      window.clearTimeout(retryTimeoutRef.current)
      retryTimeoutRef.current = null
    }
    retryCountRef.current = 0
    setRetryCount(0)
    void loadConfigurations()
  }

  return (
    <div className={styles['chat-page']}>
      <div className={styles['chat-header']}>
        <h1>AI 助手</h1>
        <div className={styles['model-selector']}>
          <select
            value={outputMode}
            onChange={(e) => setOutputMode(e.target.value as 'stream' | 'direct')}
            className={styles['model-select']}
          >
            <option value="stream">流式传输</option>
            <option value="direct">直接输出</option>
          </select>
          <span className={styles['model-hint']}>模型：使用设置中的默认模型</span>
        </div>
        {error && (
          <div className={styles['model-error']}>
            <span>{error}</span>
            {retryCount < 3 && (
              <button className={`btn ${styles['btn-retry']}`} onClick={handleRetry}>
                重试 ({3 - retryCount})
              </button>
            )}
          </div>
        )}
        <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={clearMessages}>
          新对话
        </button>
      </div>

      <div className={styles['chat-messages']}>
        {messages.length === 0 && (
          <div className={styles['chat-empty']}>
            <p>你好！有什么可以帮助你的吗？</p>
          </div>
        )}

        {messages.map((message, index) => {
          const isLastMessage = index === messages.length - 1
          const isCurrentlyStreaming = isLoading && isLastMessage && message.role === 'assistant'
          
          return (
            <div
              key={message.id}
              className={`${styles['message']} ${message.role === 'user' ? styles['user'] : styles['assistant']}`}
            >
              <div className={styles['message-content']}>
                {message.reasoning_content && (
                  <ReasoningContent 
                    messageId={message.id}
                    content={message.reasoning_content}
                    isStreaming={isCurrentlyStreaming}
                  />
                )}
                <p>{message.content}</p>
              </div>
            </div>
          )
        })}

        {isLoading && (
          <div className={`${styles['message']} ${styles['assistant']}`}>
            <div className={styles['message-content']}>
              <p className={styles['loading-text']}>思考中...</p>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className={styles['chat-input-container']}>
        <textarea
          className={styles['chat-input']}
          placeholder="输入你的问题..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          rows={1}
        />
        <button
          className={`btn btn-primary ${styles['send-btn']}`}
          onClick={handleSend}
          disabled={!input.trim() || isLoading}
        >
          发送
        </button>
      </div>
    </div>
  )
}

export default ChatPage
