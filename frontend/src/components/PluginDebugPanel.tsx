import { useState, useEffect, useRef, useCallback } from 'react'
import { pluginsAPI, PluginLogEntry } from '../services/api'
import './PluginDebugPanel.css'

const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
const POLL_INTERVAL_MS = 3000

interface Props {
  pluginId: string
  pluginName: string
}

function formatTs(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('zh-CN', { hour12: false })
  } catch {
    return ts
  }
}

function PluginDebugPanel({ pluginId, pluginName }: Props) {
  const [entries, setEntries] = useState<PluginLogEntry[]>([])
  const [filterLevel, setFilterLevel] = useState<string>('')
  const [activeLevel, setActiveLevel] = useState<string>('DEBUG')
  const [loading, setLoading] = useState(false)
  const [polling, setPolling] = useState(false)
  const [settingLevel, setSettingLevel] = useState(false)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  const fetchLogs = useCallback(async () => {
    try {
      const res = await pluginsAPI.getLogs(pluginId, filterLevel || undefined, 200, 0)
      setEntries(res.data.entries)
    } catch {
      // 静默失败，不中断轮询
    }
  }, [pluginId, filterLevel])

  useEffect(() => {
    setLoading(true)
    fetchLogs().finally(() => setLoading(false))
  }, [fetchLogs])

  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [entries])

  useEffect(() => {
    if (polling) {
      timerRef.current = setInterval(fetchLogs, POLL_INTERVAL_MS)
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
  }, [polling, fetchLogs])

  const handleSetLogLevel = async (level: string) => {
    setSettingLevel(true)
    try {
      await pluginsAPI.setLogLevel(pluginId, level)
      setActiveLevel(level)
    } catch {
      // 静默失败
    } finally {
      setSettingLevel(false)
    }
  }

  return (
    <div className="debug-panel">
      <div className="debug-panel-header">
        <span className="debug-panel-title">{pluginName} 调试面板</span>
        <div className="debug-panel-controls">
          <select
            className="debug-level-select"
            value={filterLevel}
            onChange={(e) => setFilterLevel(e.target.value)}
            title="过滤显示级别"
          >
            <option value="">全部级别</option>
            {LOG_LEVELS.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>

          <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>输出级别:</span>
          {LOG_LEVELS.map((l) => (
            <button
              key={l}
              className={`debug-btn${activeLevel === l ? ' debug-btn-active' : ''}`}
              onClick={() => handleSetLogLevel(l)}
              disabled={settingLevel}
              title={`设置插件日志输出级别为 ${l}`}
            >
              {l}
            </button>
          ))}

          <button
            className={`debug-btn${polling ? ' debug-btn-active' : ''}`}
            onClick={() => setPolling((p) => !p)}
            title="开关轮询刷新"
          >
            {polling ? '停止轮询' : '实时轮询'}
          </button>

          <button
            className="debug-btn"
            onClick={() => { setLoading(true); fetchLogs().finally(() => setLoading(false)) }}
            disabled={loading}
          >
            刷新
          </button>
        </div>
      </div>

      <div className="debug-panel-body" ref={bodyRef}>
        {loading && entries.length === 0 ? (
          <div className="debug-loading">加载中...</div>
        ) : entries.length === 0 ? (
          <div className="debug-empty">暂无日志条目</div>
        ) : (
          entries.map((entry, idx) => (
            <div key={idx} className="debug-log-row">
              <span className="debug-log-ts">{formatTs(entry.timestamp)}</span>
              <span className={`debug-log-level ${entry.level}`}>{entry.level}</span>
              <span className="debug-log-msg">{entry.message}</span>
              {Object.keys(entry.extra).length > 0 && (
                <span className="debug-log-extra">{JSON.stringify(entry.extra)}</span>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default PluginDebugPanel
