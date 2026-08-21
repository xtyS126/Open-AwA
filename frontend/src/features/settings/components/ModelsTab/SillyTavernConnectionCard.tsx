/**
 * 酒馆AI（SillyTavern）生图连接说明卡片
 *
 * 当存在已配置的生图模型时展示，指导用户在酒馆AI的图像生成扩展中
 * 以 "Stable Diffusion Web UI (AUTOMATIC1111)" 类型连接 Open-AwA 后端：
 * - API URL: Open-AwA 后端根地址（不带 /api 前缀，A1111 协议挂载在根路径）
 * - 认证: HTTP Basic，格式为 任意用户名:OpenAwA访问密钥
 */
import { useMemo, useState } from 'react'
import { API_BASE_URL } from '@/shared/api/client'
import styles from '@/features/settings/SettingsPage.module.css'

interface SillyTavernConnectionCardProps {
  /** 已配置的生图模型数量，为 0 时卡片隐藏 */
  imageModelCount: number
}

/** 从前端 API 基址推导酒馆AI连接用的后端根地址 */
function resolveBackendRootUrl(): string {
  // 相对路径（web 模式走 Vite proxy）时用当前页面 origin
  if (API_BASE_URL.startsWith('/')) {
    return window.location.origin
  }
  try {
    const parsed = new URL(API_BASE_URL)
    // 后端 API 挂在 /api 前缀下，A1111 协议在根路径，剥掉 /api 即得根地址
    const path = parsed.pathname.replace(/\/api\/?$/, '')
    return `${parsed.protocol}//${parsed.host}${path}`
  } catch {
    return window.location.origin
  }
}

export function SillyTavernConnectionCard({ imageModelCount }: SillyTavernConnectionCardProps) {
  const [copied, setCopied] = useState<'url' | 'auth' | null>(null)

  const backendUrl = useMemo(() => resolveBackendRootUrl(), [])

  // 无生图模型时不展示（酒馆AI连接后也没有可用模型）
  if (imageModelCount < 1) return null

  /** 复制文本到剪贴板并短暂显示已复制状态 */
  const handleCopy = async (text: string, field: 'url' | 'auth') => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(field)
      setTimeout(() => setCopied(null), 2000)
    } catch {
      // 剪贴板不可用（如非安全上下文）时静默降级：用户可手动选中复制
    }
  }

  return (
    <div className={styles['sdwebui-compat-card']}>
      <div className={styles['sdwebui-compat-header']}>
        <h3>酒馆AI（SillyTavern）生图接入</h3>
        <span className={styles['sdwebui-compat-badge']}>
          已配置 {imageModelCount} 个生图模型
        </span>
      </div>
      <p className={styles['sdwebui-compat-desc']}>
        在酒馆AI的 扩展 → 图像生成 中按以下配置连接 Open-AwA 生图，
        API 类型选择 <strong>Stable Diffusion Web UI (AUTOMATIC1111)</strong>
      </p>
      <div className={styles['sdwebui-compat-fields']}>
        <div className={styles['sdwebui-compat-field']}>
          <span className={styles['sdwebui-compat-field-label']}>API URL</span>
          <div className={styles['sdwebui-compat-field-value-row']}>
            <code className={styles['sdwebui-compat-field-value']}>{backendUrl}</code>
            <button
              type="button"
              className={styles['sdwebui-compat-copy-btn']}
              onClick={() => handleCopy(backendUrl, 'url')}
            >
              {copied === 'url' ? '已复制' : '复制'}
            </button>
          </div>
        </div>
        <div className={styles['sdwebui-compat-field']}>
          <span className={styles['sdwebui-compat-field-label']}>认证（可选）</span>
          <div className={styles['sdwebui-compat-field-value-row']}>
            <code className={styles['sdwebui-compat-field-value']}>任意用户名:OpenAwA访问密钥</code>
            <button
              type="button"
              className={styles['sdwebui-compat-copy-btn']}
              onClick={() => handleCopy('openawa:你的访问密钥', 'auth')}
            >
              {copied === 'auth' ? '已复制' : '复制'}
            </button>
          </div>
          <span className={styles['sdwebui-compat-field-hint']}>
            访问密钥即登录 Open-AwA 使用的 API Key（HTTP Basic 格式，冒号后为密钥）
          </span>
        </div>
      </div>
      <p className={styles['sdwebui-compat-note']}>
        连接后在酒馆AI模型列表中选择要使用的生图模型；负面提示词、尺寸等参数将按模型协议透传。
      </p>
    </div>
  )
}
