/**
 * 宠物事件总线 —— 简单的发布/订阅模式。
 *
 * ChatPage 调用 emit() 发出事件，宠物组件调用 on() 注册监听。
 * 返回值为取消订阅函数，组件卸载时调用以清理。
 */
import type { PetEvent, PetEventType } from './petEvents'

type Listener = (event: PetEvent) => void
const listeners = new Map<string, Set<Listener>>()

export const petEventBus = {
  /** 发出事件 */
  emit(event: PetEvent): void {
    const set = listeners.get(event.type)
    if (set) {
      for (const listener of set) {
        try {
          listener(event)
        } catch {
          // 监听器异常不阻塞其他监听器
        }
      }
    }
  },

  /** 注册事件监听，返回取消订阅函数 */
  on(type: PetEventType, listener: Listener): () => void {
    let set = listeners.get(type)
    if (!set) {
      set = new Set()
      listeners.set(type, set)
    }
    set.add(listener)
    return () => {
      set!.delete(listener)
      if (set!.size === 0) {
        listeners.delete(type)
      }
    }
  },

  /** 移除事件监听 */
  off(type: PetEventType, listener: Listener): void {
    const set = listeners.get(type)
    if (set) {
      set.delete(listener)
      if (set.size === 0) {
        listeners.delete(type)
      }
    }
  },
}