/**
 * 用户画像 API 模块——画像提取、事实管理、统计查询与导出。
 */

import { sharedApi } from '@/shared/api/api'

const PROFILE_BASE = '/user/profile'

/* ── 类型定义 ──────────────────────────────────────────────── */

export interface ProfileFact {
  id: string
  category: string
  category_label: string
  fact_key: string
  fact_value: string
  confidence: number
  confidence_label: string
  source_type: string
  is_active: boolean
  verification_count: number
  access_count: number
  first_observed_at: string | null
  last_updated_at: string | null
  source_session_id?: string | null
}

export interface FactsListResponse {
  facts: ProfileFact[]
  total: number
  categories: Record<string, number>
}

export interface ExtractRequest {
  session_ids?: string[]
  model_name?: string
}

export interface ExtractResult {
  extraction_id: string
  status: string
  message: string
  conversation_turns_analyzed: number
  behavior_logs_analyzed: number
  facts_added: number
  facts_updated: number
  facts_deleted: number
  facts_unchanged: number
  model: string
  duration_ms: number
}

export interface ProfileStats {
  total_active_facts: number
  total_archived_facts: number
  category_distribution: Record<string, number>
  confidence_distribution: Record<string, number>
  source_distribution: Record<string, number>
  dimensions_filled: number
  total_dimensions: number
  completeness_pct: number
  avg_confidence: number
}

export interface ProfileSummary {
  total_facts: number
  categories: Record<string, {
    label: string
    facts: ProfileFact[]
  }>
  high_confidence_count: number
  medium_confidence_count: number
  low_confidence_count: number
}

export interface ExtractionLog {
  id: string
  trigger_type: string
  status: string
  conversation_turns_analyzed: number
  behavior_logs_analyzed: number
  facts_added: number
  facts_updated: number
  facts_deleted: number
  facts_unchanged: number
  llm_model_used: string | null
  extraction_duration_ms: number | null
  error_message: string | null
  created_at: string
}

export interface ProfileDimension {
  label: string
  description: string
  priority: number
  fact_keys: string[]
}

export interface ProfileDimensionsResponse {
  categories: Record<string, ProfileDimension>
}

export interface ProfileContextResponse {
  profile_context: string
  char_count: number
}

/* ── API 函数 ──────────────────────────────────────────────── */

/** 手动触发画像提取 */
export async function extractProfile(payload: ExtractRequest): Promise<ExtractResult> {
  const { data } = await sharedApi.post(`${PROFILE_BASE}/extract`, payload)
  return data
}

/** 自动触发画像提取 */
export async function autoExtractProfile(): Promise<ExtractResult> {
  const { data } = await sharedApi.post(`${PROFILE_BASE}/extract/auto`)
  return data
}

/** 获取画像事实列表 */
export async function getProfileFacts(params?: {
  category?: string
  min_confidence?: number
  active_only?: boolean
  limit?: number
}): Promise<FactsListResponse> {
  const { data } = await sharedApi.get(`${PROFILE_BASE}/facts`, { params })
  return data
}

/** 获取单个画像事实 */
export async function getProfileFact(factId: string): Promise<ProfileFact> {
  const { data } = await sharedApi.get(`${PROFILE_BASE}/facts/${factId}`)
  return data
}

/** 手动编辑画像事实 */
export async function updateProfileFact(
  factId: string,
  payload: { fact_value: string; category?: string; fact_key?: string }
): Promise<ProfileFact> {
  const { data } = await sharedApi.put(`${PROFILE_BASE}/facts/${factId}`, payload)
  return data
}

/** 手动添加画像事实 */
export async function createProfileFact(payload: {
  category: string
  fact_key: string
  fact_value: string
  confidence?: number
}): Promise<ProfileFact> {
  const { data } = await sharedApi.post(`${PROFILE_BASE}/facts`, payload)
  return data
}

/** 删除画像事实 */
export async function deleteProfileFact(factId: string): Promise<{ message: string }> {
  const { data } = await sharedApi.delete(`${PROFILE_BASE}/facts/${factId}`)
  return data
}

/** 确认画像事实 */
export async function verifyProfileFact(factId: string): Promise<ProfileFact> {
  const { data } = await sharedApi.post(`${PROFILE_BASE}/facts/${factId}/verify`)
  return data
}

/** 否定画像事实 */
export async function disputeProfileFact(factId: string): Promise<ProfileFact> {
  const { data } = await sharedApi.post(`${PROFILE_BASE}/facts/${factId}/dispute`)
  return data
}

/** 全局刷新画像 */
export async function refreshProfile(): Promise<{ message: string; refreshed: number; archived: number }> {
  const { data } = await sharedApi.post(`${PROFILE_BASE}/refresh`)
  return data
}

/** 获取画像摘要 */
export async function getProfileSummary(): Promise<ProfileSummary> {
  const { data } = await sharedApi.get(`${PROFILE_BASE}/summary`)
  return data
}

/** 获取画像统计 */
export async function getProfileStats(): Promise<ProfileStats> {
  const { data } = await sharedApi.get(`${PROFILE_BASE}/stats`)
  return data
}

/** 获取 Agent 上下文注入的画像文本 */
export async function getProfileContext(): Promise<ProfileContextResponse> {
  const { data } = await sharedApi.get(`${PROFILE_BASE}/context`)
  return data
}

/** 导出用户画像 */
export async function exportProfile(): Promise<Record<string, unknown>> {
  const { data } = await sharedApi.get(`${PROFILE_BASE}/export`)
  return data
}

/** 清空所有画像数据 */
export async function purgeProfile(): Promise<{ message: string }> {
  const { data } = await sharedApi.delete(`${PROFILE_BASE}/purge`)
  return data
}

/** 获取提取日志 */
export async function getExtractionLogs(params?: {
  limit?: number
  offset?: number
}): Promise<{ total: number; logs: ExtractionLog[] }> {
  const { data } = await sharedApi.get(`${PROFILE_BASE}/extraction-logs`, { params })
  return data
}

/** 获取画像维度定义 */
export async function getProfileDimensions(): Promise<ProfileDimensionsResponse> {
  const { data } = await sharedApi.get(`${PROFILE_BASE}/dimensions`)
  return data
}

/* ── 画像设置（N 值与探针触发条件）── */

/**
 * 画像设置所在的路径。
 * 注意：后端 router prefix 为 /api/profile（绝对前缀，不走 /api/v1），
 * 而 sharedApi 的 baseURL 已包含 /api，因此此处使用 /profile/settings。
 */
const PROFILE_SETTINGS_PATH = '/profile/settings'

/** 探针触发条件 flags */
export interface ProbeFlags {
  /** 低置信度：画像事实置信度低于阈值时生成探针让用户确认 */
  low_confidence: boolean
  /** 新兴趣不确定：检测到新兴趣但无法归类时生成探针 */
  new_interest: boolean
  /** 定期复核：每 N 轮对话触发一次画像复核 */
  periodic_review: boolean
}

/** 画像设置完整结构 */
export interface ProfileSettings {
  /** N 轮阈值（3-20），达到后触发自主画像提取 */
  n_threshold: number
  /** 探针触发条件 */
  probe_flags: ProbeFlags
  /** 距上次提取的对话轮数 */
  turns_since_last_extract: number
  /** 上次提取时间（ISO 字符串），可能为 null */
  last_extracted_at: string | null
}

/** 画像设置更新请求载荷，仅传需要变更的字段 */
export interface ProfileSettingsUpdatePayload {
  /** N 轮阈值（3-20） */
  n_threshold?: number
  /** 探针触发条件，可仅传部分字段 */
  probe_flags?: Partial<ProbeFlags>
}

/** 获取当前用户的画像设置 */
export async function getProfileSettings(): Promise<ProfileSettings> {
  const { data } = await sharedApi.get<ProfileSettings>(PROFILE_SETTINGS_PATH)
  return data
}

/** 更新当前用户的画像设置（仅传需要变更的字段） */
export async function updateProfileSettings(
  payload: ProfileSettingsUpdatePayload
): Promise<ProfileSettings> {
  const { data } = await sharedApi.put<ProfileSettings>(PROFILE_SETTINGS_PATH, payload)
  return data
}
