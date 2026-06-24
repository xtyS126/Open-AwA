/**
 * 后端连接设置组件
 * 允许用户配置远程后端 URL，测试连通性并应用
 * Web 端和桌面端通用
 */
import { useState } from 'react'
import { setBackendUrl } from '@/shared/api/client'
import { useNotification } from '@/shared/hooks/useNotification'
import styles from './BackendConnection.module.css'

interface BackendConnectionProps {
  /** 当前后端 URL */
  currentUrl: string
  /** 是否为桌面端（影响保存逻辑：桌面端通过 IPC 通知主进程） */
  isDesktop: boolean
  /** 保存回调（桌面端通过 IPC 保存到 electron-store） */
  onSave?: (url: string) => Promise<void>
  /** 测试连接回调（桌面端通过 IPC 测试，web 端直接 fetch） */
  onTest?: (url: string) => Promise<{ ok: boolean; latency?: number; error?: string }>
}

export function BackendConnection({ currentUrl, isDesktop, onSave, onTest }: BackendConnectionProps) {
  const [url, setUrl] = useState(currentUrl)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; latency?: number; error?: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const { message, showNotification } = useNotification(3000)

  /** 测试后端连通性 */
  const handleTest = async () => {
    if (!url.trim()) {
      showNotification({ type: 'error', text: '请输入后端 URL' })
      return
    }
    setTesting(true)
    setTestResult(null)
    try {
      const result = onTest
        ? await onTest(url.trim())
        : await testConnectionWeb(url.trim())
      setTestResult(result)
      if (result.ok) {
        showNotification({ type: 'success', text: `连接成功（延迟 ${result.latency}ms）` })
      } else {
        showNotification({ type: 'error', text: `连接失败：${result.error || '未知错误'}` })
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err)
      setTestResult({ ok: false, error: errorMsg })
      showNotification({ type: 'error', text: `测试失败：${errorMsg}` })
    } finally {
      setTesting(false)
    }
  }

  /** 保存并应用后端地址 */
  const handleSave = async () => {
    if (!url.trim()) {
      showNotification({ type: 'error', text: '请输入后端 URL' })
      return
    }
    setSaving(true)
    try {
      if (onSave) {
        await onSave(url.trim())
      } else {
        setBackendUrl(url.trim())
      }
      showNotification({ type: 'success', text: '后端地址已保存，即将刷新页面...' })
      // 刷新页面以应用新的 baseURL
      setTimeout(() => window.location.reload(), 1000)
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err)
      showNotification({ type: 'error', text: `保存失败：${errorMsg}` })
    } finally {
      setSaving(false)
    }
  }

  /** 重置为默认后端地址 */
  const handleReset = () => {
    setUrl('/api')
    setBackendUrl('')
    showNotification({ type: 'success', text: '已重置为默认，即将刷新页面...' })
    setTimeout(() => window.location.reload(), 1000)
  }

  return (
    <div className={styles.container}>
      <h2 className={styles.title}>后端连接</h2>
      <p className={styles.description}>
        {isDesktop
          ? '配置 Open-AwA 后端服务地址。修改后需刷新页面生效。'
          : '配置远程后端服务地址（默认 /api 走代理）。修改后需刷新页面生效。'}
      </p>

      {message && (
        <div className={`${styles.message} ${message.type === 'success' ? styles.success : styles.error}`}>
          {message.text}
        </div>
      )}

      <div className={styles.field}>
        <label className={styles.label} htmlFor="backend-url">后端 URL</label>
        <input
          id="backend-url"
          className={styles.input}
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="http://localhost:8000/api"
          disabled={testing || saving}
        />
      </div>

      {testResult && (
        <div className={`${styles.testResult} ${testResult.ok ? styles.success : styles.error}`}>
          {testResult.ok
            ? `连接成功（延迟 ${testResult.latency}ms）`
            : `连接失败：${testResult.error || '未知错误'}`}
        </div>
      )}

      <div className={styles.actions}>
        <button
          className={styles.button}
          onClick={handleTest}
          disabled={testing || saving || !url.trim()}
        >
          {testing ? '测试中...' : '测试连接'}
        </button>
        <button
          className={`${styles.button} ${styles.primary}`}
          onClick={handleSave}
          disabled={testing || saving || !url.trim()}
        >
          {saving ? '保存中...' : '保存并应用'}
        </button>
        <button
          className={styles.button}
          onClick={handleReset}
          disabled={testing || saving}
        >
          重置为默认
        </button>
      </div>
    </div>
  )
}

/** Web 端默认测试连接实现：直接 fetch /health */
async function testConnectionWeb(baseUrl: string): Promise<{ ok: boolean; latency?: number; error?: string }> {
  const start = Date.now()
  try {
    const healthUrl = baseUrl.endsWith('/api') ? `${baseUrl}/health` : `${baseUrl}/api/health`
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 5000)
    const response = await fetch(healthUrl, { method: 'GET', signal: controller.signal })
    clearTimeout(timeoutId)
    const latency = Date.now() - start
    if (response.ok) {
      return { ok: true, latency }
    }
    return { ok: false, latency, error: `HTTP ${response.status}` }
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err)
    return { ok: false, error: errorMsg }
  }
}
