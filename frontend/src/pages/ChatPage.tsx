import { useState, useRef, useEffect } from 'react'
import { chatAPI } from '../services/api'
import { modelsAPI, ModelConfiguration } from '../services/modelsApi'
import { useChatStore } from '../stores/chatStore'
import './ChatPage.css'

function ChatPage() {
  const [input, setInput] = useState('')
  const { messages, addMessage, setLoading, isLoading, clearMessages } = useChatStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [configurations, setConfigurations] = useState<ModelConfiguration[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [loadingModels, setLoadingModels] = useState(false)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  useEffect(() => {
    loadConfigurations()
  }, [])

  const loadConfigurations = async () => {
    setLoadingModels(true)
    try {
      const response = await modelsAPI.getConfigurations()
      setConfigurations(response.data.configurations || [])
      const defaultConfig = response.data.configurations?.find(
        (c: ModelConfiguration) => c.is_default
      )
      if (defaultConfig) {
        setSelectedModel(`${defaultConfig.provider}:${defaultConfig.model}`)
      } else if (response.data.configurations?.length > 0) {
        const firstConfig = response.data.configurations[0]
        setSelectedModel(`${firstConfig.provider}:${firstConfig.model}`)
      }
    } catch (error) {
      console.error('Failed to load configurations')
    } finally {
      setLoadingModels(false)
    }
  }

  const handleSend = async () => {
    if (!input.trim() || isLoading) return

    const userMessage = input.trim()
    setInput('')
    addMessage('user', userMessage)
    setLoading(true)

    try {
      const response = await chatAPI.sendMessage(userMessage)
      addMessage('assistant', response.data.response)
    } catch (error) {
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
            disabled={loadingModels}
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
        </div>
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
