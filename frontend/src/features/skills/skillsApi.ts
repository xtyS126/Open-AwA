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

/** 单个市场源的错误信息（后端拉取失败时返回）。 */
export interface MarketSourceError {
  source: string;
  error: string;
}

export interface MarketListResponse {
  skills: MarketSkill[];
  total: number;
  /** 后端业务层错误信息（如配置缺失、未预期异常降级返回）。 */
  error?: string;
  /** 各市场源拉取失败的明细，单源失败时非空但 skills 可能有部分数据。 */
  source_errors?: MarketSourceError[];
}

/**
 * 获取技能市场中的可用技能列表。
 *
 * 错误降级约定（与后端 get_market_skills 对齐）：
 * - 后端源错误时返回 HTTP 200 + 空 skills + source_errors，不进入 catch 分支
 * - 仅当 axios 层抛出（网络错误、4xx/5xx）时进入 catch，由调用方决定展示文案
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
