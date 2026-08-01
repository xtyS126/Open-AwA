/**
 * 微信集成 API 模块。封装微信自动回复与扫码状态端点。自 api.ts 拆分而来。
 */
import { api } from './client'
import type { WeixinAutoReplyMatchType } from './types'

export interface WeixinConfig {
  account_id: string
  token: string
  base_url: string
  timeout_seconds: number
  user_id?: string
  binding_status?: string
  bot_token?: string
  ilink_bot_id?: string
  ilink_user_id?: string
  bot_type?: string
  channel_version?: string
}

export interface WeixinBindingInfo {
  id?: number
  user_id: string
  weixin_account_id: string
  base_url: string
  bot_type: string
  channel_version: string
  binding_status: string
  weixin_user_id: string
}

export interface WeixinBindingCreate {
  weixin_account_id: string
  token: string
  base_url?: string
  bot_type?: string
  channel_version?: string
  binding_status?: string
  weixin_user_id?: string
}

export interface WeixinParamsConfig {
  base_url: string
  bot_type: string
  channel_version: string
  weixin_default_base_url: string
  weixin_default_bot_type: string
  weixin_default_channel_version: string
  session_timeout_seconds: number
  token_refresh_enabled: boolean
  auto_start_reply?: boolean
}

export interface WeixinParamsUpdate {
  bot_type?: string
  channel_version?: string
  base_url?: string
  auto_start_reply?: boolean
}

export interface WeixinHealthCheckResult {
  ok: boolean
  issues: string[]
  suggestions: string[]
}

export interface WeixinQrStartRequest {
  session_key?: string
  base_url?: string
  bot_type?: string
  force?: boolean
  timeout_seconds?: number
}

export type WeixinQrState = 'pending' | 'half_success' | 'success' | 'failed'

export type WeixinQrStatus = 'idle' | 'waiting' | 'scanned' | 'scaned_but_redirect' | 'expired' | 'confirmed' | 'refreshing'

export interface WeixinQrStartResponse {
  success?: boolean
  state?: WeixinQrState
  message: string
  session_key: string
  status: 'wait' | 'waiting'
  qrcode?: string
  qrcode_url?: string
  qrcode_content?: string
  baseurl?: string
}

export interface WeixinQrWaitRequest {
  session_key: string
  timeout_seconds?: number
  qrcode?: string
  base_url?: string
}

export interface WeixinQrWaitResponse {
  success?: boolean
  state?: WeixinQrState
  connected: boolean
  session_key: string
  status: 'wait' | 'waiting' | 'scanned' | 'scaned' | 'scaned_but_redirect' | 'confirmed' | 'expired' | 'refreshing'
  message: string
  qrcode?: string
  qrcode_url?: string
  qrcode_content?: string
  auth_id?: string
  ticket?: string
  hint?: string
  account_id?: string
  ilink_bot_id?: string
  token?: string
  bot_token?: string
  base_url?: string
  baseurl?: string
  redirect_host?: string
  user_id?: string
  ilink_user_id?: string
  binding_status?: string
}

export interface WeixinQrExitRequest {
  session_key?: string
  clear_config?: boolean
}

export interface WeixinQrExitResponse {
  message: string
  cleared_sessions: number
}

export interface WeixinAutoReplyStatus {
  user_id: string
  binding_status: string
  binding_ready: boolean
  weixin_account_id?: string
  weixin_user_id?: string
  auto_reply_enabled: boolean
  auto_reply_running: boolean
  last_poll_at: string
  last_poll_status: string
  last_error: string
  last_error_at: string
  last_success_at: string
  last_reply_at: string
  last_replied_user_id: string
  last_processed_message_id: string
  cursor: string
  processed_message_count: number
}

export interface WeixinAutoReplyProcessResult {
  ok: boolean
  status: string
  processed: number
  skipped: number
  duplicates: number
  errors: number
  cursor_advanced: boolean
  cursor?: string
  error?: string
  poison_skipped?: number
}

export interface WeixinAutoReplyRule {
  id: number
  user_id: string
  rule_name: string
  match_type: WeixinAutoReplyMatchType
  match_pattern: string
  reply_content: string
  is_active: boolean
  priority: number
  created_at: string
  updated_at: string
}

export interface WeixinAutoReplyRuleCreate {
  rule_name: string
  match_type?: WeixinAutoReplyMatchType
  match_pattern: string
  reply_content: string
  is_active?: boolean
  priority?: number
}

export interface WeixinAutoReplyRuleUpdate {
  rule_name?: string
  match_type?: WeixinAutoReplyMatchType
  match_pattern?: string
  reply_content?: string
  is_active?: boolean
  priority?: number
}

export const weixinAPI = {
  getConfig: () => api.get<WeixinConfig>('/skills/weixin/config'),
  saveConfig: (config: WeixinConfig) => api.post('/skills/weixin/config', config),
  healthCheck: (config: WeixinConfig) => api.post<WeixinHealthCheckResult>('/skills/weixin/health-check', config),
  startQrLogin: (payload: WeixinQrStartRequest = {}) => api.post<WeixinQrStartResponse>('/skills/weixin/qr/start', payload),
  waitQrLogin: (payload: WeixinQrWaitRequest) => api.post<WeixinQrWaitResponse>('/skills/weixin/qr/wait', payload),
  exitQrLogin: (payload: WeixinQrExitRequest) => api.post<WeixinQrExitResponse>('/skills/weixin/qr/exit', payload),
  getBinding: () => api.get<WeixinBindingInfo>('/weixin/binding'),
  saveBinding: (data: WeixinBindingCreate) => api.post<WeixinBindingInfo>('/weixin/binding', data),
  deleteBinding: () => api.delete('/weixin/binding'),
  getParams: () => api.get<WeixinParamsConfig>('/weixin/config'),
  updateParams: (data: WeixinParamsUpdate) => api.put<WeixinParamsConfig>('/weixin/config', data),
  getAutoReplyStatus: () => api.get<WeixinAutoReplyStatus>('/weixin/auto-reply/status'),
  startAutoReply: () => api.post<WeixinAutoReplyStatus>('/weixin/auto-reply/start'),
  stopAutoReply: () => api.post<WeixinAutoReplyStatus>('/weixin/auto-reply/stop'),
  restartAutoReply: () => api.post<WeixinAutoReplyStatus>('/weixin/auto-reply/restart'),
  processAutoReplyOnce: () => api.post<WeixinAutoReplyProcessResult>('/weixin/auto-reply/process-once'),
  getRules: () => api.get<WeixinAutoReplyRule[]>('/weixin/auto-reply/rules'),
  createRule: (payload: WeixinAutoReplyRuleCreate) =>
    api.post<WeixinAutoReplyRule>('/weixin/auto-reply/rules', payload),
  updateRule: (ruleId: number, payload: WeixinAutoReplyRuleUpdate) =>
    api.put<WeixinAutoReplyRule>(`/weixin/auto-reply/rules/${ruleId}`, payload),
  deleteRule: (ruleId: number) =>
    api.delete<{ message: string }>(`/weixin/auto-reply/rules/${ruleId}`),
  // 多媒体消息查询
  listRecentMultimedia: (params?: { limit?: number; media_type?: 'image' | 'voice' | 'file' | 'video' }) =>
    api.get<WeixinMultimediaMessage[]>('/weixin/multimedia/recent', { params }),
  getMultimediaDetail: (messageId: string) =>
    api.get<WeixinMultimediaDetail>(`/weixin/multimedia/${messageId}`),
}

export interface WeixinMultimediaMessage {
  message_id: string
  from_user_id: string
  message_type: string
  text: string
  media_type: 'image' | 'voice' | 'file' | 'video' | ''
  media_id: string
  file_url: string
  file_name: string
  file_size: number
  duration_ms: number
  media_format: string
  timestamp: string
}

export interface WeixinMultimediaDetail {
  message_id: string
  session_id: string
  content: string
  role: string
  timestamp: string
  reasoning_content: string
  tool_events: Array<Record<string, unknown>>
}

// 微信 WebSocket 实时消息事件类型
export type WeixinWsEvent =
  | { event: 'connected'; user_id: string }
  | { event: 'new_message'; message_id: string; from_user_id: string; text: string; message_type: string; multimedia: WeixinMultimediaMessage | null; timestamp: string }
  | { event: 'ping'; timestamp: string }
