/**
 * MCP 配置组件，提供 MCP Server 的管理界面。
 * 支持添加、删除、连接/断开 Server，以及查看工具列表。
 */
import { useState, useEffect, useCallback } from 'react'
import { mcpAPI, MCPServer, MCPToolInfo } from '@/shared/api/mcpApi'
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

function MCPSettings() {
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

  return (
    <div className={styles['mcp-settings']}>
      <div className={styles['mcp-header']}>
        <h2>MCP Server 管理</h2>
        <button
          className={`btn btn-primary`}
          onClick={() => setShowAddForm(!showAddForm)}
        >
          {showAddForm ? '取消' : '添加 Server'}
        </button>
      </div>

      {error && <p className={styles['error-text']}>{error}</p>}

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
    </div>
  )
}

export default MCPSettings
