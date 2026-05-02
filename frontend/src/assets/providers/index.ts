/**
 * 供应商图标映射。
 * 为每个已知供应商提供本地 SVG 图标路径，未知供应商返回 null。
 */
import openaiSvg from './openai.svg'
import anthropicSvg from './anthropic.svg'
import googleSvg from './google.svg'
import deepseekSvg from './deepseek.svg'
import alibabaSvg from './alibaba.svg'
import moonshotSvg from './moonshot.svg'
import zhipuSvg from './zhipu.svg'
import ollamaSvg from './ollama.svg'

const PROVIDER_ICONS: Record<string, string> = {
  openai: openaiSvg,
  anthropic: anthropicSvg,
  google: googleSvg,
  deepseek: deepseekSvg,
  alibaba: alibabaSvg,
  moonshot: moonshotSvg,
  zhipu: zhipuSvg,
  ollama: ollamaSvg,
}

/** 已知供应商及其标准显示名称 */
const PROVIDER_NAMES: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  google: 'Google',
  deepseek: 'DeepSeek',
  alibaba: '阿里通义千问',
  moonshot: 'Kimi',
  zhipu: '智谱AI',
  ollama: 'Ollama',
}

/** 获取供应商的本地图标路径，若不存在返回 null */
export function getProviderIcon(providerId: string): string | null {
  return PROVIDER_ICONS[providerId.toLowerCase()] || null
}

/** 获取供应商的显示名称，若不存在返回格式化后的 ID */
export function getProviderDisplayName(providerId: string): string {
  return PROVIDER_NAMES[providerId.toLowerCase()] || providerId.toUpperCase()
}

export { PROVIDER_ICONS, PROVIDER_NAMES }
export default PROVIDER_ICONS
