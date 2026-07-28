/**
 * 环境变量管理 API 模块。
 */
import api from '@/shared/api/api';

export interface EnvVarItem {
  name: string;
  value: string;  // 敏感值已脱敏为 ****
  description: string;
  category: string;
  is_sensitive: boolean;
}

/**
 * 获取环境变量列表（敏感值已脱敏）。
 */
export async function listEnvVars(): Promise<EnvVarItem[]> {
  const response = await api.get<{ vars: EnvVarItem[] }>('/system/env-vars');
  return response.data.vars || [];
}

/**
 * 更新环境变量。
 */
export async function updateEnvVar(name: string, value: string): Promise<void> {
  await api.put('/system/env-vars', { name, value });
}

/**
 * 测试环境变量连接（如 API Key）。
 */
export async function testEnvVar(name: string): Promise<{ success: boolean; message: string }> {
  const response = await api.get<{ success: boolean; message: string }>(`/system/env-vars/${name}/test`);
  return response.data;
}
