/**
 * IM 渠道 API 封装 — 提供渠道列表查询、配置更新、消息发送、网关状态查询等接口。
 */
import api from '@/shared/api/api'

const BASE = '/im'

/** 渠道信息 */
export interface IMChannel {
  channel: string
  enabled: boolean
  configured: boolean
}

/** 渠道配置 */
export interface ChannelConfig {
  channel: string
  enabled: boolean
  bot_token: string
  app_id: string
  app_secret: string
  webhook_url: string
  extra: Record<string, unknown>
}

/** IM 网关状态 */
export interface IMStatus {
  running: boolean
  channels: string[]
  configs: Record<string, { enabled: boolean }>
}

/** 获取渠道列表 */
export async function getChannels(): Promise<{ channels: IMChannel[] }> {
  const { data } = await api.get(`${BASE}/channels`)
  return data
}

/** 更新渠道配置 */
export async function updateChannelConfig(
  channel: string,
  config: Partial<ChannelConfig>
): Promise<{ ok: boolean; channel: string; enabled: boolean }> {
  const { data } = await api.put(`${BASE}/channels/${channel}`, config)
  return data
}

/** 发送消息 */
export async function sendMessage(
  channel: string,
  chatId: string,
  text: string
): Promise<{ ok: boolean }> {
  const { data } = await api.post(`${BASE}/send`, { channel, chat_id: chatId, text })
  return data
}

/** 获取网关状态 */
export async function getIMStatus(): Promise<IMStatus> {
  const { data } = await api.get(`${BASE}/status`)
  return data
}
