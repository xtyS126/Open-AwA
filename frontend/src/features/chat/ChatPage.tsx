import { useState, useRef, useEffect, useCallback } from 'react'
import { chatAPI } from '@/shared/api/api'
import { modelsAPI } from '@/features/settings/modelsApi'
import { useChatStore } from '@/features/chat/store/chatStore'
import { appLogger } from '@/shared/utils/logger'
import styles from './ChatPage.module.css'

function ChatPage() {
  const [input, setInput] = useState('')
  const { messages, addMessage, updateLastMessage, setLoading, isLoading, clearMessages, sessionId, outputMode, setOutputMode } = useChatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [configurations, setConfigurations] = useState<{ id: string; provider: string; model: string; display_name: string }[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [loadingModels, setLoadingModels] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [retryCount, setRetryCount] = useState(0)
  const [saveSuccess, setSaveSuccess] = useState(false)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  const loadConfigurations = useCallback(async () => {
    setLoadingModels(true)
    setError(null)
    
    try {
      const response = await modelsAPI.getProviders()
      const providersList = response.data.providers || []
      
      const flatConfigs: { id: string; provider: string; model: string; display_name: string }[] = []
      providersList.forEach((provider: any) => {
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
      
      setConfigurations(flatConfigs)
      
      const savedModel = localStorage.getItem('selected_model')
      if (savedModel && flatConfigs.length > 0) {
        const exists = flatConfigs.some(c => c.id === savedModel)
        if (exists) {
          setSelectedModel(savedModel)
        } else {
          setSelectedModel(flatConfigs[0].id)
        }
      } else if (flatConfigs.length > 0) {
        setSelectedModel(flatConfigs[0].id)
      }
      
      setRetryCount(0)
    } catch (err) {
      appLogger.error({
        event: 'chat_model_load',
        module: 'chat_page',
        action: 'load_configurations',
        status: 'failure',
        message: 'failed to load model configurations',
        extra: { error: err instanceof Error ? err.message : String(err) },
      })
      setError('加载模型失败，请检查网络连接')
      
      if (retryCount < 3) {
        const nextRetry = retryCount + 1
        setRetryCount(nextRetry)
        setTimeout(() => {
          loadConfigurations()
        }, 1000 * nextRetry)
      }
    } finally {
      setLoadingModels(false)
    }
  }, [retryCount])

  useEffect(() => {
    appLogger.info({
      event: 'page_view',
      module: 'chat_page',
      action: 'mount',
      status: 'success',
      message: 'chat page mounted',
    })
    loadConfigurations()
  }, [])

  const parseSelectedModel = (value: string): { provider?: string; model?: string } => {
    if (!value) {
      return { provider: undefined, model: undefined }
    }

    const separatorIndex = value.indexOf(':')
    if (separatorIndex <= 0 || separatorIndex >= value.length - 1) {
      return { provider: undefined, model: undefined }
    }

    return {
      provider: value.slice(0, separatorIndex),
      model: value.slice(separatorIndex + 1)
    }
  }

  const handleSend = async () => {
    if (!input.trim() || isLoading) return

    const userMessage = input.trim()
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
      const { provider, model } = parseSelectedModel(selectedModel)

      if (outputMode === 'stream') {
        let isFirstChunk = true
        await chatAPI.sendMessageStream(
          userMessage,
          sessionId,
          provider,
          model,
          (content, reasoning) => {
            if (isFirstChunk) {
              setLoading(false)
              addMessage('assistant', content, reasoning)
              isFirstChunk = false
            } else {
              updateLastMessage(content, reasoning)
            }
          },
          (error) => {
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
              addMessage('assistant', `请求失败：${error.message}`)
              isFirstChunk = false
            } else {
              updateLastMessage(`\n\n[流中断：${error.message}]`)
            }
          }
        )
      } else {
        const response = await chatAPI.sendMessage(userMessage, sessionId, provider, model, 'direct')
        const assistantText = response.data.response
        const backendError = response.data.error

        if (assistantText && assistantText.trim()) {
          addMessage('assistant', assistantText)
        } else if (backendError?.message) {
          addMessage('assistant', `请求失败：${backendError.message}`)
        } else {
          addMessage('assistant', '抱歉，当前未返回有效内容，请稍后重试。')
        }
      }
    } catch (error) {
      appLogger.error({
        event: 'chat_send',
        module: 'chat_page',
        action: 'send_message',
        status: 'failure',
        message: 'chat send failed',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      addMessage('assistant', '抱歉，发生了错误。请稍后重试。')
    } finally {
      setLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleModelChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedModel(e.target.value)
    localStorage.setItem('selected_model', e.target.value)
    setSaveSuccess(false)
  }

  const handleSaveModel = async () => {
    if (!selectedModel) return
    
    try {
      const config = configurations.find(
        (c) => c.id === selectedModel
      )
      
      if (config) {
        // Just save to localStorage as we don't have a specific is_default flag for a single model string
        // inside the selected_models array in backend yet.
        appLogger.info({
          event: 'chat_model_save',
          module: 'chat_page',
          action: 'save_default_model',
          status: 'success',
          message: 'default model saved locally',
          extra: { provider: config.provider, model: config.model },
        })
        setSaveSuccess(true)
        setTimeout(() => setSaveSuccess(false), 3000)
        localStorage.setItem('selected_model', selectedModel)
      }
    } catch (err) {
      appLogger.error({
        event: 'chat_model_save',
        module: 'chat_page',
        action: 'save_default_model',
        status: 'failure',
        message: 'failed to save default model',
        extra: { error: err instanceof Error ? err.message : String(err) },
      })
      setError('保存模型失败')
    }
  }

  const handleRetry = () => {
    setRetryCount(0)
    loadConfigurations()
  }

  const formatModelLabel = (config: { display_name: string }) => {
    return config.display_name
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
            style={{ marginRight: '10px' }}
          >
            <option value="stream">流式传输</option>
            <option value="direct">直接输出</option>
          </select>
          <select
            value={selectedModel}
            onChange={handleModelChange}
            disabled={loadingModels || !!error}
            className={styles['model-select']}
          >
            {loadingModels ? (
              <option value="">加载中...</option>
            ) : configurations.length === 0 ? (
              <option value="">暂无可用模型</option>
            ) : (
              configurations.map((config) => (
                <option
                  key={config.id}
                  value={config.id}
                >
                  {formatModelLabel(config)}
                </option>
              ))
            )}
          </select>
          {selectedModel && (
            <button
              className={`btn ${styles['btn-save-model']} ${saveSuccess ? styles['success'] : ''}`}
              onClick={handleSaveModel}
              disabled={!selectedModel}
            >
              {saveSuccess ? '已保存' : '保存模型'}
            </button>
          )}
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

        {messages.map((message) => (
          <div
            key={message.id}
            className={`${styles['message']} ${message.role === 'user' ? styles['user'] : styles['assistant']}`}
          >
            <div className={styles['message-content']}>
              {message.reasoning_content && (
                <div className={styles['reasoning-content']} style={{
                  padding: '8px 12px',
                  marginBottom: '8px',
                  backgroundColor: 'rgba(0,0,0,0.05)',
                  borderLeft: '4px solid #888',
                  color: '#666',
                  fontStyle: 'italic',
                  fontSize: '0.9em',
                  borderRadius: '4px'
                }}>
                  {message.reasoning_content}
                </div>
              )}
              <p>{message.content}</p>
            </div>
          </div>
        ))}

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
