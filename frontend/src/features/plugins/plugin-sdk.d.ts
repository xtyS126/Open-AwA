declare namespace PluginSDK {

  type ExtensionPointType =
    | 'tool'
    | 'hook'
    | 'command'
    | 'route'
    | 'event_handler'
    | 'scheduler'
    | 'middleware'
    | 'data_provider'

  type PluginState =
    | 'registered'
    | 'loaded'
    | 'enabled'
    | 'disabled'
    | 'unloaded'
    | 'updating'
    | 'error'

  type PermissionScope =
    | 'file:read'
    | 'file:write'
    | 'network:http'

  interface PluginManifest {
    name: string
    version: string
    pluginApiVersion: string
    description?: string
    author?: string
    permissions?: PermissionScope[]
    extensions: PluginExtension[]
  }

  interface PluginExtension {
    point: ExtensionPointType
    name: string
    version: string
    config?: Record<string, unknown>
  }

  interface ExtensionPoint {
    type: ExtensionPointType
    name: string
    version: string
    config: Record<string, unknown>
    pluginName: string
  }

  interface ExtensionRegistration {
    pluginName: string
    point: ExtensionPointType
    name: string
    version: string
    config: Record<string, unknown>
  }

  interface PluginContext {
    pluginName: string
    version: string
    state: PluginState
    config: Record<string, unknown>
    permissions: PermissionScope[]
    extensions: ExtensionRegistration[]
  }

  interface StorageAPI {
    getConfig(pluginName: string): Promise<Record<string, unknown>>
    setConfig(pluginName: string, config: Record<string, unknown>): Promise<void>
    getState(pluginName: string): Promise<PluginState>
  }

  interface EventPayload {
    eventType: string
    data: Record<string, unknown>
    timestamp: string
    sourcePlugin?: string
  }

  type EventHandler = (payload: EventPayload) => void | Promise<void>

  interface EventAPI {
    subscribe(eventType: string, handler: EventHandler): () => void
    unsubscribe(eventType: string, handler: EventHandler): void
    publish(eventType: string, data: Record<string, unknown>): void
  }

  interface PermissionAPI {
    hasPermission(pluginName: string, scope: PermissionScope): boolean
    getPermissions(pluginName: string): PermissionScope[]
    requestPermission(pluginName: string, scope: PermissionScope): Promise<boolean>
  }

  interface PluginInfo {
    name: string
    version: string
    description: string
    state: PluginState
    author?: string
    permissions: PermissionScope[]
    extensions: ExtensionRegistration[]
    executionStats?: PluginExecutionStats
  }

  interface PluginExecutionStats {
    totalExecutions: number
    timeoutSetting: number
    memoryLimit: string
    cpuLimit: number
  }

  interface PluginListResponse {
    plugins: PluginInfo[]
    total: number
  }

  interface PluginLoadRequest {
    path: string
    config?: Record<string, unknown>
  }

  interface PluginInstallRequest {
    packageName: string
    version?: string
  }

  interface PluginExecuteRequest {
    pluginName: string
    method?: string
    params?: Record<string, unknown>
  }

  interface PluginExecuteResponse {
    status: 'success' | 'error' | 'timeout'
    result?: unknown
    message?: string
    executionId: number
  }

  interface PluginUpdateRequest {
    path: string
    rolloutConfig?: RolloutConfig
  }

  interface RolloutConfig {
    percentage?: number
    canaryDuration?: number
    autoPromote?: boolean
  }

  interface PluginRollbackRequest {
    snapshotId?: string
  }

  interface HotUpdateResult {
    pluginName: string
    previousVersion: string
    newVersion: string
    snapshotId: string
    rolledBackTo?: string
  }

  interface SchemaValidationResult {
    valid: boolean
    errors: string[]
  }

  interface ToolDefinition {
    name: string
    description: string
    parameters: ToolParameterSchema
  }

  interface ToolParameterSchema {
    type: 'object'
    properties: Record<string, ToolProperty>
    required?: string[]
  }

  interface ToolProperty {
    type: 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object'
    description?: string
    default?: unknown
    enum?: unknown[]
    minimum?: number
    maximum?: number
  }

  interface SandboxConfig {
    timeout?: number
    memoryLimit?: string
    cpuLimit?: number
  }

  interface PluginStateTransition {
    pluginName: string
    fromState: PluginState
    toState: PluginState
    success: boolean
    rolledBack: boolean
    error?: string
  }

  interface PluginSnapshot {
    snapshotId: string
    pluginName: string
    version: string
    createdAt: string
  }
}

export = PluginSDK
export as namespace PluginSDK
