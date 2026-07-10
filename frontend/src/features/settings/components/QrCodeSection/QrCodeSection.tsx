/**
 * 移动端接入二维码组件。
 *
 * 渲染当前后端服务地址的二维码，供 Open-AwA 手机 App 扫码快速配置后端连接。
 * 二维码内容为后端服务的 origin（scheme + host + port），与 Android BackendManager
 * 默认期望格式（如 http://192.168.1.100:8000）一致。
 *
 * 安全与 UX 考虑：
 * - 当 BaseUrl 为 localhost/127.0.0.1 时显示警告，提示手机需在同一局域网且后端开启局域网访问
 * - 提供 BaseUrl 文本与复制按钮，方便用户手动输入
 * - 二维码通过 qrcode 库在前端本地生成，不向任何第三方服务发送 URL
 */
import { useEffect, useState, useCallback } from 'react'
import QRCode from 'qrcode'
import { API_BASE_URL } from '@/shared/api/client'
import { appLogger } from '@/shared/utils/logger'
import styles from './QrCodeSection.module.css'

/**
 * 将 API_BASE_URL 解析为绝对 origin URL。
 * - 绝对 URL（http/https）：取其 origin（scheme + host + port）
 * - 相对路径（/api）：使用当前页面 origin（生产同源部署场景）
 */
function resolveBackendOrigin(): string {
  if (API_BASE_URL.startsWith('http://') || API_BASE_URL.startsWith('https://')) {
    try {
      const url = new URL(API_BASE_URL)
      return `${url.protocol}//${url.host}`
    } catch {
      return API_BASE_URL
    }
  }
  // 相对路径：使用当前页面 origin（生产环境下前端与后端同源部署）
  if (typeof window !== 'undefined') {
    return window.location.origin
  }
  return API_BASE_URL
}

/**
 * 判断 URL 是否为本地回环地址。
 * 手机端无法访问电脑的 localhost，需提示用户切换为局域网 IP。
 */
function isLocalAddress(url: string): boolean {
  try {
    const parsed = new URL(url)
    const host = parsed.hostname.toLowerCase()
    return (
      host === 'localhost' ||
      host === '127.0.0.1' ||
      host === '0.0.0.0' ||
      host === '::1'
    )
  } catch {
    return false
  }
}

/** 将文本复制到剪贴板，返回是否成功 */
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 降级到 execCommand
  }
  // 降级方案：使用临时 textarea + execCommand
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  } catch {
    return false
  }
}

export function QrCodeSection() {
  const backendOrigin = resolveBackendOrigin()
  const localAddress = isLocalAddress(backendOrigin)
  const [qrDataUrl, setQrDataUrl] = useState<string>('')
  const [qrError, setQrError] = useState<string>('')
  const [copied, setCopied] = useState(false)

  // 生成二维码 data URL，backendOrigin 变化时重新生成
  useEffect(() => {
    let cancelled = false
    setQrError('')
    QRCode.toDataURL(backendOrigin, {
      errorCorrectionLevel: 'M',
      margin: 2,
      width: 240,
      color: {
        dark: '#1f2937',
        light: '#ffffff',
      },
    })
      .then((url) => {
        if (!cancelled) {
          setQrDataUrl(url)
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const errorMsg = err instanceof Error ? err.message : String(err)
        setQrError(`二维码生成失败：${errorMsg}`)
        appLogger.error({
          event: 'qrcode_generate_failed',
          module: 'settings',
          message: '移动端接入二维码生成失败',
          extra: { error: errorMsg, url: backendOrigin },
        })
      })
    return () => {
      cancelled = true
    }
  }, [backendOrigin])

  /** 复制 BaseUrl 到剪贴板 */
  const handleCopy = useCallback(async () => {
    const ok = await copyToClipboard(backendOrigin)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } else {
      appLogger.warning({
        event: 'qrcode_copy_failed',
        module: 'settings',
        message: '复制后端地址到剪贴板失败',
      })
    }
  }, [backendOrigin])

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>移动端接入</h3>
      <p className={styles.description}>
        用 Open-AwA 手机 App 扫描此二维码即可连接到当前后端服务。
      </p>

      <div className={styles.content}>
        <div className={styles.qrWrap}>
          {qrDataUrl ? (
            <img
              src={qrDataUrl}
              alt="后端地址二维码"
              className={styles.qrImage}
              width={240}
              height={240}
              loading="lazy"
              decoding="async"
            />
          ) : qrError ? (
            <div className={styles.qrError}>{qrError}</div>
          ) : (
            <div className={styles.qrPlaceholder}>生成中...</div>
          )}
        </div>

        <div className={styles.info}>
          <div className={styles.urlRow}>
            <label className={styles.label}>后端地址</label>
            <code className={styles.urlText}>{backendOrigin}</code>
            <button
              type="button"
              className={styles.copyBtn}
              onClick={() => void handleCopy()}
              title="复制后端地址"
            >
              {copied ? '已复制' : '复制'}
            </button>
          </div>

          {localAddress && (
            <div className={styles.warning}>
              当前后端地址为本地回环地址（localhost/127.0.0.1），手机无法直接访问。
              请将后端地址改为局域网 IP（如 http://192.168.1.100:8000），并确保：
              <ul>
                <li>手机与电脑在同一局域网/Wi-Fi</li>
                <li>后端服务已监听 0.0.0.0 或具体局域网 IP（非仅 127.0.0.1）</li>
                <li>防火墙已放行后端端口（默认 8000）</li>
              </ul>
            </div>
          )}

          <div className={styles.tip}>
            提示：在上方"后端 URL"输入框中修改地址后保存，二维码会自动更新。
          </div>
        </div>
      </div>
    </div>
  )
}

export default QrCodeSection
