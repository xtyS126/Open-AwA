import { useState, useRef, useEffect, useCallback } from 'react'
import { chatAPI } from '../services/api'
import { modelsAPI, ModelConfiguration } from '../services/modelsApi'
import { useChatStore } from '../stores/chatStore'
import { appLogger } from '../services/logger'
import './ChatPage.css'

function ChatPage() {
  const [input, setInput] = useState('')
  const { messages, addMessage, setLoading, isLoading, clearMessages, sessionId } = useChatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [configurations, setConfigurations] = useState<ModelConfiguration[]>([])
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
      const response = await modelsAPI.getConfigurations()
      setConfigurations(response.data.configurations || [])
      
      const savedModel = localStorage.getItem('selected_model')
      if (savedModel && response.data.configurations) {
        const exists = response.data.configurations.some(
          (c: ModelConfiguration) => `${c.provider}:${c.model}` === savedModel
        )
        if (exists) {
          setSelectedModel(savedModel)
        } else {
          const defaultConfig = response.data.configurations.find(
            (c: ModelConfiguration) => c.is_default
          )
          if (defaultConfig) {
            setSelectedModel(`${defaultConfig.provider}:${defaultConfig.model}`)
          } else if (response.data.configurations.length > 0) {
            const firstConfig = response.data.configurations[0]
            setSelectedModel(`${firstConfig.provider}:${firstConfig.model}`)
          }
        }
      } else {
        const defaultConfig = response.data.configurations?.find(
          (c: ModelConfiguration) => c.is_default
        )
        if (defaultConfig) {
          setSelectedModel(`${defaultConfig.provider}:${defaultConfig.model}`)
        } else if (response.data.configurations?.length > 0) {
          const firstConfig = response.data.configurations[0]
          setSelectedModel(`${firstConfig.provider}:${firstConfig.model}`)
        }
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
      extra: { session_id: sessionId, input_length: userMessage.length },
    })
    setInput('')
    addMessage('user', userMessage)
    setLoading(true)

    try {
      const { provider, model } = parseSelectedModel(selectedModel)
      const response = await chatAPI.sendMessage(userMessage, sessionId, provider, model)
      const assistantText = response.data.response
      const backendError = response.data.error

      if (assistantText && assistantText.trim()) {
        addMessage('assistant', assistantText)
      } else if (backendError?.message) {
        addMessage('assistant', `请求失败：${backendError.message}`)
      } else {
        addMessage('assistant', '抱歉，当前未返回有效内容，请稍后重试。')
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
      const [provider, model] = selectedModel.split(':')
      const config = configurations.find(
        (c: ModelConfiguration) => c.provider === provider && c.model === model
      )
      
      if (config) {
        await modelsAPI.updateConfiguration(config.id, { is_default: true })
        appLogger.info({
          event: 'chat_model_save',
          module: 'chat_page',
          action: 'save_default_model',
          status: 'success',
          message: 'default model saved',
          extra: { provider, model },
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

  const formatModelLabel = (config: ModelConfiguration) => {
    const providerNames: Record<string, string> = {
      openai: 'OpenAI',
      anthropic: 'Anthropic',
      google: 'Google',
      deepseek: 'DeepSeek',
      alibaba: '阿里',
      moonshot: 'Kimi',
      zhipu: '智谱'
    }
    return `${providerNames[config.provider] || config.provider} - ${config.display_name || config.model}`
  }

  return (
    <div className="chat-page">
      <div className="chat-header">
        <h1>AI 助手</h1>
        <div className="model-selector">
          <select
            value={selectedModel}
            onChange={handleModelChange}
            disabled={loadingModels || !!error}
            className="model-select"
          >
            {loadingModels ? (
              <option value="">加载中...</option>
            ) : configurations.length === 0 ? (
              <option value="">暂无可用模型</option>
            ) : (
              configurations.map((config) => (
                <option
                  key={config.id}
                  value={`${config.provider}:${config.model}`}
                >
                  {formatModelLabel(config)}
                </option>
              ))
            )}
          </select>
          {selectedModel && (
            <button
              className={`btn btn-save-model ${saveSuccess ? 'success' : ''}`}
              onClick={handleSaveModel}
              disabled={!selectedModel}
            >
              {saveSuccess ? '✓ 已保存' : '保存模型'}
            </button>
          )}
        </div>
        {error && (
          <div className="model-error">
            <span>{error}</span>
            {retryCount < 3 && (
              <button className="btn btn-retry" onClick={handleRetry}>
                重试 ({3 - retryCount})
              </button>
            )}
          </div>
        )}
        <button className="btn btn-secondary" onClick={clearMessages}>
          新对话
        </button>
      </div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>你好！有什么可以帮助你的吗？</p>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`message ${message.role === 'user' ? 'user' : 'assistant'}`}
          >
            <div className="message-content">
              <p>{message.content}</p>
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="message assistant">
            <div className="message-content">
              <p className="loading-text">思考中...</p>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-container">
        <textarea
          className="chat-input"
          placeholder="输入你的问题..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          rows={1}
        />
        <button
          className="btn btn-primary send-btn"
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
