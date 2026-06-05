/**
 * Coding 聊天面板 — 上下文感知的 AI 编码助手。
 * 支持分析、解释、重构、生成测试等代码操作。
 */
import React, { useState, useCallback, useRef } from 'react'
import { Send, Code, GitBranch, Bug, ScrollText } from 'lucide-react'
import { useCodingStore } from '../store/codingStore'
import { useChatStore } from '@/features/chat/store/chatStore'
import { chatAPI } from '@/features/chat/chatApi'
import styles from './CodingChatPanel.module.css'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

const QUICK_ACTIONS = [
  { icon: Code, label: '解释代码', prompt: '请解释当前文件的代码结构和逻辑' },
  { icon: GitBranch, label: '重构建议', prompt: '请分析当前文件并给出重构建议' },
  { icon: Bug, label: '查找问题', prompt: '请检查当前文件中的潜在bug和问题' },
  { icon: ScrollText, label: '生成测试', prompt: '请为当前文件中的函数生成单元测试' },
]

const CodingChatPanel: React.FC = () => {
  const { activeFilePath, openFiles } = useCodingStore()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  const activeFile = openFiles.find((f) => f.path === activeFilePath)

  const handleSend = useCallback(async (text?: string) => {
    const messageText = text || input.trim()
    if (!messageText || isLoading) return

    const contextInfo = activeFile
      ? `\n\n[当前文件: ${activeFile.path}]\n\`\`\`\n${activeFile.content.slice(0, 3000)}\n\`\`\``
      : ''

    const fullMessage = messageText + contextInfo
    setMessages((prev) => [...prev, { role: 'user', content: messageText }])
    setInput('')
    setIsLoading(true)

    try {
      const sessionId = `coding-${Date.now()}`
      let responseText = ''

      await chatAPI.sendMessageStream(
        fullMessage,
        sessionId,
        (chunk: string) => {
          responseText += chunk
        },
        () => {},
        () => {},
      )
      setMessages((prev) => [...prev, { role: 'assistant', content: responseText }])
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: '处理请求时出错，请重试。' }])
    } finally {
      setIsLoading(false)
    }
  }, [input, isLoading, activeFile])

  const handleQuickAction = useCallback((prompt: string) => {
    handleSend(prompt)
  }, [handleSend])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <span>Coding 助手</span>
        {activeFile && (
          <span className={styles.activeFile}>{activeFile.name}</span>
        )}
      </div>

      <div className={styles.messages}>
        {messages.length === 0 && (
          <div className={styles.empty}>
            <p>向 Coding 助手提问，获取代码帮助</p>
            <div className={styles.quickActions}>
              {QUICK_ACTIONS.map((action) => (
                <button
                  key={action.label}
                  className={styles.quickBtn}
                  onClick={() => handleQuickAction(action.prompt)}
                >
                  <action.icon size={14} />
                  <span>{action.label}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`${styles.msg} ${styles[msg.role]}`}>
            <div className={styles.msgContent}>{msg.content}</div>
          </div>
        ))}
        {isLoading && <div className={styles.loading}>助手正在思考...</div>}
        <div ref={chatEndRef} />
      </div>

      <div className={styles.inputArea}>
        <textarea
          className={styles.textarea}
          placeholder="向 Agent 提问（例如：'分析此文件的架构'）..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={3}
        />
        <button
          className={styles.sendBtn}
          onClick={() => handleSend()}
          disabled={isLoading || !input.trim()}
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  )
}

export default React.memo(CodingChatPanel)
