/**
 * 流式消息缓冲 Hook。
 *
 * 将 SSE chunk 的即时写入改为内存缓冲 + requestAnimationFrame 批量刷新，
 * 大幅降低流式过程中的状态更新频率和主线程压力。
 */
import { useRef, useCallback, useEffect } from 'react'

interface StreamBufferOptions {
  /** 消息更新回调：(messageId, contentDelta, reasoningDelta) => void */
  onFlush: (messageId: string, content: string, reasoning: string) => void
  /** 缓冲刷新间隔（ms），默认 50ms */
  flushInterval?: number
}

interface StreamBuffer {
  /** 写入一个 chunk 到缓冲区 */
  write: (messageId: string, content: string, reasoning?: string) => void
  /** 强制立即刷新缓冲区 */
  flush: (messageId?: string) => void
}

export function useStreamBuffer({ onFlush, flushInterval = 50 }: StreamBufferOptions): StreamBuffer {
  const bufferRef = useRef<Map<string, { content: string; reasoning: string }>>(new Map())
  const rafIdRef = useRef<number | null>(null)
  const lastFlushRef = useRef<number>(0)
  const onFlushRef = useRef(onFlush)
  // 在 useEffect 中更新 ref，避免在 render 阶段修改 ref 违反 React 纯渲染规则
  useEffect(() => {
    onFlushRef.current = onFlush
  })

  const doFlush = useCallback((messageId?: string) => {
    const buffer = bufferRef.current
    if (buffer.size === 0) return

    const entries = messageId
      ? [[messageId, buffer.get(messageId)] as const].filter(([, v]) => v !== undefined)
      : Array.from(buffer.entries())

    for (const [msgId, data] of entries) {
      if (data && (data.content || data.reasoning)) {
        onFlushRef.current(msgId, data.content, data.reasoning)
      }
    }

    if (messageId) {
      buffer.delete(messageId)
    } else {
      buffer.clear()
    }
    lastFlushRef.current = performance.now()
  }, [])

  const scheduleFlush = useCallback((messageId?: string) => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current)
    }
    rafIdRef.current = requestAnimationFrame(() => {
      rafIdRef.current = null
      doFlush(messageId)
    })
  }, [doFlush])

  const write = useCallback((messageId: string, content: string, reasoning: string = '') => {
    const buffer = bufferRef.current
    const existing = buffer.get(messageId) || { content: '', reasoning: '' }
    existing.content += content
    if (reasoning) {
      existing.reasoning += reasoning
    }
    buffer.set(messageId, existing)

    const now = performance.now()
    if (now - lastFlushRef.current >= flushInterval) {
      lastFlushRef.current = now
      scheduleFlush(messageId)
    } else {
      scheduleFlush(messageId)
    }
  }, [flushInterval, scheduleFlush])

  const flush = useCallback((messageId?: string) => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current)
      rafIdRef.current = null
    }
    doFlush(messageId)
  }, [doFlush])

  // 组件卸载时清空缓冲
  useEffect(() => {
    return () => {
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current)
      }
      doFlush()
    }
  }, [doFlush])

  return { write, flush }
}
