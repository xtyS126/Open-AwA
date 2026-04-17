import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  pluginsAPI,
  PluginConfigSchemaResponse,
  PluginPermissionStatus,
  PluginPermissionUpdateResponse,
} from '@/shared/api/api'
import type { Plugin } from '@/features/dashboard/dashboard'

/** 文件系统中发现的插件元数据（来自 GET /plugins/discover） */
export interface DiscoveredPlugin {
  name: string
  version: string
  description: string
  path: string
  loaded: boolean
  state: string
  requested_permissions: string[]
}

const getErrorMessage = (error: unknown, fallback: string): string => {
  const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return fallback
}

export function usePluginList() {
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchPlugins = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await pluginsAPI.getAll()
      setPlugins(response.data || [])
    } catch (error) {
      setError(getErrorMessage(error, '插件列表加载失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPlugins()
  }, [fetchPlugins])

  return {
    plugins,
    loading,
    error,
    retry: fetchPlugins,
    refresh: fetchPlugins,
    setPlugins,
  }
}

/** 获取文件系统中发现的本地插件列表 */
export function useDiscoveredPlugins() {
  const [discovered, setDiscovered] = useState<DiscoveredPlugin[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchDiscovered = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await pluginsAPI.discover()
      // 后端可能返回 { discovered: [...], total_count } 或直接返回数组
      const data = response.data
      const list = Array.isArray(data) ? data : (data?.discovered || [])
      setDiscovered(list)
    } catch (error) {
      setError(getErrorMessage(error, '本地插件发现失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDiscovered()
  }, [fetchDiscovered])

  return {
    discovered,
    loading,
    error,
    retry: fetchDiscovered,
    refresh: fetchDiscovered,
  }
}

export function usePluginImport() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const retryRef = useRef<(() => Promise<unknown>) | null>(null)

  const runAction = useCallback(async <T,>(action: () => Promise<T>, fallbackError: string): Promise<T> => {
    setLoading(true)
    setError(null)
    retryRef.current = action
    try {
      return await action()
    } catch (error) {
      setError(getErrorMessage(error, fallbackError))
      throw error
    } finally {
      setLoading(false)
    }
  }, [])

  const importFromFile = useCallback(
    async (file: File) => runAction(() => pluginsAPI.upload(file), '插件本地导入失败'),
    [runAction],
  )

  const importFromUrl = useCallback(
    async (sourceUrl: string, timeoutSeconds: number = 30) =>
      runAction(() => pluginsAPI.importFromUrl(sourceUrl, timeoutSeconds), '插件远程导入失败'),
    [runAction],
  )

  const retry = useCallback(async () => {
    if (retryRef.current) {
      await runAction(retryRef.current, '导入重试失败')
    }
  }, [runAction])

  return { loading, error, retry, importFromFile, importFromUrl }
}

export function usePluginDelete() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const retryRef = useRef<(() => Promise<unknown>) | null>(null)

  const runAction = useCallback(async <T,>(action: () => Promise<T>, fallbackError: string): Promise<T> => {
    setLoading(true)
    setError(null)
    retryRef.current = action
    try {
      return await action()
    } catch (error) {
      setError(getErrorMessage(error, fallbackError))
      throw error
    } finally {
      setLoading(false)
    }
  }, [])

  const deleteOne = useCallback(
    async (pluginId: string) => runAction(() => pluginsAPI.uninstall(pluginId), '插件删除失败'),
    [runAction],
  )

  const deleteBatch = useCallback(
    async (pluginIds: string[]) =>
      runAction(
        async () => {
          const settled = await Promise.allSettled(pluginIds.map((pluginId) => pluginsAPI.uninstall(pluginId)))
          const successIds: string[] = []
          const failed: Array<{ pluginId: string; reason: string }> = []
          settled.forEach((result, index) => {
            if (result.status === 'fulfilled') {
              successIds.push(pluginIds[index])
              return
            }
            failed.push({
              pluginId: pluginIds[index],
              reason: getErrorMessage(result.reason, '删除失败'),
            })
          })
          return { successIds, failed }
        },
        '批量删除失败',
      ),
    [runAction],
  )

  const retry = useCallback(async () => {
    if (retryRef.current) {
      await runAction(retryRef.current, '删除重试失败')
    }
  }, [runAction])

  return { loading, error, retry, deleteOne, deleteBatch }
}

export function usePluginDetail(pluginId: string | null) {
  const [detail, setDetail] = useState<Plugin | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchDetail = useCallback(async () => {
    if (!pluginId) {
      setDetail(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const response = await pluginsAPI.getOne(pluginId)
      setDetail(response.data || null)
    } catch (error) {
      setError(getErrorMessage(error, '插件详情加载失败'))
    } finally {
      setLoading(false)
    }
  }, [pluginId])

  useEffect(() => {
    fetchDetail()
  }, [fetchDetail])

  return { detail, loading, error, retry: fetchDetail }
}

type PluginConfigValue = Record<string, unknown>

const createEmptyPermissionStatus = (plugin: Pick<Plugin, 'id' | 'name'>): PluginPermissionStatus => ({
  plugin_id: plugin.id,
  plugin_name: plugin.name,
  requested_permissions: [],
  granted_permissions: [],
  missing_permissions: [],
})

export function usePluginConfig(pluginId: string | null) {
  const { detail, loading, error, retry } = usePluginDetail(pluginId)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const retrySaveRef = useRef<(() => Promise<void>) | null>(null)

  const config = useMemo<PluginConfigValue>(() => {
    const rawConfig = (detail as Plugin & { config?: unknown } | null)?.config
    if (rawConfig && typeof rawConfig === 'object' && !Array.isArray(rawConfig)) {
      return rawConfig as PluginConfigValue
    }
    return {}
  }, [detail])

  const runSaveAction = useCallback(async (action: () => Promise<void>, fallbackError: string) => {
    retrySaveRef.current = action
    setSaving(true)
    setSaveError(null)
    try {
      await action()
    } catch (error) {
      setSaveError(getErrorMessage(error, fallbackError))
      throw error
    } finally {
      setSaving(false)
    }
  }, [])

  const saveConfig = useCallback(
    async (nextConfig: PluginConfigValue) => {
      if (!pluginId) return
      await runSaveAction(async () => {
        await pluginsAPI.saveConfig(pluginId, nextConfig)
      }, '插件配置保存失败')
    },
    [pluginId, runSaveAction],
  )

  const retrySave = useCallback(async () => {
    if (retrySaveRef.current) {
      await runSaveAction(retrySaveRef.current, '插件配置重试失败')
    }
  }, [runSaveAction])

  return {
    config,
    loading,
    error,
    retry,
    saving,
    saveError,
    saveConfig,
    retrySave,
  }
}

export function usePluginConfigSchema(pluginId: string | null) {
  const [schemaPayload, setSchemaPayload] = useState<PluginConfigSchemaResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchSchema = useCallback(async () => {
    if (!pluginId) {
      setSchemaPayload(null)
      setError(null)
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const response = await pluginsAPI.getConfigSchema(pluginId)
      setSchemaPayload(response.data)
    } catch (error) {
      setError(getErrorMessage(error, '插件配置 Schema 加载失败'))
    } finally {
      setLoading(false)
    }
  }, [pluginId])

  useEffect(() => {
    fetchSchema()
  }, [fetchSchema])

  return {
    schemaPayload,
    loading,
    error,
    retry: fetchSchema,
    refresh: fetchSchema,
  }
}

export function usePluginConfigActions(pluginId: string | null) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const retryRef = useRef<(() => Promise<unknown>) | null>(null)

  const runAction = useCallback(async <T,>(action: () => Promise<T>, fallbackError: string): Promise<T> => {
    setLoading(true)
    setError(null)
    retryRef.current = action
    try {
      return await action()
    } catch (error) {
      setError(getErrorMessage(error, fallbackError))
      throw error
    } finally {
      setLoading(false)
    }
  }, [])

  const saveConfig = useCallback(
    async (config: PluginConfigValue): Promise<PluginConfigValue> => {
      if (!pluginId) return {}
      const response = await runAction(
        () => pluginsAPI.saveConfig(pluginId, config),
        '插件配置保存失败',
      )
      return response.data?.config || {}
    },
    [pluginId, runAction],
  )

  const resetConfig = useCallback(async (): Promise<PluginConfigValue> => {
    if (!pluginId) return {}
    const response = await runAction(
      () => pluginsAPI.resetConfig(pluginId),
      '插件配置重置失败',
    )
    return response.data?.config || {}
  }, [pluginId, runAction])

  const exportConfig = useCallback(async (): Promise<PluginConfigValue> => {
    if (!pluginId) return {}
    const response = await runAction(
      () => pluginsAPI.exportConfig(pluginId),
      '插件配置导出失败',
    )
    return response.data?.config || {}
  }, [pluginId, runAction])

  const retry = useCallback(async () => {
    if (retryRef.current) {
      await runAction(retryRef.current, '配置操作重试失败')
    }
  }, [runAction])

  return {
    loading,
    error,
    retry,
    saveConfig,
    resetConfig,
    exportConfig,
  }
}

export function usePluginToggle() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const retryRef = useRef<(() => Promise<unknown>) | null>(null)

  const runAction = useCallback(async <T,>(action: () => Promise<T>, fallbackError: string): Promise<T> => {
    setLoading(true)
    setError(null)
    retryRef.current = action
    try {
      return await action()
    } catch (error) {
      setError(getErrorMessage(error, fallbackError))
      throw error
    } finally {
      setLoading(false)
    }
  }, [])

  const toggle = useCallback(
    async (pluginId: string) => runAction(() => pluginsAPI.toggle(pluginId), '插件状态切换失败'),
    [runAction],
  )

  const retry = useCallback(async () => {
    if (retryRef.current) {
      await runAction(retryRef.current, '插件状态切换重试失败')
    }
  }, [runAction])

  return {
    loading,
    error,
    retry,
    toggle,
  }
}

export function usePluginPermissions() {
  const [permissionStatusMap, setPermissionStatusMap] = useState<Record<string, PluginPermissionStatus>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const retryRef = useRef<(() => Promise<unknown>) | null>(null)

  const runAction = useCallback(async <T,>(action: () => Promise<T>, fallbackError: string): Promise<T> => {
    setLoading(true)
    setError(null)
    retryRef.current = action
    try {
      return await action()
    } catch (error) {
      setError(getErrorMessage(error, fallbackError))
      throw error
    } finally {
      setLoading(false)
    }
  }, [])

  const refreshPermissions = useCallback(
    async (plugin: Pick<Plugin, 'id' | 'name'>): Promise<PluginPermissionStatus | null> => {
      try {
        return await runAction(async () => {
          const response = await pluginsAPI.getPermissions(plugin.id)
          const status = response.data
          setPermissionStatusMap((prev) => ({ ...prev, [plugin.id]: status }))
          return status
        }, '插件权限加载失败')
      } catch {
        const emptyStatus = createEmptyPermissionStatus(plugin)
        setPermissionStatusMap((prev) => ({ ...prev, [plugin.id]: emptyStatus }))
        return null
      }
    },
    [runAction],
  )

  const authorizePermissions = useCallback(
    async (pluginId: string, permissions: string[]): Promise<PluginPermissionUpdateResponse> => {
      return runAction(async () => {
        const response = await pluginsAPI.authorizePermissions(pluginId, permissions)
        setPermissionStatusMap((prev) => ({ ...prev, [pluginId]: response.data }))
        return response.data
      }, '权限授权失败')
    },
    [runAction],
  )

  const revokePermissions = useCallback(
    async (pluginId: string, permissions: string[]): Promise<PluginPermissionUpdateResponse> => {
      return runAction(async () => {
        const response = await pluginsAPI.revokePermissions(pluginId, permissions)
        setPermissionStatusMap((prev) => ({ ...prev, [pluginId]: response.data }))
        return response.data
      }, '权限撤销失败')
    },
    [runAction],
  )

  const retry = useCallback(async () => {
    if (retryRef.current) {
      await runAction(retryRef.current, '权限操作重试失败')
    }
  }, [runAction])

  return {
    permissionStatusMap,
    loading,
    error,
    retry,
    refreshPermissions,
    authorizePermissions,
    revokePermissions,
    setPermissionStatusMap,
  }
}
