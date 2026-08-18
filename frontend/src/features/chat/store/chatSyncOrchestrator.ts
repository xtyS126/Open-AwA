/**
 * 前端状态副作用编排层（单一咽喉点）。
 *
 * 通过 zustand subscribe 集中监听各分域 Store 的状态变化，统一触发：
 * 1. 持久化：conversations / pinnedConversations / sessionId / 偏好 / 选中模型
 *    写入 localStorage + 按需同步到服务端。
 * 2. 跨 Store 联动：选中推理模型时自动开启思考模式。
 * 3. 维护 thinkingEnabled 快照，供 sessionStore 跨域读取。
 *
 * 收敛后，各 setter 只负责更新 state，不再手工调用持久化或跨域 getState()，
 * 新增 setter 即使忘记持久化也不会导致状态漂移（由本层统一兜底）。
 */

import { safeGetItem } from '@/shared/utils/safeStorage'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useModelStore } from '@/features/chat/store/modelStore'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'
import {
  consumeSync,
  setThinkingSnapshot,
} from '@/features/chat/store/chatSyncRegistry'
import {
  persistOutputMode,
  persistSelectedModel,
  persistThinkingEnabled,
  persistThinkingDepth,
  persistPinnedConversations,
} from '@/features/chat/store/chatStoreEffects'
import {
  setActiveSessionId,
  setConversationSummaries,
} from '@/features/chat/storage/chatPersistence'

/** 判断指定模型标识是否为推理模型（包含 reasoner/r1/o1/o3） */
function isReasonerModel(model: string): boolean {
  const lower = model.toLowerCase()
  return (
    lower.includes('reasoner') ||
    lower.includes('r1') ||
    lower.includes('o1') ||
    lower.includes('o3')
  )
}

/** 编排层是否已安装，保证幂等 */
let installed = false

/**
 * 安装所有跨 Store 订阅。幂等，可安全重复调用。
 * 在应用入口（chatStore 兼容入口）加载时自动安装。
 */
export function setupChatSync(): void {
  if (installed) return
  installed = true

  // 初始化 thinkingEnabled 快照，保持与 preferenceStore 当前值一致
  setThinkingSnapshot(usePreferenceStore.getState().thinkingEnabled)

  // 会话层持久化：摘要 / 固定列表 / 活动会话
  useSessionStore.subscribe((state, prev) => {
    if (state.conversations !== prev.conversations) {
      setConversationSummaries(state.conversations)
    }
    if (state.pinnedConversations !== prev.pinnedConversations) {
      persistPinnedConversations(state.pinnedConversations)
    }
    if (state.sessionId !== prev.sessionId) {
      setActiveSessionId(state.sessionId)
    }
  })

  // 偏好层持久化 + thinkingEnabled 快照维护
  usePreferenceStore.subscribe((state, prev) => {
    if (state.outputMode !== prev.outputMode) {
      persistOutputMode(state.outputMode, consumeSync('outputMode'))
    }
    if (state.thinkingEnabled !== prev.thinkingEnabled) {
      persistThinkingEnabled(state.thinkingEnabled, consumeSync('thinkingEnabled'))
      setThinkingSnapshot(state.thinkingEnabled)
    }
    if (state.thinkingDepth !== prev.thinkingDepth) {
      persistThinkingDepth(state.thinkingDepth, consumeSync('thinkingDepth'))
    }
  })

  // 模型层持久化 + 跨 Store 联动（推理模型自动开启思考模式）
  useModelStore.subscribe((state, prev) => {
    if (state.selectedModel === prev.selectedModel) return
    const selectedModel = state.selectedModel
    persistSelectedModel(selectedModel, consumeSync('selectedModel'))

    // 推理模型自动开启思考模式（仅当用户未显式关闭时）；不同步到服务端，由 thinkingEnabled 自身同步
    if (
      selectedModel &&
      isReasonerModel(selectedModel) &&
      safeGetItem('chat_thinking_enabled', '') !== 'false'
    ) {
      usePreferenceStore.getState().setThinkingEnabled(true, { syncToServer: false })
    }
  })
}

// 模块加载即自动安装跨 Store 订阅（setupChatSync 幂等）。chatStore 兼容入口与 main.tsx
// 应用入口均通过副作用 import 加载本模块，自调用确保编排层的持久化与跨 Store 联动真正生效，
// 避免各分域 Store 纯化后持久化失效。
setupChatSync()