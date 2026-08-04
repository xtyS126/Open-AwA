export interface ShortTermMemory {
  id: number
  role: string
  content: string
  timestamp: string
  session_id?: string
}

export interface LongTermMemory {
  id: number
  content: string
  importance: number
  confidence?: number
  quality_score?: number
  archive_status?: string
  source_type?: string
  memory_layer?: string
  state?: string
  access_count?: number
  created_at?: string
  last_access?: string
  [key: string]: unknown
}

export interface Prompt {
  id?: string
  name: string
  content: string
  variables?: string
  is_active?: boolean
}

export interface BehaviorLog {
  id: number
  action_type: string
  details: string
  user_id?: string
  created_at: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
}

export interface ChatResponse {
  response: string
  session_id?: string
  metadata?: Record<string, unknown>
}

export interface ExecutionStep {
  action: string
  result: string
}

export interface BillingProvider {
  id: string
  name: string
  display_name?: string
  icon?: string | null
  api_endpoint?: string | null
  has_api_key?: boolean
  // 密钥状态：active 已配置且可用 / stale 旧算法密文已失效 / missing 未配置
  api_key_status?: 'active' | 'stale' | 'missing'
  selected_models?: string[]
  configuration_count?: number
}

export interface BillingModelConfiguration {
  id: number
  provider: string
  model: string
  display_name: string | null
  description: string | null
  icon?: string | null
  api_endpoint?: string | null
  api_key?: string | null
  has_api_key?: boolean
  // 密钥状态：active 已配置且可用 / stale 旧算法密文已失效 / missing 未配置
  api_key_status?: 'active' | 'stale' | 'missing'
  selected_models?: string[]
  is_active: boolean
  is_default: boolean
  sort_order: number
  created_at: string | null
  updated_at: string | null
}

export interface BillingProviderModel {
  id: number
  provider: string
  model: string
  input_price: number
  output_price: number
  currency: string
  context_window: number | null
  selected?: boolean
}

export const snakeToCamel = (str: string): string =>
  str.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase())

export const camelToSnake = (str: string): string =>
  str.replace(/[A-Z]/g, letter => `_${letter.toLowerCase()}`)

export const convertToCamelCase = <T>(obj: unknown): T => {
  if (Array.isArray(obj)) {
    return obj.map(item => convertToCamelCase<T>(item)) as T
  } else if (isRecord(obj)) {
    return Object.keys(obj).reduce((acc, key) => {
      const camelKey = snakeToCamel(key)
      const value = obj[key]
      return {
        ...acc,
        [camelKey]: convertToCamelCase<unknown>(value)
      }
    }, {} as T)
  }
  return obj as T
}

export const convertToSnakeCase = <T>(obj: unknown): T => {
  if (Array.isArray(obj)) {
    return obj.map(item => convertToSnakeCase<T>(item)) as T
  } else if (isRecord(obj)) {
    return Object.keys(obj).reduce((acc, key) => {
      const snakeKey = camelToSnake(key)
      const value = obj[key]
      return {
        ...acc,
        [snakeKey]: convertToSnakeCase<unknown>(value)
      }
    }, {} as T)
  }
  return obj as T
}

export interface ApiResponse<T> {
  data: T
  status?: number
  message?: string
}

export interface PaginationParams {
  page?: number
  limit?: number
  skip?: number
  offset?: number
}

export interface ApiError {
  message: string
  code?: string | number
  details?: Record<string, unknown>
}

export type ExtensionPointType =
  | 'tool'
  | 'hook'
  | 'command'
  | 'route'
  | 'event_handler'
  | 'scheduler'
  | 'middleware'
  | 'data_provider'

export interface PluginExtension {
  point: ExtensionPointType
  name: string
  version: string
  config?: Record<string, unknown>
}

export interface PluginManifest {
  name: string
  version: string
  pluginApiVersion: string
  description?: string
  author?: string
  permissions?: string[]
  extensions: PluginExtension[]
}

export interface ExtensionRegistration {
  pluginName: string
  point: ExtensionPointType
  name: string
  version: string
  config: Record<string, unknown>
}

export interface SchemaValidationResult {
  valid: boolean
  errors: string[]
}

/**
 * 类型守卫：判断给定值是否为可索引的对象（非数组、非 null）。
 * 用于替代 `value as Record<string, unknown>` 这种不安全的类型断言：
 * 通过运行时检查 + 类型谓词，让 TypeScript 在分支内自动将 unknown 收窄为 Record。
 */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * 安全地将任意值转换为 Record 类型。
 * - 若 value 已是可索引对象，原样返回（类型已收窄）
 * - 否则返回空对象，避免后续属性访问抛错
 *
 * 该函数内部不使用 `as` 断言，完全依赖类型守卫进行类型收窄。
 */
export function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {}
}
