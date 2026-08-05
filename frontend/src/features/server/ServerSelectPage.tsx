/**
 * 服务器选择页（APP 模式首屏）。
 *
 * 设计主题："局域网信号发现"——探测、发现、连接 的配对仪式。
 * - 扫描中：雷达动画（旋转扫描弧 + 涟漪脉冲）表达探测过程
 * - 发现列表：信号强度条把延迟可视化（<30ms 满格），版本徽章与延迟并排
 * - 手动添加：作为次级入口，与自动发现互补（跨网段 / 非默认端口）
 *
 * 全部颜色走 tokens 变量，浅色/深色主题自动适配；
 * 动画只用 transform/opacity（GPU 合成），尊重 prefers-reduced-motion。
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
import BrandMark from '@/shared/components/BrandMark/BrandMark'
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

/**
 * 延迟毫秒数 → 信号格数（1-4）。
 * 阈值对应局域网典型体验：<30ms 极佳（直连/模拟器宿主映射），
 * <80ms 良好（同网段 WiFi），<200ms 可用（跨网段/NAT 转发）。
 */
export function signalBars(latencyMs: number): number {
  if (latencyMs < 30) return 4
  if (latencyMs < 80) return 3
  if (latencyMs < 200) return 2
  return 1
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

/** 扫描中的雷达动画（旋转扫描弧 + 双层涟漪脉冲） */
function Radar() {
  return (
    <div className={styles['radar-wrap']} aria-hidden="true">
      <div className={styles['radar']}>
        <div className={styles['radar-sweep']} />
        <div className={styles['radar-ripple']} />
        <div className={styles['radar-ripple']} />
        <div className={styles['radar-core']} />
      </div>
    </div>
  )
}

/** 信号强度条：按延迟毫秒数渲染 1-4 格竖条 */
function SignalBars({ latencyMs }: { latencyMs: number }) {
  const bars = signalBars(latencyMs)
  return (
    <span
      className={styles['signal-bars']}
      aria-label={`信号强度 ${bars}/4`}
      title={`延迟 ${latencyMs}ms`}
    >
      {[1, 2, 3, 4].map((level) => (
        <span
          key={level}
          className={`${styles['signal-bar']} ${level <= bars ? styles['signal-bar-on'] : ''}`}
          style={{ height: `${6 + level * 3}px` }}
        />
      ))}
    </span>
  )
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
    void connectTo(backend.url, backend.ip)
  }, [connectTo])

  const scanning = scanState === 'scanning'

  return (
    <div className={styles['server-select-page']}>
      <div className={styles['server-shell']}>
        {/* 品牌区 */}
        <header className={styles['brand-header']}>
          <BrandMark size={56} />
          <h1 className={styles['brand-title']}>Open-AwA</h1>
          <p className={styles['brand-subtitle']}>选择要连接的服务器</p>
        </header>

        {/* 扫描控制 */}
        <div className={styles['scan-control']}>
          <label className={styles['port-field']}>
            <span className={styles['port-label']}>端口</span>
            <input
              className={styles['port-input']}
              type="number"
              value={manualPort}
              min={1}
              max={65535}
              onChange={(e) => setManualPort(e.target.value)}
              disabled={scanning}
            />
          </label>
          <button
            type="button"
            className={`${styles['scan-btn']} ${scanning ? styles['scan-btn-active'] : ''}`}
            onClick={() => void startScan()}
            disabled={scanning}
          >
            {scanning ? '正在扫描…' : found.length > 0 || scanState === 'done' ? '重新扫描' : '扫描局域网'}
          </button>
        </div>

        {/* 扫描状态区：雷达动画 + 实时计数 */}
        <div className={styles['status-area']} role="status" aria-live="polite">
          {scanning ? (
            <>
              <Radar />
              <p className={styles['status-text']}>
                {found.length > 0
                  ? `已发现 ${found.length} 个实例，继续扫描…`
                  : '正在扫描网段内设备…'}
              </p>
            </>
          ) : scanState === 'done' ? (
            <p className={styles['status-text']}>
              {found.length > 0 ? `发现 ${found.length} 个实例` : '本次扫描未发现实例'}
            </p>
          ) : (
            <p className={styles['status-text']}>点击上方按钮扫描局域网</p>
          )}
        </div>

        {/* 发现结果列表 */}
        {found.length > 0 && (
          <ul className={styles['server-list']} aria-label="发现的服务器列表">
            {found.map((backend) => {
              const isConnecting = connecting === backend.ip
              return (
                <li key={backend.ip}>
                  <button
                    type="button"
                    className={styles['server-item']}
                    onClick={() => handleDiscoveredConnect(backend)}
                    disabled={!!connecting}
                    aria-busy={isConnecting}
                  >
                    <span className={styles['server-item-signal']}>
                      <SignalBars latencyMs={backend.latencyMs} />
                    </span>
                    <span className={styles['server-item-main']}>
                      <span className={styles['server-item-name']}>
                        {backend.instanceName || 'Open-AwA'}
                      </span>
                      <span className={styles['server-item-ip']}>
                        {backend.ip}
                        <span className={styles['server-item-latency']}>{backend.latencyMs}ms</span>
                      </span>
                    </span>
                    <span className={styles['server-item-meta']}>
                      {backend.version && (
                        <span className={styles['server-item-version']}>v{backend.version}</span>
                      )}
                      <span
                        className={`${styles['server-item-action']} ${isConnecting ? styles['server-item-action-loading'] : ''}`}
                        aria-hidden="true"
                      >
                        {isConnecting ? '' : '›'}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}

        {/* 空结果引导 */}
        {scanState === 'done' && found.length === 0 && !error && (
          <div className={styles['empty-hint']}>
            <p className={styles['empty-title']}>没有发现 Open-AwA 实例</p>
            <p className={styles['empty-detail']}>
              请确认后端已启动，并以 <code>ALLOW_LAN_ACCESS=true</code> 开启局域网访问；
              也可以使用下方手动添加地址。
            </p>
          </div>
        )}

        {/* 手动添加 */}
        <div className={styles['manual-section']}>
          <div className={styles['manual-label']}>手动添加服务器</div>
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
              aria-label="服务器地址"
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
            正在连接 {connecting}…
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
