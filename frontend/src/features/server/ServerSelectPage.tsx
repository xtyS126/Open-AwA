/**
 * 服务器选择页（APP 模式首屏）。
 *
 * 功能：
 * - 自动扫描局域网内同网段的 Open-AwA 后端（探测 /api/system/ping）
 * - 实时展示已发现实例（实例名/IP/版本/延迟），用户选择接入
 * - 支持手动输入后端地址兜底（跨网段或端口非默认）
 *
 * 选择后调用 setBackendUrl 持久化，随后由 RootGuard 走正常初始化流程。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from '@/shared/routing'
import { setBackendUrl } from '@/shared/api/client'
import {
  DEFAULT_BACKEND_PORT,
  scanLanBackends,
  type DiscoveredBackend,
} from '@/shared/api/lanDiscovery'
import { isNativeApp } from '@/shared/utils/platform'
import { useAuthStore } from '@/shared/store/authStore'
import { appLogger } from '@/shared/utils/logger'
import styles from './ServerSelectPage.module.css'

type ScanState = 'idle' | 'scanning' | 'done'

/** 将用户输入规范化接入 URL：自动补全协议与 /api 前缀 */
export function normalizeServerInput(input: string): string {
  let value = input.trim()
  if (!value) {
    return ''
  }
  if (!/^https?:\/\//i.test(value)) {
    value = `http://${value}`
  }
  try {
    const url = new URL(value)
    if (url.pathname === '/' || url.pathname === '') {
      url.pathname = '/api'
    }
    return `${url.origin}${url.pathname.replace(/\/+$/, '')}`
  } catch {
    return ''
  }
}

/** 校验候选后端可达：探测 ping 端点确认 pong=true */
async function probeBackend(baseUrl: string, timeoutMs = 3000): Promise<boolean> {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    const resp = await fetch(`${baseUrl}/system/ping`, { signal: controller.signal })
    clearTimeout(timer)
    if (!resp.ok) {
      return false
    }
    const data = (await resp.json()) as { pong?: boolean } | null
    return data?.pong === true
  } catch {
    return false
  }
}

export default function ServerSelectPage() {
  const navigate = useNavigate()
  const setNeedsServerSelection = useAuthStore((s) => s.setNeedsServerSelection)
  const [scanState, setScanState] = useState<ScanState>('idle')
  const [found, setFound] = useState<DiscoveredBackend[]>([])
  const [manualInput, setManualInput] = useState('')
  const [manualPort, setManualPort] = useState(String(DEFAULT_BACKEND_PORT))
  const [error, setError] = useState('')
  const [connecting, setConnecting] = useState('')
  const scanRunRef = useRef(0)

  const startScan = useCallback(async () => {
    setError('')
    setFound([])
    setScanState('scanning')
    const runId = ++scanRunRef.current
    try {
      const port = Number(manualPort.trim()) || DEFAULT_BACKEND_PORT
      const results = await scanLanBackends(port, 24, 900, (backend) => {
        // 实时追加已发现实例（按延迟保持有序）
        if (scanRunRef.current === runId) {
          setFound((prev) => {
            const next = [...prev, backend].sort((a, b) => a.latencyMs - b.latencyMs)
            return next
          })
        }
      })
      if (scanRunRef.current === runId) {
        setFound(results)
        setScanState('done')
      }
    } catch (scanError) {
      if (scanRunRef.current === runId) {
        setError(`扫描失败：${scanError instanceof Error ? scanError.message : String(scanError)}`)
        setScanState('done')
      }
    }
  }, [manualPort])

  // 进入页面后自动开始扫描（原生容器内）
  useEffect(() => {
    if (isNativeApp()) {
      void startScan()
    }
    return () => {
      scanRunRef.current += 1
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const connectTo = useCallback(async (baseUrl: string, label: string) => {
    setError('')
    setConnecting(label)
    const reachable = await probeBackend(baseUrl)
    if (!reachable) {
      setConnecting('')
      setError(`无法连接 ${label}，请确认后端已启动且允许局域网访问（ALLOW_LAN_ACCESS=true）`)
      return
    }
    setBackendUrl(baseUrl)
    setNeedsServerSelection(false)
    appLogger.info({
      event: 'server_selected',
      module: 'server',
      action: 'connect',
      status: 'success',
      message: 'backend selected, redirecting to login',
      extra: { url: baseUrl },
    })
    void navigate('/login')
  }, [navigate, setNeedsServerSelection])

  const handleManualConnect = useCallback(async () => {
    const baseUrl = normalizeServerInput(manualInput)
    if (!baseUrl) {
      setError('请输入有效的服务器地址，例如 192.168.1.100:8000')
      return
    }
    await connectTo(baseUrl, baseUrl)
  }, [manualInput, connectTo])

  const handleDiscoveredConnect = useCallback((backend: DiscoveredBackend) => {
    void connectTo(backend.url, `${backend.ip}:${backend.latencyMs}ms`)
  }, [connectTo])

  return (
    <div className={styles['server-select-page']}>
      <div className={styles['server-card']}>
        <div className={styles['server-header']}>
          <h1 className={styles['server-title']}>Open-AwA</h1>
          <p className={styles['server-subtitle']}>选择要连接的服务器</p>
        </div>

        <div className={styles['scan-section']}>
          <div className={styles['scan-row']}>
            <label className={styles['port-label']} htmlFor="server-port">端口</label>
            <input
              id="server-port"
              className={styles['port-input']}
              type="number"
              value={manualPort}
              min={1}
              max={65535}
              onChange={(e) => setManualPort(e.target.value)}
              disabled={scanState === 'scanning'}
            />
            <button
              type="button"
              className={styles['scan-btn']}
              onClick={() => void startScan()}
              disabled={scanState === 'scanning'}
            >
              {scanState === 'scanning' ? '扫描中...' : found.length > 0 || scanState === 'done' ? '重新扫描' : '扫描局域网'}
            </button>
          </div>
          {scanState === 'scanning' && (
            <p className={styles['scan-hint']} role="status">
              正在扫描网段内设备，约 10 秒，请稍候...
            </p>
          )}
          {scanState === 'done' && found.length === 0 && !error && (
            <p className={styles['scan-empty']}>未发现 Open-AwA 后端，请确认后端已开启局域网访问，或手动输入地址</p>
          )}
        </div>

        {found.length > 0 && (
          <ul className={styles['server-list']} aria-label="发现的服务器列表">
            {found.map((backend) => (
              <li key={backend.ip}>
                <button
                  type="button"
                  className={styles['server-item']}
                  onClick={() => handleDiscoveredConnect(backend)}
                  disabled={!!connecting}
                >
                  <span className={styles['server-item-main']}>
                    <span className={styles['server-item-name']}>
                      {backend.instanceName || 'Open-AwA'}
                    </span>
                    <span className={styles['server-item-ip']}>{backend.ip}</span>
                  </span>
                  <span className={styles['server-item-meta']}>
                    {backend.version && <span className={styles['server-item-version']}>v{backend.version}</span>}
                    <span className={styles['server-item-latency']}>{backend.latencyMs}ms</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className={styles['manual-section']}>
          <div className={styles['manual-label']}>手动输入服务器地址</div>
          <div className={styles['manual-row']}>
            <input
              className={styles['manual-input']}
              type="text"
              placeholder="192.168.1.100:8000"
              value={manualInput}
              onChange={(e) => setManualInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  void handleManualConnect()
                }
              }}
              disabled={!!connecting}
            />
            <button
              type="button"
              className={styles['connect-btn']}
              onClick={() => void handleManualConnect()}
              disabled={!!connecting || !manualInput.trim()}
            >
              连接
            </button>
          </div>
        </div>

        {connecting && (
          <p className={styles['connecting']} role="status">
            正在连接 {connecting}...
          </p>
        )}
        {error && (
          <p className={styles['server-error']} role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
