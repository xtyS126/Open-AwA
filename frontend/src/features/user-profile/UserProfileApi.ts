/**
 * 用户画像（五层洋葱模型）API 模块。
 * 封装 Soul Engine 后端三个端点：
 *   - GET  /api/soul/profile        获取五层画像（未建立时 data 为 null）
 *   - GET  /api/soul/probes         获取 pending 探针列表
 *   - POST /api/soul/probe/respond  确认/拒绝探针
 *
 * 后端统一响应信封：{ success: boolean, data: T | null, message: string }
 * 此处解包 axios 响应后直接返回信封，便于调用方按 success/data 分支处理。
 */
import api from '@/shared/api/api'

/** 后端统一响应信封 */
export interface ApiResponse<T> {
  success: boolean
  data: T | null
  message: string
}

/** 单层画像数据 */
export interface OnionLayerData {
  description: string
  structured_data: Record<string, unknown>
  confidence: number
}

/** 五层洋葱画像（从外到内：surface → interest → role → values → core） */
export interface OnionProfile {
  user_id: string
  surface: OnionLayerData
  interest: OnionLayerData
  role: OnionLayerData
  values: OnionLayerData
  core: OnionLayerData
  updated_at: string
}

/** 兴趣探针（pending 状态需用户确认/拒绝） */
export interface InterestProbe {
  id: number
  user_id: string
  hypothesis: string
  reasoning: Record<string, unknown> | null
  status: string
  probe_question: string | null
  created_at: string
  responded_at: string | null
}

/** 探针响应类型 */
export type ProbeResponse = 'confirmed' | 'rejected'

export const userProfileApi = {
  /**
   * 获取当前用户的五层画像。
   * 画像未建立时返回 { success: true, data: null, message: '画像尚未建立' }
   */
  getProfile: async (signal?: AbortSignal): Promise<ApiResponse<OnionProfile>> => {
    const { data } = await api.get<ApiResponse<OnionProfile>>('/soul/profile', { signal })
    return data
  },

  /** 获取 pending 状态的兴趣探针列表（后端已过滤 status=pending） */
  getProbes: async (signal?: AbortSignal): Promise<ApiResponse<InterestProbe[]>> => {
    const { data } = await api.get<ApiResponse<InterestProbe[]>>('/soul/probes', { signal })
    return data
  },

  /**
   * 确认或拒绝兴趣探针。
   * confirmed 提升对应 fact confidence 至 0.9，rejected 标记 is_active=False。
   */
  respondToProbe: async (
    probeId: number,
    response: ProbeResponse,
  ): Promise<ApiResponse<InterestProbe>> => {
    const { data } = await api.post<ApiResponse<InterestProbe>>(
      '/soul/probe/respond',
      { probe_id: probeId, response },
    )
    return data
  },
}
