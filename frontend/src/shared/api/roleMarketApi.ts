/**
 * 角色市场 API 模块，提供市场角色浏览、安装、发布和评分接口。
 */
import api from '@/shared/api/api'

const BASE = '/role-market'

/** 市场角色信息 */
export interface MarketRole {
  id: string
  name: string
  description: string
  avatar_url: string
  is_preset: boolean
  usage_count: number
  category: string
  created_at: string | null
}

/** 市场分类信息 */
export interface MarketCategory {
  id: string
  name: string
}

/** 市场角色列表响应 */
export interface MarketRoleListResponse {
  total: number
  page: number
  page_size: number
  items: MarketRole[]
}

/** 获取市场角色列表 */
export async function getMarketRoles(params?: {
  category?: string
  sort?: string
  page?: number
  page_size?: number
}): Promise<MarketRoleListResponse> {
  const { data } = await api.get(BASE, { params })
  return data
}

/** 获取市场分类列表 */
export async function getCategories(): Promise<{ categories: MarketCategory[] }> {
  const { data } = await api.get(`${BASE}/categories`)
  return data
}

/** 发布角色到市场 */
export async function publishRole(
  roleId: string,
  category?: string,
  tags?: string[]
): Promise<{ ok: boolean }> {
  const { data } = await api.post(`${BASE}/publish`, {
    role_id: roleId,
    category: category || 'general',
    tags: tags || [],
  })
  return data
}

/** 从市场安装角色 */
export async function installRole(
  roleId: string
): Promise<{ ok: boolean; installed_role_id?: string }> {
  const { data } = await api.post(`${BASE}/install/${roleId}`)
  return data
}

/** 为角色评分 */
export async function rateRole(
  roleId: string,
  rating: number,
  comment?: string
): Promise<{ ok: boolean }> {
  const { data } = await api.post(`${BASE}/${roleId}/rate`, {
    rating,
    comment: comment || '',
  })
  return data
}
