/**
 * 跨 Store 同步注册表（叶子模块，不依赖任何 Store）。
 *
 * 职责：
 * 1. 暂存"待持久化"的同步意图（某字段变更是否需要同步到服务端）。
 *    由 setter 调用 markSync 记录意图，编排层订阅到状态变化后 consumeSync 消费并执行持久化，
 *    从而使 setter 只负责更新 state，持久化的时机与是否同步到服务端集中在编排层。
 * 2. 维护实时 thinkingEnabled 快照，供 sessionStore 跨域读取。
 *    避免 store 之间直接 getState() 互读造成的隐式耦合。
 *
 * 本模块刻意不 import 任何 Store，避免与 store 模块产生循环依赖。
 */
import { safeGetItem } from '@/shared/utils/safeStorage'

/** 待持久化的同步意图表：字段名 -> 是否同步到服务端 */
const pendingSyncMap: Record<string, boolean> = {}

/**
 * 记录某字段本轮变更是否需要同步到服务端。
 * 由 setter 在 set state 之前调用。
 * @param field 字段名（outputMode / thinkingEnabled / thinkingDepth / selectedModel）
 * @param syncToServer 是否同步到服务端
 */
export function markSync(field: string, syncToServer: boolean): void {
  pendingSyncMap[field] = syncToServer
}

/**
 * 消费某字段的同步意图。若 setter 未记录则默认同步到服务端（与 chatStoreEffects 默认行为一致）。
 * @param field 字段名
 */
export function consumeSync(field: string): boolean {
  if (field in pendingSyncMap) {
    const value = pendingSyncMap[field]
    delete pendingSyncMap[field]
    return value
  }
  return true
}

/**
 * 实时 thinkingEnabled 快照。默认从 localStorage 推断，保证编排层未初始化时也能读到合理初值。
 */
let thinkingEnabledSnapshot =
  safeGetItem('chat_thinking_enabled', '') !== 'false'

/** 更新 thinkingEnabled 快照（由编排层在订阅到 preferenceStore 变化时同步） */
export function setThinkingSnapshot(enabled: boolean): void {
  thinkingEnabledSnapshot = enabled
}

/** 读取当前 thinkingEnabled 快照，供 sessionStore 跨域读取时使用（避免直接 getState 互读） */
export function getThinkingEnabled(): boolean {
  return thinkingEnabledSnapshot
}

/** 仅供测试：重置快照状态，避免跨用例污染 */
export function resetThinkingSnapshotForTests(): void {
  thinkingEnabledSnapshot = safeGetItem('chat_thinking_enabled', '') !== 'false'
}