/**
 * 宠物事件联动 —— 事件类型定义与 PetEvent 接口。
 *
 * ChatPage 通过 petEventBus 发出事件，宠物组件（PetSprite / Live2DViewer / PetOverlayApp）
 * 监听事件并映射到对应动画或表情。
 */

/** 宠物事件类型枚举 */
export const PetEventType = {
  /** 用户发送消息 */
  CHAT_USER_MESSAGE: 'chat:user-message',
  /** AI 开始思考（流式输出开始） */
  CHAT_AI_THINKING: 'chat:ai-thinking',
  /** AI 回复完成（流式输出结束） */
  CHAT_AI_REPLY: 'chat:ai-reply',
  /** 检测到积极情绪 */
  CHAT_POSITIVE: 'chat:positive',
  /** 检测到消极情绪 */
  CHAT_NEGATIVE: 'chat:negative',
  /** 陪伴羁绊升级 */
  COMPANION_BOND_UPGRADE: 'companion:bond-upgrade',
  /** 陪伴里程碑 */
  COMPANION_MILESTONE: 'companion:milestone',
} as const

export type PetEventType = typeof PetEventType[keyof typeof PetEventType]

/** 宠物事件 */
export interface PetEvent {
  /** 事件类型 */
  type: PetEventType
  /** 事件附加数据 */
  payload?: Record<string, unknown>
  /** 事件时间戳（毫秒） */
  timestamp: number
}

/** 积极情绪关键词 */
const POSITIVE_KEYWORDS = ['开心', '高兴', '太好了', '恭喜', '喜欢', '爱你', '一起', '陪伴']

/** 消极情绪关键词 */
const NEGATIVE_KEYWORDS = ['难过', '伤心', '抱歉', '对不起', '遗憾', '失望']

/**
 * 检测文本中的情绪倾向
 * @returns 'positive' | 'negative' | null
 */
export function detectSentiment(text: string): 'positive' | 'negative' | null {
  for (const kw of POSITIVE_KEYWORDS) {
    if (text.includes(kw)) return 'positive'
  }
  for (const kw of NEGATIVE_KEYWORDS) {
    if (text.includes(kw)) return 'negative'
  }
  return null
}