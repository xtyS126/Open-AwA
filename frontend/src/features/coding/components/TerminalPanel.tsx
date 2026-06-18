/**
 * 终端面板组件 — 提供命令输入和输出展示。
 * 使用简单的 div/input 模拟终端界面，不依赖 xterm.js。
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { Terminal, Trash2, X } from 'lucide-react'
import { createSession, executeCommand, closeSession, type CommandResult } from '@/shared/api/terminalApi'
import styles from './TerminalPanel.module.css'

interface TerminalPanelProps {
  cwd?: string
  onClose?: () => void
}

interface OutputLine {
  type: 'command' | 'stdout' | 'stderr' | 'error'
  text: string
}

/** 终端面板组件，提供命令输入和输出展示 */
export default function TerminalPanel({ cwd, onClose }: TerminalPanelProps) {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [outputs, setOutputs] = useState<OutputLine[]>([])
  const [history, setHistory] = useState<string[]>([])
  const [historyIndex, setHistoryIndex] = useState(-1)
  const [loading, setLoading] = useState(false)
  const outputRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // 初始化终端会话
  useEffect(() => {
    let mounted = true
    const init = async () => {
      try {
        const result = await createSession(cwd)
        if (mounted && result.ok && result.session_id) {
          setSessionId(result.session_id)
          setOutputs([{ type: 'stdout', text: `终端会话已创建 (cwd: ${result.cwd || '默认目录'})` }])
        }
      } catch (e) {
        if (mounted) {
          setOutputs([{ type: 'error', text: `终端会话创建失败: ${e}` }])
        }
      }
    }
    init()
    return () => {
      mounted = false
      if (sessionId) {
        closeSession(sessionId).catch(() => {})
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 自动滚动到底部
  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [outputs])

  // 执行命令
  const handleExecute = useCallback(async () => {
    const command = input.trim()
    if (!command || !sessionId || loading) return

    setInput('')
    setHistory(prev => [...prev, command])
    setHistoryIndex(-1)
    setLoading(true)

    setOutputs(prev => [...prev, { type: 'command', text: `$ ${command}` }])

    try {
      const result: CommandResult = await executeCommand(sessionId, command)
      if (result.ok) {
        if (result.stdout) {
          setOutputs(prev => [...prev, { type: 'stdout', text: result.stdout }])
        }
        if (result.stderr) {
          setOutputs(prev => [...prev, { type: 'stderr', text: result.stderr }])
        }
        if (result.exit_code !== undefined && result.exit_code !== 0) {
          setOutputs(prev => [...prev, { type: 'error', text: `退出码: ${result.exit_code}` }])
        }
      } else {
        setOutputs(prev => [...prev, { type: 'error', text: result.error || '执行失败' }])
      }
    } catch (e) {
      setOutputs(prev => [...prev, { type: 'error', text: `执行异常: ${e}` }])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }, [input, sessionId, loading])

  // 键盘事件处理
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleExecute()
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (history.length > 0) {
        const newIndex = historyIndex === -1 ? history.length - 1 : Math.max(0, historyIndex - 1)
        setHistoryIndex(newIndex)
        setInput(history[newIndex])
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (historyIndex !== -1) {
        const newIndex = historyIndex + 1
        if (newIndex >= history.length) {
          setHistoryIndex(-1)
          setInput('')
        } else {
          setHistoryIndex(newIndex)
          setInput(history[newIndex])
        }
      }
    } else if (e.key === 'l' && e.ctrlKey) {
      e.preventDefault()
      setOutputs([])
    }
  }

  // 清空输出
  const handleClear = () => {
    setOutputs([])
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.title}>
          <Terminal size={14} />
          <span>终端</span>
        </div>
        <div className={styles.actions}>
          <button className={styles.actionBtn} onClick={handleClear} title="清空">
            <Trash2 size={14} />
          </button>
          {onClose && (
            <button className={styles.actionBtn} onClick={onClose} title="关闭">
              <X size={14} />
            </button>
          )}
        </div>
      </div>
      <div className={styles.output} ref={outputRef}>
        {outputs.map((line, i) => (
          <div key={i} className={`${styles.line} ${styles[line.type]}`}>
            <pre>{line.text}</pre>
          </div>
        ))}
        {loading && <div className={styles.loading}>执行中...</div>}
      </div>
      <div className={styles.inputRow}>
        <span className={styles.prompt}>$</span>
        <input
          ref={inputRef}
          className={styles.input}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入命令..."
          disabled={!sessionId || loading}
          autoFocus
        />
      </div>
    </div>
  )
}
