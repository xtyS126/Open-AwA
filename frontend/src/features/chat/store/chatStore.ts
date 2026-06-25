/**
 * [Deprecated] chatStore 兼容入口。
 *
 * 此文件已拆分为 4 个独立的分域 Store，请直接从对应 Store 导入：
 * - useSessionStore: 会话相关状态（messages, sessionId, conversations 等）
 * - useModelStore: 模型相关状态（selectedModel, modelOptions 等）
 * - useToolCallStore: 工具调用相关状态（activeToolCalls）
 * - usePreferenceStore: 偏好相关状态（outputMode, thinkingEnabled, thinkingDepth）
 *
 * 副作用（localStorage 持久化 + 服务端同步）已提取到：
 * - @/shared/store/chatStoreEffects
 *
 * 派生状态选择器位于：
 * - @/shared/store/selectors
 *
 * 迁移示例：
 *   // 旧：
 *   import { useChatStore } from '@/features/chat/store/chatStore'
 *   const messages = useChatStore(s => s.messages)
 *
 *   // 新：
 *   import { useSessionStore } from '@/features/chat/store/sessionStore'
 *   const messages = useSessionStore(s => s.messages)
 */
export { useSessionStore } from '@/features/chat/store/sessionStore'
export { useModelStore, type ModelOption } from '@/features/chat/store/modelStore'
export { useToolCallStore } from '@/features/chat/store/toolCallStore'
export { usePreferenceStore } from '@/features/chat/store/preferenceStore'
export type { PreferenceMutationOptions } from '@/shared/store/chatStoreEffects'
