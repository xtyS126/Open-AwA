/**
 * Soul 画像 API 模块 — 封装 Soul 画像的五层洋葱模型后端通信。
 */
import { sharedApi } from '@/shared/api/api'

const SOUL_BASE = '/api/soul'

/* ── 类型定义 ──────────────────────────────────────────────── */

/** 单层画像数据 */
export interface LayerData {
  description: string
  structured_data: Record<string, unknown>
  confidence: number
}

/** 五层洋葱画像 */
export interface OnionProfile {
  user_id: string
  surface: LayerData
  interest: LayerData
  role: LayerData
  values: LayerData
  core: LayerData
  updated_at: string
}

/** 画像查询响应 */
export interface ProfileResponse {
  profile: OnionProfile
}

/** 画像覆盖层编辑请求 */
export interface OverrideRequest {
  layer: string
  overrides: Record<string, unknown>
}

/** 兴趣探针 */
export interface Probe {
  id: number
  hypothesis: string
  status: 'pending' | 'confirmed' | 'rejected'
  probe_question: string
  confidence: number
}

/** 探针列表响应 */
export interface ProbeResponse {
  probes: Probe[]
}

/* ── API 函数 ──────────────────────────────────────────────── */

/** 获取当前用户的五层洋葱画像 */
export async function getProfile(): Promise<ProfileResponse> {
  const { data } = await sharedApi.get<ProfileResponse>(`${SOUL_BASE}/profile`)
  return data
}

/** 更新画像覆盖层（编辑某一层的结构化数据） */
export async function updateOverrides(overrides: OverrideRequest): Promise<void> {
  await sharedApi.put(`${SOUL_BASE}/profile/overrides`, overrides)
}

/** 获取待确认的兴趣探针列表 */
export async function getProbes(): Promise<ProbeResponse> {
  const { data } = await sharedApi.get<ProbeResponse>(`${SOUL_BASE}/probes`)
  return data
}

/** 对兴趣探针做出确认或拒绝响应 */
export async function respondProbe(
  probeId: number,
  status: 'confirmed' | 'rejected'
): Promise<void> {
  await sharedApi.post(`${SOUL_BASE}/probes/${probeId}/respond`, { status })
}

/** 初始化用户画像（首次创建） */
export async function initProfile(): Promise<void> {
  await sharedApi.post(`${SOUL_BASE}/profile/init`)
}