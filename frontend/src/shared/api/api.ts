/**
 * API 模块统一入口（barrel）。
 * 客户端实例和认证逻辑在 client.ts，类型定义在 types.ts，
 * 各业务端点已按域拆分至同目录的 *Api.ts 文件（chatApi/authApi/skillsApi 等）。
 * 本文件仅做聚合再导出，保持既有 `from '@/shared/api/api'` 引用方零改动。
 *
 * 认证策略：
 *   - 单用户模式：使用 API Key (Bearer) 认证
 *   - 状态变更请求自动附加 X-CSRF-Token（CSRF 防御已恢复，对应 P0-9）
 *   - 应用启动或登录成功后调用 refreshCsrfToken() 拉取 per-session CSRF token
 */
import { api } from './client'

// 向后兼容：保持原有命名导出
export {
  getCachedApiKey,
  setTempApiKey,
  clearCachedApiKey,
  getApiErrorDetail,
  logStreamParseWarning,
  refreshCsrfToken,
  getCachedCsrfToken,
} from './client'

// 领域模块聚合再导出
export * from './chatApi'
export * from './authApi'
export * from './skillsApi'
export * from './pluginsApi'
export * from './opsApi'
export * from './memoryApi'
export * from './promptsApi'
export * from './scheduledTasksApi'
export * from './conversationApi'
export * from './behaviorApi'
export * from './weixinApi'
export * from './diaryApi'
export * from './issueFeedbackApi'

// 向后兼容：axios 客户端默认导出（既有领域文件依赖）
export { api as sharedApi }
export default api
