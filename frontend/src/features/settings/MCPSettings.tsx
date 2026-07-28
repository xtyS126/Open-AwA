/**
 * MCP 配置组件，提供 MCP Server 的管理界面。
 * 支持添加、删除、连接/断开 Server，以及查看工具列表和资源内容。
 */
import { useState, useEffect, useCallback } from 'react'
import {
  mcpAPI,
  MCPServer,
  MCPToolInfo,
  MCPResource,
  MCPResourceReadResponse,
} from '@/shared/api/mcpApi'
import { appLogger } from '@/shared/utils/logger'
import styles from './MCPSettings.module.css'

interface AddFormState {
  name: string
  command: string
  args: string
  transport_type: string
  url: string
}

const INITIAL_FORM: AddFormState = {
  name: '',
  command: '',
  args: '',
  transport_type: 'stdio',
  url: '',
}

/* 标签页类型 */
type TabKey = 'servers' | 'tools' | 'resources'

/* 服务器资源缓存：serverId -> 资源列表 */
type ServerResourcesMap = Record<string, MCPResource[]>

/* 资源内容缓存：以 serverId + uri 作为键 */
type ResourceContentMap = Record<string, MCPResourceReadResponse>

/* 资源加载状态：以 serverId + uri 作为键 */
type ResourceLoadingMap = Record<string, boolean>

/* 资源错误信息：以 serverId + uri 作为键 */
type ResourceErrorMap = Record<string, string>

/* 已展开资源内容的键集合 */
type ExpandedResourcesSet = Set<string>

/* 拼接资源内容的唯一键 */
const buildResourceKey = (serverId: string, uri: string): string => `${serverId}::${uri}`

function MCPSettings() {
  /* 当前激活的标签页 */
  const [activeTab, setActiveTab] = useState<TabKey>('servers')
  const [servers, setServers] = useState<MCPServer[]>([])
  const [loading, setLoading] = useState(false)
  const [showAddForm, setShowAddForm] = useState(false)
  const [addForm, setAddForm] = useState<AddFormState>(INITIAL_FORM)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  /* 展开工具列表的 server_id 集合 */
  const [expandedServers, setExpandedServers] = useState<Set<string>>(new Set())
  /* 各 server 的工具缓存 */
  const [serverTools, setServerTools] = useState<Record<string, MCPToolInfo[]>>({})
  const [loadingTools, setLoadingTools] = useState<Record<string, boolean>>({})

  /* 资源标签页相关状态 */
  const [serverResources, setServerResources] = useState<ServerResourcesMap>({})
  const [loadingResources, setLoadingResources] = useState<Record<string, boolean>>({})
  const [resourceContents, setResourceContents] = useState<ResourceContentMap>({})
  const [resourceLoading, setResourceLoading] = useState<ResourceLoadingMap>({})
  const [resourceErrors, setResourceErrors] = useState<ResourceErrorMap>({})
  const [expandedResources, setExpandedResources] = useState<ExpandedResourcesSet>(new Set())

  const loadServers = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await mcpAPI.getServers()
      setServers(res.data)
    } catch (err) {
      setError('加载 MCP Server 列表失败')
      appLogger.error({ event: 'mcp_load_servers_failed', module: 'mcp', message: String(err) })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadServers()
  }, [loadServers])

  /* 切换到资源标签页时，按服务器加载资源列表 */
  const loadServerResources = useCallback(async (serverId: string, serverName: string) => {
    if (serverResources[serverId]) return
    setLoadingResources((prev) => ({ ...prev, [serverId]: true }))
    try {
      const res = await mcpAPI.getServerResources(serverId)
      setServerResources((prev) => ({ ...prev, [serverId]: res.data.resources }))
    } catch (err) {
      appLogger.error({
        event: 'mcp_load_resources_failed',
        module: 'mcp',
        message: String(err),
        extra: { server_id: serverId, server_name: serverName },
      })
      /* 失败时缓存空数组，避免重复请求 */
      setServerResources((prev) => ({ ...prev, [serverId]: [] }))
    } finally {
      setLoadingResources((prev) => ({ ...prev, [serverId]: false }))
    }
  }, [serverResources])

  /* 切换标签页 */
  const handleTabChange = (tab: TabKey) => {
    setActiveTab(tab)
    if (tab === 'resources' && servers.length > 0) {
      /* 进入资源标签页时，自动加载所有已连接服务器的资源 */
      servers.forEach((s) => {
        if (s.status === 'connected') {
          loadServerResources(s.id, s.name)
        }
      })
    }
  }

  /* 添加 Server */
  const handleAdd = async () => {
    if (!addForm.name.trim()) return
    setAdding(true)
    try {
      const argsArray = addForm.args.trim() ? addForm.args.split(/\s+/) : []
      await mcpAPI.addServer({
        name: addForm.name,
        command: addForm.command || undefined,
        args: argsArray.length > 0 ? argsArray : undefined,
        transport_type: addForm.transport_type,
        url: addForm.url || undefined,
      })
      setAddForm(INITIAL_FORM)
      setShowAddForm(false)
      await loadServers()
    } catch (err) {
      setError('添加 MCP Server 失败')
      appLogger.error({ event: 'mcp_add_server_failed', module: 'mcp', message: String(err) })
    } finally {
      setAdding(false)
    }
  }

  /* 删除 Server */
  const handleDelete = async (id: string) => {
    try {
      await mcpAPI.deleteServer(id)
      await loadServers()
    } catch (err) {
      setError('删除 MCP Server 失败')
      appLogger.error({ event: 'mcp_delete_server_failed', module: 'mcp', message: String(err) })
    }
  }

  /* 连接 Server */
  const handleConnect = async (id: string) => {
    try {
      await mcpAPI.connectServer(id)
      await loadServers()
    } catch (err) {
      setError('连接 MCP Server 失败')
      appLogger.error({ event: 'mcp_connect_failed', module: 'mcp', message: String(err) })
    }
  }

  /* 断开 Server */
  const handleDisconnect = async (id: string) => {
    try {
      await mcpAPI.disconnectServer(id)
      await loadServers()
    } catch (err) {
      setError('断开 MCP Server 失败')
      appLogger.error({ event: 'mcp_disconnect_failed', module: 'mcp', message: String(err) })
    }
  }

  /* 展开/收起工具列表 */
  const toggleTools = async (serverId: string) => {
    const next = new Set(expandedServers)
    if (next.has(serverId)) {
      next.delete(serverId)
      setExpandedServers(next)
      return
    }
    next.add(serverId)
    setExpandedServers(next)
    /* 如果还没加载过，请求工具列表 */
    if (!serverTools[serverId]) {
      setLoadingTools((prev) => ({ ...prev, [serverId]: true }))
      try {
        const res = await mcpAPI.getServerTools(serverId)
        setServerTools((prev) => ({ ...prev, [serverId]: res.data.tools }))
      } catch (err) {
        appLogger.error({ event: 'mcp_load_tools_failed', module: 'mcp', message: String(err) })
      } finally {
        setLoadingTools((prev) => ({ ...prev, [serverId]: false }))
      }
    }
  }

  /* 展开/收起资源内容，首次展开时请求资源内容 */
  const toggleResource = async (serverId: string, uri: string) => {
    const key = buildResourceKey(serverId, uri)
    const next = new Set(expandedResources)
    if (next.has(key)) {
      next.delete(key)
      setExpandedResources(next)
      return
    }
    next.add(key)
    setExpandedResources(next)
    /* 已缓存则直接展示 */
    if (resourceContents[key]) return
    setResourceLoading((prev) => ({ ...prev, [key]: true }))
    setResourceErrors((prev) => ({ ...prev, [key]: '' }))
    try {
      const res = await mcpAPI.readServerResource(serverId, uri)
      setResourceContents((prev) => ({ ...prev, [key]: res.data }))
    } catch (err) {
      setResourceErrors((prev) => ({ ...prev, [key]: '读取资源失败' }))
      appLogger.error({
        event: 'mcp_read_resource_failed',
        module: 'mcp',
        message: String(err),
        extra: { server_id: serverId, uri },
      })
    } finally {
      setResourceLoading((prev) => ({ ...prev, [key]: false }))
    }
  }

  /* 生成 blob 资源的下载链接（data URL） */
  const buildBlobDownloadUrl = (mime: string | undefined, blob: string | undefined): string => {
    const mimeType = mime || 'application/octet-stream'
    return `data:${mimeType};base64,${blob ?? ''}`
  }

  /* 渲染资源内容区域 */
  const renderResourceContent = (serverId: string, uri: string) => {
    const key = buildResourceKey(serverId, uri)
    if (resourceLoading[key]) {
      return <div className={styles['resource-loading']}>加载资源内容中...</div>
    }
    if (resourceErrors[key]) {
      return <div className={styles['resource-error']}>{resourceErrors[key]}</div>
    }
    const content = resourceContents[key]
    if (!content) return null
    /* 文本资源直接展示 */
    if (content.text !== undefined && content.text !== null) {
      return (
        <div className={styles['resource-content']}>
          <div className={styles['resource-text']}>{content.text}</div>
        </div>
      )
    }
    /* 二进制资源展示下载链接 */
    if (content.blob !== undefined && content.blob !== null) {
      const fileName = uri.split('/').pop() || 'resource'
      return (
        <div className={styles['resource-content']}>
          <a
            className={styles['resource-blob-link']}
            href={buildBlobDownloadUrl(content.mime_type, content.blob)}
            download={fileName}
          >
            下载二进制资源 ({content.mime_type || '未知类型'})
          </a>
        </div>
      )
    }
    return (
      <div className={styles['resource-content']}>
        <div className={styles['resource-text']}>资源内容为空</div>
      </div>
    )
  }

  /* 渲染资源标签页内容：按服务器分组展示 */
  const renderResourcesTab = () => {
    const connectedServers = servers.filter((s) => s.status === 'connected')
    if (connectedServers.length === 0) {
      return (
        <div className={styles['empty-state']}>
          暂无已连接的 MCP Server，请先在"服务器"标签页连接 Server
        </div>
      )
    }
    return (
      <div className={styles['resources-section']}>
        {connectedServers.map((server) => {
          const resources = serverResources[server.id] ?? []
          const isLoading = loadingResources[server.id]
          return (
            <div key={server.id} className={styles['resource-group']}>
              <div className={styles['resource-group-header']}>
                <span>{server.name}</span>
                <span className={styles['resource-group-count']}>
                  {isLoading ? '加载中...' : `${resources.length} 个资源`}
                </span>
              </div>
              {isLoading ? null : resources.length === 0 ? (
                <div className={styles['loading-text']} style={{ padding: '12px 14px' }}>
                  该 Server 暂无资源
                </div>
              ) : (
                <div className={styles['resource-list']}>
                  {resources.map((res) => {
                    const key = buildResourceKey(server.id, res.uri)
                    const expanded = expandedResources.has(key)
                    return (
                      <div
                        key={res.uri}
                        className={`${styles['resource-item']} ${expanded ? styles['expanded'] : ''}`}
                        onClick={() => toggleResource(server.id, res.uri)}
                      >
                        <div className={styles['resource-item-header']}>
                          <div className={styles['resource-meta']}>
                            <div className={styles['resource-name']}>{res.name}</div>
                            <div className={styles['resource-uri']}>{res.uri}</div>
                            {res.description && (
                              <div className={styles['resource-desc']}>{res.description}</div>
                            )}
                          </div>
                          {res.mimeType && (
                            <span className={styles['resource-mime']}>{res.mimeType}</span>
                          )}
                        </div>
                        {expanded && renderResourceContent(server.id, res.uri)}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div className={styles['mcp-settings']}>
      <div className={styles['mcp-header']}>
        <h2>MCP Server 管理</h2>
        {activeTab === 'servers' && (
          <button
            className={`btn btn-primary`}
            onClick={() => setShowAddForm(!showAddForm)}
          >
            {showAddForm ? '取消' : '添加 Server'}
          </button>
        )}
      </div>

      {error && <p className={styles['error-text']}>{error}</p>}

      {/* 标签页切换 */}
      <div className={styles['tabs']}>
        <button
          className={`${styles['tab']} ${activeTab === 'servers' ? styles['active'] : ''}`}
          onClick={() => handleTabChange('servers')}
        >
          服务器
        </button>
        <button
          className={`${styles['tab']} ${activeTab === 'tools' ? styles['active'] : ''}`}
          onClick={() => handleTabChange('tools')}
        >
          工具
        </button>
        <button
          className={`${styles['tab']} ${activeTab === 'resources' ? styles['active'] : ''}`}
          onClick={() => handleTabChange('resources')}
        >
          资源
        </button>
      </div>

      {/* 服务器标签页：添加表单 + 服务器列表 */}
      {activeTab === 'servers' && (
        <>
          {/* 添加表单 */}
          {showAddForm && (
            <div className={styles['add-form']}>
              <h3>添加 MCP Server</h3>
              <div className={styles['form-row']}>
                <div className={styles['form-group']}>
                  <label>名称</label>
                  <input
                    type="text"
                    value={addForm.name}
                    onChange={(e) => setAddForm((p) => ({ ...p, name: e.target.value }))}
                    placeholder="例如 filesystem-server"
                  />
                </div>
                <div className={styles['form-group']}>
                  <label>传输类型</label>
                  <select
                    value={addForm.transport_type}
                    onChange={(e) => setAddForm((p) => ({ ...p, transport_type: e.target.value }))}
                  >
                    <option value="stdio">Stdio</option>
                    <option value="sse">SSE</option>
                  </select>
                </div>
              </div>

              {addForm.transport_type === 'stdio' && (
                <div className={styles['form-row']}>
                  <div className={styles['form-group']}>
                    <label>启动命令</label>
                    <input
                      type="text"
                      value={addForm.command}
                      onChange={(e) => setAddForm((p) => ({ ...p, command: e.target.value }))}
                      placeholder="例如 npx 或 python"
                    />
                  </div>
                  <div className={styles['form-group']}>
                    <label>参数（空格分隔）</label>
                    <input
                      type="text"
                      value={addForm.args}
                      onChange={(e) => setAddForm((p) => ({ ...p, args: e.target.value }))}
                      placeholder="例如 -y @modelcontextprotocol/server-filesystem /tmp"
                    />
                  </div>
                </div>
              )}

              {addForm.transport_type === 'sse' && (
                <div className={styles['form-row']}>
                  <div className={styles['form-group']}>
                    <label>服务器地址</label>
                    <input
                      type="text"
                      value={addForm.url}
                      onChange={(e) => setAddForm((p) => ({ ...p, url: e.target.value }))}
                      placeholder="例如 http://localhost:3001/sse"
                    />
                  </div>
                </div>
              )}

              <div className={styles['form-actions']}>
                <button
                  className={`${styles['btn-sm']} ${styles['primary']}`}
                  onClick={handleAdd}
                  disabled={adding || !addForm.name.trim()}
                >
                  {adding ? '添加中...' : '确认添加'}
                </button>
                <button
                  className={styles['btn-sm']}
                  onClick={() => { setShowAddForm(false); setAddForm(INITIAL_FORM) }}
                >
                  取消
                </button>
              </div>
            </div>
          )}

          {/* 服务器列表 */}
          {loading ? (
            <p className={styles['loading-text']}>加载中...</p>
          ) : servers.length === 0 ? (
            <div className={styles['empty-state']}>
              暂无 MCP Server 配置，点击上方按钮添加
            </div>
          ) : (
            <div className={styles['server-list']}>
              {servers.map((server) => (
                <div key={server.id} className={styles['server-card']}>
                  <div className={styles['server-info']}>
                    <div className={styles['server-meta']}>
                      <span className={styles['server-name']}>{server.name}</span>
                      <div className={styles['server-detail']}>
                        <span>传输: {server.transport_type}</span>
                        <span
                          className={`${styles['status-badge']} ${styles[server.status]}`}
                        >
                          {server.status === 'connected' ? '已连接' : '未连接'}
                        </span>
                        <span>工具: {server.tools_count}</span>
                      </div>
                    </div>
                    <div className={styles['server-actions']}>
                      {server.status === 'connected' ? (
                        <>
                          <button
                            className={styles['btn-sm']}
                            onClick={() => toggleTools(server.id)}
                          >
                            {expandedServers.has(server.id) ? '收起工具' : '查看工具'}
                          </button>
                          <button
                            className={styles['btn-sm']}
                            onClick={() => handleDisconnect(server.id)}
                          >
                            断开
                          </button>
                        </>
                      ) : (
                        <button
                          className={`${styles['btn-sm']} ${styles['primary']}`}
                          onClick={() => handleConnect(server.id)}
                        >
                          连接
                        </button>
                      )}
                      <button
                        className={`${styles['btn-sm']} ${styles['danger']}`}
                        onClick={() => handleDelete(server.id)}
                      >
                        删除
                      </button>
                    </div>
                  </div>

                  {/* 展开的工具列表 */}
                  {expandedServers.has(server.id) && (
                    <div className={styles['tools-section']}>
                      <h4>工具列表</h4>
                      {loadingTools[server.id] ? (
                        <p className={styles['loading-text']}>加载工具中...</p>
                      ) : serverTools[server.id]?.length ? (
                        <div className={styles['tools-list']}>
                          {serverTools[server.id].map((tool) => (
                            <div key={tool.name} className={styles['tool-item']}>
                              <div className={styles['tool-name']}>{tool.name}</div>
                              {tool.description && (
                                <div className={styles['tool-desc']}>{tool.description}</div>
                              )}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className={styles['loading-text']}>该 Server 暂无工具</p>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* 工具标签页：聚合展示所有已连接服务器的工具 */}
      {activeTab === 'tools' && (
        <>
          {loading ? (
            <p className={styles['loading-text']}>加载中...</p>
          ) : servers.filter((s) => s.status === 'connected').length === 0 ? (
            <div className={styles['empty-state']}>
              暂无已连接的 MCP Server，请先在"服务器"标签页连接 Server
            </div>
          ) : (
            <div className={styles['server-list']}>
              {servers
                .filter((s) => s.status === 'connected')
                .map((server) => (
                  <div key={server.id} className={styles['server-card']}>
                    <div className={styles['server-info']}>
                      <div className={styles['server-meta']}>
                        <span className={styles['server-name']}>{server.name}</span>
                        <div className={styles['server-detail']}>
                          <span>工具数: {server.tools_count}</span>
                        </div>
                      </div>
                      <div className={styles['server-actions']}>
                        <button
                          className={styles['btn-sm']}
                          onClick={() => toggleTools(server.id)}
                        >
                          {expandedServers.has(server.id) ? '收起工具' : '查看工具'}
                        </button>
                      </div>
                    </div>

                    {expandedServers.has(server.id) && (
                      <div className={styles['tools-section']}>
                        <h4>工具列表</h4>
                        {loadingTools[server.id] ? (
                          <p className={styles['loading-text']}>加载工具中...</p>
                        ) : serverTools[server.id]?.length ? (
                          <div className={styles['tools-list']}>
                            {serverTools[server.id].map((tool) => (
                              <div key={tool.name} className={styles['tool-item']}>
                                <div className={styles['tool-name']}>{tool.name}</div>
                                {tool.description && (
                                  <div className={styles['tool-desc']}>{tool.description}</div>
                                )}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className={styles['loading-text']}>该 Server 暂无工具</p>
                        )}
                      </div>
                    )}
                  </div>
                ))}
            </div>
          )}
        </>
      )}

      {/* 资源标签页：按服务器分组展示资源，支持读取资源内容 */}
      {activeTab === 'resources' && renderResourcesTab()}
    </div>
  )
}

export default MCPSettings
