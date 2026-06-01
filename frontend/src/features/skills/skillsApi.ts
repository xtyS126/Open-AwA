/**
 * 技能市场 API 模块 — 封装技能市场的后端通信。
 */
import api from '@/shared/api/api';

export interface MarketSkill {
  name: string;
  description: string;
  version: string;
  source: string;
  source_url: string;
  author: string;
  downloads: number;
  installed: boolean;
}

export interface MarketListResponse {
  skills: MarketSkill[];
  total: number;
}

/**
 * 获取技能市场中的可用技能列表。
 */
export async function listMarketSkills(search?: string, source?: string): Promise<MarketListResponse> {
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  if (source) params.set('source', source);
  const query = params.toString();
  const url = `/skills/market${query ? `?${query}` : ''}`;
  const response = await api.get<MarketListResponse>(url);
  return response.data;
}

/**
 * 从技能市场安装技能到技能池。
 */
export async function installMarketSkill(name: string, source?: string, sourceUrl?: string): Promise<void> {
  await api.post('/skills/market/install', {
    name,
    source: source || 'clawhub',
    source_url: sourceUrl,
  });
}
