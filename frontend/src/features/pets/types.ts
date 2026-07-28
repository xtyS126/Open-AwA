/**
 * 宠物（Ambient Pet）相关 TypeScript 类型定义。
 * 与后端 /api/pets 接口的 Pydantic 响应模型精确对齐。
 */

/** 单个动画帧：精灵表索引与该帧显示时长（毫秒） */
export interface PetAnimationFrame {
  /** 该帧在精灵表中的全局索引 */
  sprite_index: number
  /** 该帧显示时长（毫秒） */
  duration_ms: number
}

/** 一组动画：帧序列、循环起点与回退动画名 */
export interface PetAnimation {
  /** 依次播放的帧序列 */
  frames: PetAnimationFrame[]
  /** 循环起点（指向 frames 数组的下标）；为 null 表示播完停在末帧 */
  loop_start: number | null
  /** 该动画不可用时回退使用的动画名（仅作元数据，前端不强制遵循） */
  fallback: string
}

/** 宠物完整信息（对应后端 PetResponse） */
export interface PetResponse {
  /** 唯一标识，内置形如 builtin:codex，自定义形如 custom:<uid>:<pet_id> */
  id: string
  /** slug 形式的宠物 ID，用于激活接口 */
  pet_id: string
  /** 展示名称 */
  display_name: string
  /** 描述 */
  description: string
  /** 精灵表版本号（1 或 2） */
  sprite_version: number
  /** 单帧宽度（像素） */
  frame_width: number
  /** 单帧高度（像素） */
  frame_height: number
  /** 精灵表列数 */
  columns: number
  /** 精灵表行数 */
  rows: number
  /** 总帧数 */
  frame_count: number
  /** 各动画定义，键为动画名 */
  animations: Record<string, PetAnimation>
  /** 是否为内置宠物 */
  is_builtin: boolean
  /** 精灵表是否就绪可绘制 */
  spritesheet_ready: boolean
  /** 是否为当前激活宠物 */
  is_active: boolean
  /** 创建时间（ISO 字符串，可选） */
  created_at?: string
}

/** 宠物列表响应 */
export interface PetListResponse {
  pets: PetResponse[]
  total: number
}

/** 当前激活宠物响应（pet_id 为 null 表示未激活） */
export interface PetActiveResponse {
  pet_id: string | null
  display_name: string | null
}