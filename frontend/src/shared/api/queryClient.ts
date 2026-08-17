/**
 * TanStack Query 全局 QueryClient 单例。
 *
 * 设计目标：
 *   - 统一服务端状态管理（缓存、失效、重试、后台刷新）
 *   - 默认 staleTime 60s：避免短时间内重复请求（多 Tab Container 共享缓存）
 *   - 默认 gcTime 5min：缓存未被观察的查询保留 5 分钟，便于切换页面快速恢复
 *   - 默认 retry 1：网络抖动时单次重试，避免对失败请求过度重试
 *
 * 注意：
 *   - 共享 axios 实例与所有安全拦截器仍由 `client.ts` 提供，queryFn 直接调用各域 API 模块
 *   - SSE 流式响应（chatAPI.sendMessageStream）不走 TanStack Query，保持现有 fetch 流式实现
 */
import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 数据被视为"新鲜"的时长，期间不会发起后台刷新
      // 60 秒：覆盖用户在 5 个设置 Tab 间快速切换的场景，避免每次 mount 重复请求
      staleTime: 60 * 1000,
      // 未被观察的缓存保留时长（5 分钟），过期后由 GC 回收
      gcTime: 5 * 60 * 1000,
      // 失败重试次数（单次，避免对错误请求过度重试）
      retry: 1,
      // 默认不在窗口聚焦时自动刷新（避免后台标签页切换造成意外请求风暴）
      refetchOnWindowFocus: false,
    },
    mutations: {
      // 变更操作默认不重试（写操作应由用户主动重试）
      retry: 0,
    },
  },
})

export default queryClient
