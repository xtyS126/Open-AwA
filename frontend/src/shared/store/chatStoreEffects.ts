/**
 * chatStore 副作用集中管理。
 *
 * 将 localStorage 持久化与服务端偏好同步从 Store 的 setter 中提取为纯函数，
 * 使 Store 的 setter 只负责状态更新，副作用集中管理，便于测试与维护。
 */
import { safeSetItem } from '@/shared/utils/safeStorage'
import { syncPreferenceToServer } from '@/shared/utils/preferenceSync'

/** 偏好变更选项：是否同步到服务端 */
export interface PreferenceMutationOptions {
  syncToServer?: boolean
}

/**
 * 持久化输出模式到 localStorage，并按需同步到服务端。
 * @param mode 输出模式
 * @param syncToServer 是否同步到服务端
 */
export function persistOutputMode(mode: 'stream' | 'direct', syncToServer: boolean): void {
  safeSetItem('chat_output_mode', mode)
  if (syncToServer) {
    syncPreferenceToServer('outputMode', mode)
  }
}

/**
 * 持久化选中的模型到 localStorage，并按需同步到服务端。
 * @param model 模型标识
 * @param syncToServer 是否同步到服务端
 */
export function persistSelectedModel(model: string, syncToServer: boolean): void {
  safeSetItem('chat_selected_model', model)
  if (syncToServer) {
    syncPreferenceToServer('selectedModel', model)
  }
}

/**
 * 持久化思考模式开关到 localStorage，并按需同步到服务端。
 * @param enabled 是否启用思考模式
 * @param syncToServer 是否同步到服务端
 */
export function persistThinkingEnabled(enabled: boolean, syncToServer: boolean): void {
  safeSetItem('chat_thinking_enabled', enabled ? 'true' : 'false')
  if (syncToServer) {
    syncPreferenceToServer('thinkingEnabled', enabled)
  }
}

/**
 * 持久化思考深度到 localStorage，并按需同步到服务端。
 * @param depth 思考深度（0-5）
 * @param syncToServer 是否同步到服务端
 */
export function persistThinkingDepth(depth: number, syncToServer: boolean): void {
  safeSetItem('chat_thinking_depth', String(depth))
  if (syncToServer) {
    syncPreferenceToServer('thinkingDepth', depth)
  }
}

/**
 * 持久化固定的对话历史 ID 列表到 localStorage。
 * @param ids 固定的会话 ID 列表
 */
export function persistPinnedConversations(ids: string[]): void {
  safeSetItem('chat_pinned_conversations', JSON.stringify(ids))
}
