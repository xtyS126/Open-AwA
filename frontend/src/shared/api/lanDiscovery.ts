/**
 * 局域网后端发现：
 * - 通过原生插件 LanDiscovery 获取本机 IPv4 与网段
 * - 枚举同网段候选主机，并发探测 /api/system/ping（pong=true 即命中 Open-AwA 后端）
 *
 * 探测走 WebView 内 fetch：
 * - 后端开启 ALLOW_LAN_ACCESS 时 CORS 放行 https://localhost origin，正常读取响应
 * - 非 Open-AwA 主机 / 未开 CORS 的主机抛跨源错误，视为不可达自动跳过
 * - 每个候选 900ms 超时，单次扫描控制在 10 秒左右
 */
import { registerPlugin } from '@capacitor/core'

export interface LocalNetworkInfo {
  ip: string
  prefixLength: number
  interfaceName: string
}

interface LanDiscoveryNativePlugin {
  getNetworkInfo(): Promise<{ info: LocalNetworkInfo | null }>
}

export const lanDiscovery = registerPlugin<LanDiscoveryNativePlugin>('LanDiscovery')

/** 扫描发现的后端实例 */
export interface DiscoveredBackend {
  ip: string
  /** 接入用的 API 基址（含 /api 前缀） */
  url: string
  latencyMs: number
  version?: string
  instanceName?: string
}

/** 默认探测端口（后端 FastAPI 默认监听端口） */
export const DEFAULT_BACKEND_PORT = 8000

/** Android 模拟器（AOSP/MuMu）宿主机映射地址 */
const EMULATOR_HOST_ALIAS = '10.0.2.2'

/**
 * 并发扫描本机所在网段内的 Open-AwA 后端实例。
 * 仅在 Capacitor 原生容器内可用；浏览器环境返回空列表。
 */
export async function scanLanBackends(
  port = DEFAULT_BACKEND_PORT,
  concurrency = 24,
  timeoutMs = 900,
  onFound?: (backend: DiscoveredBackend) => void,
): Promise<DiscoveredBackend[]> {
  let info: LocalNetworkInfo | null = null
  try {
    const result = await lanDiscovery.getNetworkInfo()
    info = result?.info ?? null
  } catch {
    return []
  }
  if (!info) {
    return []
  }

  const parts = info.ip.split('.')
  if (parts.length !== 4) {
    return []
  }
  const base = `${parts[0]}.${parts[1]}.${parts[2]}.`

  // 枚举同 /24 网段的候选主机（跳过本机）
  const candidates: string[] = []
  for (let i = 1; i <= 254; i += 1) {
    const ip = base + i
    if (ip !== info.ip) {
      candidates.push(ip)
    }
  }

  // Android 模拟器宿主映射：AOSP 约定 10.0.2.2 指向宿主机，
  // MuMu 模拟器后端跑在宿主机时后端仅出现在 10.0.2.2 上（宿主 LAN IP 与模拟器不同网段）。
  // 真手机上该地址通常不可达，额外探测一个 IP 的开销可忽略。
  // 放在候选列表首位优先探测：模拟器场景下让结果更快出现，避免等满一轮。
  if (!candidates.includes(EMULATOR_HOST_ALIAS)) {
    candidates.unshift(EMULATOR_HOST_ALIAS)
  }

  const results: DiscoveredBackend[] = []
  let nextIndex = 0

  const probeWorker = async () => {
    while (nextIndex < candidates.length) {
      const ip = candidates[nextIndex]
      nextIndex += 1
      const url = `http://${ip}:${port}`
      try {
        const controller = new AbortController()
        const timer = setTimeout(() => controller.abort(), timeoutMs)
        const t0 = performance.now()
        const resp = await fetch(`${url}/api/system/ping`, { signal: controller.signal })
        clearTimeout(timer)
        if (!resp.ok) {
          continue
        }
        const data = (await resp.json()) as {
          pong?: boolean
          version?: string
          instance_name?: string
        } | null
        if (data?.pong === true) {
          const backend: DiscoveredBackend = {
            ip,
            url: `${url}/api`,
            latencyMs: Math.round(performance.now() - t0),
            version: data.version,
            instanceName: data.instance_name,
          }
          results.push(backend)
          onFound?.(backend)
        }
      } catch {
        // 不可达或跨源被拒（非 Open-AwA 主机），跳过
      }
    }
  }

  const workerCount = Math.max(1, Math.min(concurrency, candidates.length))
  await Promise.all(Array.from({ length: workerCount }, () => probeWorker()))

  return results.sort((a, b) => a.latencyMs - b.latencyMs)
}
