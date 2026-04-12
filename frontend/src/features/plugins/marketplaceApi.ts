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
export function searchPlugins(query: string) {
  return api.get<MarketplaceSearchResponse>('/marketplace/plugins/search', {
    params: { q: query },
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
