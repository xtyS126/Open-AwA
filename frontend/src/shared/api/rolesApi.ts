/**
 * 角色 API 封装 — 提供角色 CRUD、预设模板获取、角色激活等接口。
 */
// 直接从 client 导入 axios 实例，避免经由 api.ts barrel 把全部业务 API 模块拉入页面关键路径
import { api } from '@/shared/api/client'
import type {
  AgentRole,
  RoleCreateRequest,
  RoleUpdateRequest,
  RoleActivateResponse,
} from '@/shared/types/role'

const BASE = '/roles'

/** 获取所有角色列表 */
export async function getRoles(): Promise<AgentRole[]> {
  const { data } = await api.get(BASE)
  return data
}

/** 获取角色详情 */
export async function getRole(roleId: string): Promise<AgentRole> {
  const { data } = await api.get(`${BASE}/${roleId}`)
  return data
}

/** 创建新角色 */
export async function createRole(roleData: RoleCreateRequest): Promise<AgentRole> {
  const { data } = await api.post(BASE, roleData)
  return data
}

/** 更新角色配置 */
export async function updateRole(roleId: string, roleData: RoleUpdateRequest): Promise<AgentRole> {
  const { data } = await api.put(`${BASE}/${roleId}`, roleData)
  return data
}

/** 删除角色 */
export async function deleteRole(roleId: string): Promise<void> {
  await api.delete(`${BASE}/${roleId}`)
}

/** 获取预设角色模板列表 */
export async function getPresetRoles(): Promise<AgentRole[]> {
  const { data } = await api.get(`${BASE}/presets`)
  return data
}

/** 激活角色 */
export async function activateRole(roleId: string, sessionId: string): Promise<RoleActivateResponse> {
  const { data } = await api.post(`${BASE}/${roleId}/activate`, { session_id: sessionId })
  return data
}
