/**
 * 插件命令选择器组件。
 * 允许用户浏览所有已安装插件及其命令，选中后返回命令信息供调度使用。
 */
import { useState, useEffect, useCallback } from 'react'
import { Search, ChevronRight, Puzzle, Zap, Code } from 'lucide-react'
import { scheduledTasksAPI, PluginCommandInfo } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import styles from './PluginCommandSelector.module.css'

interface Props {
  onSelect: (command: PluginCommandInfo | null) => void
  selectedPluginName?: string
  selectedCommandName?: string
}

export default function PluginCommandSelector({
  onSelect,
  selectedPluginName,
  selectedCommandName,
}: Props) {
  const [commands, setCommands] = useState<PluginCommandInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  const [expandedPlugin, setExpandedPlugin] = useState<string | null>(null)
  const [selectedCommand, setSelectedCommand] = useState<string | null>(
    selectedCommandName || null
  )

  useEffect(() => {
    loadCommands()
  }, [])

  // 当外部传入选中值时同步
  useEffect(() => {
    if (selectedPluginName && selectedCommandName) {
      setExpandedPlugin(selectedPluginName)
      setSelectedCommand(selectedCommandName)
      const found = commands.find(
        (c) =>
          c.plugin_name === selectedPluginName &&
          c.command_name === selectedCommandName
      )
      if (found) onSelect(found)
    }
  }, [selectedPluginName, selectedCommandName, commands])

  const loadCommands = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await scheduledTasksAPI.getPluginCommands()
      setCommands(res.data)
    } catch (err) {
      appLogger.error({
        event: 'plugin_commands_load_failed',
        module: 'scheduled_tasks',
        action: 'load_plugin_commands',
        status: 'failure',
        message: '加载插件命令列表失败',
        extra: { error: err instanceof Error ? err.message : String(err) },
      })
      setError('加载插件命令列表失败')
    } finally {
      setLoading(false)
    }
  }

  // 按插件分组命令
  const grouped = useCallback(() => {
    const map = new Map<string, PluginCommandInfo[]>()
    commands.forEach((cmd) => {
      const list = map.get(cmd.plugin_name) || []
      list.push(cmd)
      map.set(cmd.plugin_name, list)
    })
    return Array.from(map.entries())
  }, [commands])

  const filteredGroups = grouped().filter(([pluginName, cmds]) => {
    if (!searchTerm) return true
    const term = searchTerm.toLowerCase()
    return (
      pluginName.toLowerCase().includes(term) ||
      cmds.some(
        (c) =>
          c.command_name.toLowerCase().includes(term) ||
          c.command_description.toLowerCase().includes(term)
      )
    )
  })

  const handleSelectCommand = (cmd: PluginCommandInfo) => {
    setSelectedCommand(cmd.command_name)
    onSelect(cmd)
  }

  if (loading) {
    return (
      <div className={styles['loading']}>
        <Puzzle size={18} className={styles['spin']} />
        正在加载插件命令...
      </div>
    )
  }

  if (error) {
    return (
      <div className={styles['error']}>
        <span>{error}</span>
        <button className="btn btn-ghost" onClick={loadCommands} type="button">
          重试
        </button>
      </div>
    )
  }

  if (commands.length === 0) {
    return (
      <div className={styles['empty']}>
        <Zap size={24} />
        <p>暂无可用的插件命令</p>
        <span>请先安装并启用插件，然后刷新列表</span>
      </div>
    )
  }

  return (
    <div className={styles['container']}>
      {/* 搜索栏 */}
      <div className={styles['search-bar']}>
        <Search size={16} className={styles['search-icon']} />
        <input
          type="text"
          placeholder="搜索插件或命令..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className={styles['search-input']}
        />
      </div>

      {/* 插件命令列表 */}
      <div className={styles['list']}>
        {filteredGroups.map(([pluginName, cmds]) => {
          const isExpanded = expandedPlugin === pluginName
          const info = cmds[0]

          return (
            <div key={pluginName} className={styles['plugin-group']}>
              <button
                type="button"
                className={`${styles['plugin-header']} ${isExpanded ? styles['expanded'] : ''}`}
                onClick={() =>
                  setExpandedPlugin(isExpanded ? null : pluginName)
                }
              >
                <div className={styles['plugin-info']}>
                  <div className={styles['plugin-icon']}>
                    <Code size={16} />
                  </div>
                  <div>
                    <span className={styles['plugin-name']}>{pluginName}</span>
                    <span className={styles['plugin-version']}>
                      v{info.plugin_version}
                    </span>
                  </div>
                </div>
                <div className={styles['plugin-meta']}>
                  <span className={styles['command-count']}>
                    {cmds.length} 个命令
                  </span>
                  <ChevronRight
                    size={16}
                    className={`${styles['chevron']} ${isExpanded ? styles['chevron-open'] : ''}`}
                  />
                </div>
              </button>

              {info.plugin_description && isExpanded && (
                <p className={styles['plugin-desc']}>{info.plugin_description}</p>
              )}

              {isExpanded && (
                <div className={styles['command-list']}>
                  {cmds.map((cmd) => (
                    <button
                      key={cmd.command_name}
                      type="button"
                      className={`${styles['command-item']} ${
                        selectedCommand === cmd.command_name &&
                        expandedPlugin === pluginName
                          ? styles['selected']
                          : ''
                      }`}
                      onClick={() => handleSelectCommand(cmd)}
                    >
                      <div className={styles['command-info']}>
                        <span className={styles['command-name']}>
                          {cmd.command_name}
                        </span>
                        {cmd.command_description && (
                          <span className={styles['command-desc']}>
                            {cmd.command_description}
                          </span>
                        )}
                      </div>
                      {selectedCommand === cmd.command_name &&
                        expandedPlugin === pluginName && (
                          <span className={styles['check']}>
                            <Zap size={14} />
                          </span>
                        )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
