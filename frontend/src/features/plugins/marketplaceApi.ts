/**
 * 插件市场 API 模块，封装与后端市场接口的通信逻辑。
 */
import api from '@/shared/api/api'

/** 插件市场单个插件数据结构 */
export interface MarketplacePlugin {
  id: string
  name: string
  description: string
  author: string
  version: string
  category: string
  tags: string[]
  download_url: string
  icon: string
  install_count: number
  /** 插件来源，'builtin' 表示系统内置（市场不展示） */
  source?: string
}

/** 插件列表/搜索响应结构 */
export interface MarketplaceSearchResponse {
  plugins: MarketplacePlugin[]
  total: number
  page: number
  page_size: number
}

/** 获取插件列表（支持分类筛选和分页） */
export function getPlugins(params: {
  category?: string
  page?: number
  page_size?: number
}) {
  return api.get<MarketplaceSearchResponse>('/marketplace/plugins', { params })
}

/** 搜索插件 */
export function searchPlugins(query: string, page?: number, pageSize?: number) {
  return api.get<MarketplaceSearchResponse>('/marketplace/plugins/search', {
    params: { q: query, page, page_size: pageSize },
  })
}

/** 获取插件详情 */
export function getPluginDetail(id: string) {
  return api.get<MarketplacePlugin>(`/marketplace/plugins/${id}`)
}

/** 从市场安装插件 */
export function installPlugin(id: string) {
  return api.post(`/marketplace/plugins/${id}/install`)
}

/** 获取分类列表 */
export function getCategories() {
  return api.get<{ categories: string[] }>('/marketplace/categories')
}

/* ==================== 评分与评论相关类型 ==================== */

/** 插件评分汇总信息 */
export interface PluginRatingSummary {
  /** 平均评分（0-5，保留一位小数） */
  average_score: number
  /** 总评分人数 */
  total_count: number
  /** 各星级分布，键为 1-5，值为对应人数 */
  distribution: Record<number, number>
  /** 当前用户的评分（未评分时为 null） */
  user_score: number | null
}

/** 单条插件评论 */
export interface PluginReview {
  id: number
  plugin_id: string
  user_id: string
  username: string
  content: string
  /** 评论附带的评分（1-5） */
  rating: number
  is_hidden: boolean
  created_at: string
  updated_at: string
}

/** 评论列表分页响应 */
export interface PluginReviewListResponse {
  reviews: PluginReview[]
  total: number
  page: number
  page_size: number
}

/* ==================== 评分与评论 API ==================== */

/** 创建或更新当前用户对指定插件的评分（1-5 星），返回最新汇总 */
export function ratePlugin(pluginId: string, score: number) {
  return api.post<PluginRatingSummary>(`/marketplace/plugins/${pluginId}/rate`, {
    score,
  })
}

/** 获取指定插件的评分汇总（含当前用户评分） */
export function getPluginRating(pluginId: string) {
  return api.get<PluginRatingSummary>(`/marketplace/plugins/${pluginId}/rating`)
}

/** 发表评论，可附带评分 */
export function createReview(
  pluginId: string,
  payload: { content: string; rating?: number }
) {
  return api.post<PluginReview>(`/marketplace/plugins/${pluginId}/reviews`, payload)
}

/** 分页获取评论列表 */
export function listReviews(pluginId: string, page: number = 1, pageSize: number = 10) {
  return api.get<PluginReviewListResponse>(`/marketplace/plugins/${pluginId}/reviews`, {
    params: { page, page_size: pageSize },
  })
}

/** 更新评论（仅作者可调用） */
export function updateReview(
  reviewId: number,
  payload: { content?: string; rating?: number }
) {
  return api.put<PluginReview>(`/marketplace/reviews/${reviewId}`, payload)
}

/** 删除评论（作者或管理员可调用） */
export function deleteReview(reviewId: number) {
  return api.delete<{ message: string }>(`/marketplace/reviews/${reviewId}`)
}
