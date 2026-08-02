import { useCallback, useEffect } from 'react'
import {
  Link,
  Outlet,
  useLocation as useTanStackLocation,
  useNavigate as useTanStackNavigate,
  useParams as useTanStackParams,
} from '@tanstack/react-router'

export { Link, Outlet }

export interface Location {
  pathname: string
  search: string
  hash: string
}

/**
 * 将解析后的查询对象还原为页面层沿用的 URL 查询字符串接口。
 */
export function useLocation(): Location {
  const location = useTanStackLocation()

  return {
    pathname: location.pathname,
    search: location.searchStr,
    hash: location.hash,
  }
}

export interface NavigateOptions {
  replace?: boolean
}

export type NavigateFunction = (to: string, options?: NavigateOptions) => Promise<void>

interface NavigateProps extends NavigateOptions {
  to: string
}

/**
 * 保留页面层现有的字符串导航接口，将路由库差异集中在边界内。
 */
export function useNavigate(): NavigateFunction {
  const navigate = useTanStackNavigate()

  return useCallback(
    (to: string, options?: NavigateOptions) => navigate({
      to,
      replace: options?.replace,
    }),
    [navigate],
  )
}

/**
 * 按目标值触发一次重定向，避免路由过渡重渲染时重复提交同一导航。
 */
export function Navigate({ to, replace }: NavigateProps) {
  const navigate = useNavigate()

  useEffect(() => {
    void navigate(to, { replace })
  }, [navigate, replace, to])

  return null
}

/**
 * 页面可以按自身路由声明收窄参数类型，未匹配的参数保持为 undefined。
 */
export function useParams<TParams extends Record<string, string | undefined>>(): TParams {
  const params = useTanStackParams({ strict: false, shouldThrow: false })

  return (params ?? {}) as TParams
}
