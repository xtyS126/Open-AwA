/** 应用初始化缓存，供认证失效和测试统一复位。 */

export interface AppInitializationResult {
  isAuthenticated: boolean
  user?: {
    username: string
    nickname?: string | null
    avatar_url?: string | null
    email?: string | null
    phone?: string | null
    role?: string
  }
}

let initializationPromise: Promise<AppInitializationResult> | null = null
let cachedInitializationResult: AppInitializationResult | null = null

export const getInitializationPromise = (): Promise<AppInitializationResult> | null => initializationPromise

export const setInitializationPromise = (value: Promise<AppInitializationResult> | null): void => {
  initializationPromise = value
}

export const getCachedInitializationResult = (): AppInitializationResult | null => cachedInitializationResult

export const setCachedInitializationResult = (value: AppInitializationResult | null): void => {
  cachedInitializationResult = value
}

export const resetAppInitializationCache = (): void => {
  initializationPromise = null
  cachedInitializationResult = null
}
