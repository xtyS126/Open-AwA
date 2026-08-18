/**
 * 引导窗口页面组件
 * 桌面端首次启动时显示，用于配置后端 URL
 * 通过 Electron preload 注入的 API 进行 IPC 通信
 */
import { useState, useCallback } from 'react'
import { getDesktopApi } from '@/shared/utils/platform'
import styles from './OnboardingPage.module.css'

/** 连接测试状态 */
type ConnectionStatus = 'idle' | 'testing' | 'success' | 'error'

/** 连接测试结果 */
interface TestResult {
  ok: boolean
  latency?: number
  error?: string
}

export default function OnboardingPage() {
  const [url, setUrl] = useState('http://localhost:8000')
  const [status, setStatus] = useState<ConnectionStatus>('idle')
  const [statusMessage, setStatusMessage] = useState('')
  const [testPassed, setTestPassed] = useState(false)
  const [saving, setSaving] = useState(false)

  /** 测试后端连接 */
  const handleTestConnection = useCallback(async () => {
    const trimmedUrl = url.trim()
    if (!trimmedUrl) {
      setStatus('error')
      setStatusMessage('请输入后端 URL')
      return
    }

    setStatus('testing')
    setStatusMessage('')

    try {
      const desktopApi = getDesktopApi()
      if (!desktopApi) {
        setStatus('error')
        setStatusMessage('未检测到桌面端环境，请通过桌面应用启动')
        return
      }
      const result = (await desktopApi.ipc.invoke('backend:test-connection', { url: trimmedUrl })) as TestResult
      if (result.ok) {
        setStatus('success')
        setStatusMessage(`连接成功（延迟 ${result.latency}ms）`)
        setTestPassed(true)
      } else {
        setStatus('error')
        setStatusMessage(`连接失败：${result.error || '未知错误'}`)
        setTestPassed(false)
      }
    } catch (err) {
      setStatus('error')
      setStatusMessage(`测试失败：${err instanceof Error ? err.message : String(err)}`)
      setTestPassed(false)
    }
  }, [url])

  /** 保存后端 URL 并进入主窗口 */
  const handleSave = useCallback(async () => {
    if (!testPassed || saving) return

    const trimmedUrl = url.trim()
    setSaving(true)

    try {
      const desktopApi = getDesktopApi()
      if (!desktopApi) {
        setStatus('error')
        setStatusMessage('未检测到桌面端环境，请通过桌面应用启动')
        setSaving(false)
        return
      }
      const result = (await desktopApi.ipc.invoke('backend:set-url', { url: trimmedUrl })) as { success: boolean; error?: string }
      if (result.success) {
        // 主进程收到 backend:url-saved 事件后会自动关闭引导窗口并启动主窗口
        // 此处无需额外操作
      } else {
        setStatus('error')
        setStatusMessage(`保存失败：${result.error || '未知错误'}`)
        setSaving(false)
      }
    } catch (err) {
      setStatus('error')
      setStatusMessage(`保存失败：${err instanceof Error ? err.message : String(err)}`)
      setSaving(false)
    }
  }, [url, testPassed, saving])

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <h1 className={styles.title}>Open-AwA 桌面端</h1>
        <p className={styles.description}>
          请输入后端服务地址以开始使用。后端需已部署并运行中。
        </p>

        <div className={styles.field}>
          <label htmlFor="backend-url" className={styles.label}>后端 URL</label>
          <input
            id="backend-url"
            type="text"
            className={styles.input}
            placeholder="http://localhost:8000"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value)
              setTestPassed(false)
              setStatus('idle')
              setStatusMessage('')
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && testPassed) {
                handleSave()
              } else if (e.key === 'Enter') {
                handleTestConnection()
              }
            }}
          />
        </div>

        {status !== 'idle' && (
          <div className={`${styles.result} ${status === 'success' ? styles.resultSuccess : status === 'error' ? styles.resultError : styles.resultTesting}`}>
            {status === 'testing' && '正在测试连接...'}
            {status === 'success' && statusMessage}
            {status === 'error' && statusMessage}
          </div>
        )}

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.testBtn}
            onClick={handleTestConnection}
            disabled={status === 'testing'}
          >
            {status === 'testing' ? '测试中...' : '测试连接'}
          </button>
          <button
            type="button"
            className={styles.saveBtn}
            onClick={handleSave}
            disabled={!testPassed || saving}
          >
            {saving ? '保存中...' : '保存并进入'}
          </button>
        </div>
      </div>
    </div>
  )
}