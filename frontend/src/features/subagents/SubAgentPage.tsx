/**
 * SubAgent 管理页面：图定义管理 + 执行历史 + 已注册 Agent。
 * 提供图定义的增删改查、运行、执行历史查看、已注册 Agent 浏览。
 * 包含三个标签页：图定义管理 / 执行历史 / 已注册 Agent。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Plus,
  Trash2,
  Play,
  Save,
  X,
  RefreshCw,
  Network,
  Clock,
  CheckCircle,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Send,
  XCircle,
  Loader,
} from 'lucide-react'
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  type NodeProps,
  type Node,
  type Edge,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { Button, Input, Modal, Textarea, EmptyState, Badge, Card } from '@/shared/components/ui'
import { getApiErrorDetail } from '@/shared/api/client'
import {
  subagentsApi,
  type SubagentDefinitionResponse,
  type SubagentDefinitionCreate,
  type SubagentDefinitionUpdate,
  type GraphDefinitionSchema,
  type GraphNodeSchema,
  type GraphEdgeSchema,
  type RunDefinitionRequest,
  type ExecutionHistoryResponse,
  type GraphExecutionResult,
  type RegisteredAgent,
  type DelegateRequest,
  type DelegateResponse,
  type SubagentTaskInput,
  type IsolationLevel,
  type MergeStrategy,
  type ActiveTasksResponse,
  type OrchestratorCapabilities,
  type SubagentLifecycleState,
} from '@/shared/api/subagentsApi'
import { appLogger } from '@/shared/utils/logger'
import {
  getAgentColor,
  graphDefinitionToFlow,
  type SubagentNodeData,
} from './subagentGraph'
import styles from './SubAgentPage.module.css'

/* ---- 工具函数 ---- */

/** 从未知错误中提取用户友好的错误消息，回退到指定消息 */
function getErrorMessage(error: unknown, fallback: string): string {
  return getApiErrorDetail(error) || fallback
}

/** 格式化 ISO 时间戳为本地可读字符串 */
function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

/** 格式化秒级耗时为可读字符串 */
function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(2)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m${s}s`
}

/** 格式化 Unix 时间戳（秒）为本地可读字符串 */
function formatUnixTimestamp(ts: number): string {
  try {
    return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return String(ts)
  }
}

/** 安全地将 JSON 字符串解析为对象，失败返回 null */
function safeJsonParse<T>(text: string): T | null {
  try {
    return JSON.parse(text) as T
  } catch {
    return null
  }
}

/** 创建空图定义 */
function createEmptyGraph(): GraphDefinitionSchema {
  return { nodes: [], edges: [], entry_point: '', finish_points: [] }
}

/** 将对象格式化为缩进 JSON 字符串 */
function prettyJson(obj: unknown): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

/* ---- 标签页类型 ---- */
type TabKey = 'definitions' | 'history' | 'agents' | 'delegate'

/* ---- 图定义编辑器视图模式 ---- */
type GraphViewMode = 'table' | 'visual'

/* ---- 委派任务表单行 ---- */
interface DelegateTaskFormRow {
  /** 任务指令 */
  instruction: string
  /** 允许的工具（逗号分隔） */
  allowedTools: string
  /** 隔离级别 */
  isolationLevel: IsolationLevel
  /** 最大轮次（可选，空字符串表示不设置） */
  maxTurns: string
  /** 最大 token 数（可选） */
  maxTokens: string
  /** 最大执行时间秒数（可选） */
  maxTime: string
}

/* ---- 隔离级别选项 ---- */
const ISOLATION_LEVEL_OPTIONS: Array<{ value: IsolationLevel; label: string }> = [
  { value: 1, label: 'CONTEXT' },
  { value: 2, label: 'PROCESS' },
  { value: 3, label: 'SANDBOX' },
]

/* ---- 合并策略选项 ---- */
const MERGE_STRATEGY_OPTIONS: Array<{ value: MergeStrategy; label: string }> = [
  { value: 'concatenate', label: 'CONCATENATE' },
  { value: 'dag', label: 'DAG' },
  { value: 'llm_summary', label: 'LLM_SUMMARY' },
  { value: 'voting', label: 'VOTING' },
]

/* ---- 生命周期状态对应的 Badge 变体 ---- */
function getLifecycleBadgeVariant(
  state: SubagentLifecycleState,
): 'primary' | 'success' | 'warning' | 'error' {
  switch (state) {
    case 'completed':
      return 'success'
    case 'running':
    case 'created':
    case 'waiting':
      return 'primary'
    case 'timeout':
    case 'terminated':
      return 'warning'
    case 'error':
    case 'cancelled':
      return 'error'
    default:
      return 'primary'
  }
}

/* ---- 执行结果展示组件 ---- */

interface RunResultDisplayProps {
  result: GraphExecutionResult
}

/** 展示图执行结果：状态、执行日志、消息、错误、结果 */
function RunResultDisplay({ result }: RunResultDisplayProps) {
  return (
    <div className={styles.runResult}>
      <div className={styles.runResultHeader}>
        <h4>执行结果</h4>
        <Badge
          variant={result.success ? 'success' : 'error'}
          text={result.success ? '成功' : '失败'}
        />
      </div>

      {/* 执行日志 */}
      {result.execution_log.length > 0 && (
        <div className={styles.runResultSection}>
          <h5>执行日志</h5>
          <div className={styles.executionLogList}>
            {result.execution_log.map((log, i) => (
              <div key={i} className={styles.executionLogItem}>
                <div className={styles.executionLogHeader}>
                  <span className={styles.executionLogNode}>{log.node}</span>
                  <Badge
                    variant={
                      log.status === 'completed' ? 'success'
                        : log.status === 'running' ? 'primary'
                        : 'error'
                    }
                    text={log.status}
                  />
                  {log.duration_ms !== null && (
                    <span className={styles.executionLogDuration}>{log.duration_ms}ms</span>
                  )}
                </div>
                {log.error && (
                  <div className={styles.executionLogError}>{log.error}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 消息列表 */}
      {result.messages.length > 0 && (
        <div className={styles.runResultSection}>
          <h5>消息</h5>
          <div className={styles.messageList}>
            {result.messages.map((msg, i) => (
              <div key={i} className={styles.messageItem}>
                <Badge variant="primary" text={msg.role} />
                <span className={styles.messageContent}>{msg.content}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 错误信息 */}
      {Object.keys(result.errors).length > 0 && (
        <div className={styles.runResultSection}>
          <h5>错误</h5>
          <pre className={styles.jsonBlock}>{prettyJson(result.errors)}</pre>
        </div>
      )}

      {/* 结果数据 */}
      {Object.keys(result.results).length > 0 && (
        <div className={styles.runResultSection}>
          <h5>结果</h5>
          <pre className={styles.jsonBlock}>{prettyJson(result.results)}</pre>
        </div>
      )}
    </div>
  )
}

/* ---- 图视图自定义节点组件 ---- */

/** 自定义节点组件：按 agent 字段着色，显示节点名称/Agent/描述与入口终点标记 */
function SubagentNodeComponent({ data }: NodeProps<SubagentNodeData>) {
  const color = getAgentColor(data.agent)
  return (
    <div
      className={styles.graphNode}
      style={{ borderLeftColor: color }}
      data-entry={data.isEntryPoint ? 'true' : 'false'}
      data-finish={data.isFinishPoint ? 'true' : 'false'}
    >
      <Handle type="target" position={Position.Top} className={styles.graphNodeHandle} />
      <div className={styles.graphNodeHeader} style={{ backgroundColor: color }}>
        {data.agent || '未指定 Agent'}
      </div>
      <div className={styles.graphNodeBody}>
        <span className={styles.graphNodeTitle}>{data.title}</span>
        {data.node.description && (
          <span className={styles.graphNodeDesc}>{data.node.description}</span>
        )}
        {(data.isEntryPoint || data.isFinishPoint) && (
          <div className={styles.graphNodeBadges}>
            {data.isEntryPoint && <Badge variant="primary" text="入口" />}
            {data.isFinishPoint && <Badge variant="success" text="终点" />}
          </div>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className={styles.graphNodeHandle} />
    </div>
  )
}

/** reactflow 节点类型映射（模块级定义，避免每次渲染重建） */
const nodeTypes = { subagentNode: SubagentNodeComponent }

/* ---- 主页面组件 ---- */

export default function SubAgentPage() {
  /* ---- 标签页状态 ---- */
  const [activeTab, setActiveTab] = useState<TabKey>('definitions')

  /* ---- 数据状态 ---- */
  const [definitions, setDefinitions] = useState<SubagentDefinitionResponse[]>([])
  const [selectedDefId, setSelectedDefId] = useState<number | null>(null)
  const [history, setHistory] = useState<ExecutionHistoryResponse[]>([])
  const [agents, setAgents] = useState<RegisteredAgent[]>([])

  /* ---- 加载状态 ---- */
  const [isLoadingDefs, setIsLoadingDefs] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [isLoadingAgents, setIsLoadingAgents] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isCreating, setIsCreating] = useState(false)

  /* ---- 错误状态 ---- */
  const [error, setError] = useState<string | null>(null)

  /* ---- 弹窗状态 ---- */
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showRunModal, setShowRunModal] = useState(false)

  /* ---- 运行结果 ---- */
  const [runResult, setRunResult] = useState<GraphExecutionResult | null>(null)

  /* ---- 历史展开状态 ---- */
  const [expandedHistoryId, setExpandedHistoryId] = useState<number | null>(null)
  const [historyFilter, setHistoryFilter] = useState<string>('')

  /* ---- 编辑器状态 ---- */
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editTags, setEditTags] = useState('')
  const [editGraph, setEditGraph] = useState<GraphDefinitionSchema>(createEmptyGraph())

  /* ---- 创建弹窗状态 ---- */
  const [createName, setCreateName] = useState('')
  const [createDescription, setCreateDescription] = useState('')
  const [createTags, setCreateTags] = useState('')

  /* ---- 运行弹窗状态 ---- */
  const [runContext, setRunContext] = useState('{}')
  const [runMessages, setRunMessages] = useState('[]')

  /* ---- 图视图状态 ---- */
  const [graphViewMode, setGraphViewMode] = useState<GraphViewMode>('table')
  /** 可视化模式下正在编辑的节点索引（null 表示未编辑） */
  const [editingNodeIndex, setEditingNodeIndex] = useState<number | null>(null)
  /** 节点编辑弹窗草稿 */
  const [nodeEditDraft, setNodeEditDraft] = useState<GraphNodeSchema | null>(null)

  /* ---- 委派任务状态 ---- */
  const [delegateTasks, setDelegateTasks] = useState<DelegateTaskFormRow[]>([
    { instruction: '', allowedTools: '', isolationLevel: 1, maxTurns: '', maxTokens: '', maxTime: '' },
  ])
  const [mergeStrategy, setMergeStrategy] = useState<MergeStrategy>('concatenate')
  const [delegateResult, setDelegateResult] = useState<DelegateResponse | null>(null)
  const [activeTasks, setActiveTasks] = useState<ActiveTasksResponse | null>(null)
  const [isDelegating, setIsDelegating] = useState(false)
  const [cancellingTaskId, setCancellingTaskId] = useState<string | null>(null)
  const [capabilities, setCapabilities] = useState<OrchestratorCapabilities | null>(null)

  /* ---- 卸载安全引用 ---- */
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  /* ---- 数据加载函数 ---- */

  /** 加载图定义列表 */
  const loadDefinitions = useCallback(async () => {
    setIsLoadingDefs(true)
    setError(null)
    try {
      const { definitions: defs } = await subagentsApi.listDefinitions()
      if (!mountedRef.current) return
      setDefinitions(defs)
    } catch (err) {
      if (!mountedRef.current) return
      appLogger.error({
        event: 'subagents_definitions_load_failed',
        module: 'subagents',
        message: '加载图定义列表失败',
        extra: { error: String(err) },
      })
      setError(getErrorMessage(err, '加载图定义列表失败'))
    } finally {
      if (mountedRef.current) setIsLoadingDefs(false)
    }
  }, [])

  /** 加载执行历史 */
  const loadHistory = useCallback(async () => {
    setIsLoadingHistory(true)
    setError(null)
    try {
      const { history: hist } = await subagentsApi.listExecutionHistory()
      if (!mountedRef.current) return
      setHistory(hist)
    } catch (err) {
      if (!mountedRef.current) return
      appLogger.error({
        event: 'subagents_history_load_failed',
        module: 'subagents',
        message: '加载执行历史失败',
        extra: { error: String(err) },
      })
      setError(getErrorMessage(err, '加载执行历史失败'))
    } finally {
      if (mountedRef.current) setIsLoadingHistory(false)
    }
  }, [])

  /** 加载已注册 Agent */
  const loadAgents = useCallback(async () => {
    setIsLoadingAgents(true)
    setError(null)
    try {
      const { agents: ags } = await subagentsApi.listAgents()
      if (!mountedRef.current) return
      setAgents(ags)
    } catch (err) {
      if (!mountedRef.current) return
      appLogger.error({
        event: 'subagents_agents_load_failed',
        module: 'subagents',
        message: '加载已注册 Agent 失败',
        extra: { error: String(err) },
      })
      setError(getErrorMessage(err, '加载已注册 Agent 失败'))
    } finally {
      if (mountedRef.current) setIsLoadingAgents(false)
    }
  }, [])

  /** 加载当前活跃的子代理任务列表 */
  const loadActiveTasks = useCallback(async () => {
    try {
      const resp = await subagentsApi.getActiveTasks()
      if (!mountedRef.current) return
      setActiveTasks(resp)
    } catch (err) {
      if (!mountedRef.current) return
      appLogger.error({
        event: 'subagents_active_tasks_load_failed',
        module: 'subagents',
        message: '加载活跃任务失败',
        extra: { error: String(err) },
      })
    }
  }, [])

  /** 加载编排器能力描述（隔离级别/合并策略/默认资源限制） */
  const loadCapabilities = useCallback(async () => {
    try {
      const caps = await subagentsApi.getCapabilities()
      if (!mountedRef.current) return
      setCapabilities(caps)
    } catch (err) {
      if (!mountedRef.current) return
      appLogger.error({
        event: 'subagents_capabilities_load_failed',
        module: 'subagents',
        message: '加载编排器能力失败',
        extra: { error: String(err) },
      })
    }
  }, [])

  /* ---- 初始加载 ---- */
  useEffect(() => {
    loadDefinitions()
    loadHistory()
    loadAgents()
  }, [loadDefinitions, loadHistory, loadAgents])

  /* ---- 委派任务轮询：delegate 标签页激活时每 3 秒拉取活跃任务 ---- */
  useEffect(() => {
    if (activeTab !== 'delegate') return
    /* 进入标签页时立即拉取一次 + 加载能力 */
    loadActiveTasks()
    loadCapabilities()
    const timer = setInterval(() => {
      loadActiveTasks()
    }, 3000)
    return () => clearInterval(timer)
  }, [activeTab, loadActiveTasks, loadCapabilities])

  /* ---- 派生状态 ---- */

  /** 当前选中的图定义对象 */
  const selectedDef = useMemo(
    () => definitions.find(d => d.id === selectedDefId) ?? null,
    [definitions, selectedDefId],
  )

  /** 是否只读（内置图定义不允许编辑/删除） */
  const isReadOnly = selectedDef?.is_builtin ?? false

  /** 节点名称列表（用于下拉选择） */
  const nodeNames = useMemo(() => editGraph.nodes.map(n => n.name), [editGraph.nodes])

  /** 历史记录中的图名称选项（去重） */
  const graphNameOptions = useMemo(() => {
    const list = Array.isArray(history) ? history : []
    const set = new Set(list.map(h => h.graph_name))
    return Array.from(set)
  }, [history])

  /** 过滤后的历史记录 */
  const filteredHistory = useMemo(() => {
    if (!historyFilter) return history
    return history.filter(h => h.graph_name === historyFilter)
  }, [history, historyFilter])

  /** 图视图：从 editGraph 计算 reactflow 节点与边（含 dagre 布局） */
  const computedFlow = useMemo(() => graphDefinitionToFlow(editGraph), [editGraph])

  /* ---- 事件处理 ---- */

  /** 切换标签页 */
  const handleTabChange = useCallback((tab: TabKey) => {
    setActiveTab(tab)
    setError(null)
  }, [])

  /** 刷新当前标签页数据 */
  const handleRefresh = useCallback(() => {
    if (activeTab === 'definitions') loadDefinitions()
    else if (activeTab === 'history') loadHistory()
    else if (activeTab === 'agents') loadAgents()
    else if (activeTab === 'delegate') loadActiveTasks()
  }, [activeTab, loadDefinitions, loadHistory, loadAgents, loadActiveTasks])

  /** 选中图定义进行编辑 */
  const handleSelectDefinition = useCallback((def: SubagentDefinitionResponse) => {
    setSelectedDefId(def.id)
    setEditName(def.name)
    setEditDescription(def.description)
    setEditTags(def.tags || '')
    setEditGraph(def.graph_definition)
    setRunResult(null)
    setError(null)
  }, [])

  /** 保存图定义 */
  const handleSave = useCallback(async () => {
    if (!selectedDefId) return
    if (!editName.trim()) {
      setError('图定义名称不能为空')
      return
    }
    setIsSaving(true)
    setError(null)
    try {
      const payload: SubagentDefinitionUpdate = {
        name: editName,
        description: editDescription,
        graph_definition: editGraph,
        tags: editTags || undefined,
      }
      const updated = await subagentsApi.updateDefinition(selectedDefId, payload)
      if (!mountedRef.current) return
      appLogger.info({
        event: 'definition_updated',
        module: 'subagents',
        message: '图定义更新成功',
        extra: { id: updated.id },
      })
      setDefinitions(prev => prev.map(d => (d.id === updated.id ? updated : d)))
    } catch (err) {
      if (!mountedRef.current) return
      appLogger.error({
        event: 'definition_save_failed',
        module: 'subagents',
        message: '保存图定义失败',
        extra: { error: String(err) },
      })
      setError(getErrorMessage(err, '保存图定义失败'))
    } finally {
      if (mountedRef.current) setIsSaving(false)
    }
  }, [selectedDefId, editName, editDescription, editGraph, editTags])

  /** 删除图定义 */
  const handleDelete = useCallback(async () => {
    if (!selectedDefId || !selectedDef) return
    if (selectedDef.is_builtin) {
      setError('内置图定义不可删除')
      return
    }
    if (!window.confirm(`确认删除图定义 "${selectedDef.name}"？`)) return
    setIsDeleting(true)
    setError(null)
    try {
      await subagentsApi.deleteDefinition(selectedDefId)
      if (!mountedRef.current) return
      appLogger.info({
        event: 'definition_deleted',
        module: 'subagents',
        message: '图定义删除成功',
        extra: { id: selectedDefId },
      })
      setDefinitions(prev => prev.filter(d => d.id !== selectedDefId))
      setSelectedDefId(null)
      setEditName('')
      setEditDescription('')
      setEditTags('')
      setEditGraph(createEmptyGraph())
    } catch (err) {
      if (!mountedRef.current) return
      appLogger.error({
        event: 'definition_delete_failed',
        module: 'subagents',
        message: '删除图定义失败',
        extra: { error: String(err) },
      })
      setError(getErrorMessage(err, '删除图定义失败'))
    } finally {
      if (mountedRef.current) setIsDeleting(false)
    }
  }, [selectedDefId, selectedDef])

  /** 创建图定义 */
  const handleCreate = useCallback(async () => {
    if (!createName.trim()) {
      setError('图定义名称不能为空')
      return
    }
    setIsCreating(true)
    setError(null)
    try {
      const payload: SubagentDefinitionCreate = {
        name: createName,
        description: createDescription,
        graph_definition: createEmptyGraph(),
        tags: createTags || undefined,
      }
      const created = await subagentsApi.createDefinition(payload)
      if (!mountedRef.current) return
      appLogger.info({
        event: 'definition_created',
        module: 'subagents',
        message: '图定义创建成功',
        extra: { id: created.id },
      })
      setDefinitions(prev => [...prev, created])
      setShowCreateModal(false)
      setCreateName('')
      setCreateDescription('')
      setCreateTags('')
      handleSelectDefinition(created)
    } catch (err) {
      if (!mountedRef.current) return
      appLogger.error({
        event: 'definition_create_failed',
        module: 'subagents',
        message: '创建图定义失败',
        extra: { error: String(err) },
      })
      setError(getErrorMessage(err, '创建图定义失败'))
    } finally {
      if (mountedRef.current) setIsCreating(false)
    }
  }, [createName, createDescription, createTags, handleSelectDefinition])

  /** 打开运行弹窗 */
  const handleOpenRunModal = useCallback(() => {
    setRunResult(null)
    setRunContext('{}')
    setRunMessages('[]')
    setShowRunModal(true)
  }, [])

  /** 执行图定义 */
  const handleRun = useCallback(async () => {
    if (!selectedDefId) return

    /* 解析上下文 JSON */
    let context: Record<string, unknown> | undefined
    if (runContext.trim() && runContext.trim() !== '{}') {
      const parsed = safeJsonParse<Record<string, unknown>>(runContext)
      if (parsed === null) {
        setError('上下文 JSON 格式错误')
        return
      }
      context = parsed
    }

    /* 解析消息 JSON */
    let messages: Array<{ role: string; content: string }> | undefined
    if (runMessages.trim() && runMessages.trim() !== '[]') {
      const parsed = safeJsonParse<Array<{ role: string; content: string }>>(runMessages)
      if (parsed === null || !Array.isArray(parsed)) {
        setError('消息 JSON 格式错误')
        return
      }
      messages = parsed
    }

    setIsRunning(true)
    setError(null)
    setRunResult(null)
    try {
      const payload: RunDefinitionRequest = {}
      if (context) payload.context = context
      if (messages) payload.messages = messages
      const result = await subagentsApi.runDefinition(selectedDefId, payload)
      if (!mountedRef.current) return
      setRunResult(result)
      appLogger.info({
        event: 'definition_run_completed',
        module: 'subagents',
        message: '图定义执行完成',
        extra: { id: selectedDefId, success: result.success },
      })
    } catch (err) {
      if (!mountedRef.current) return
      appLogger.error({
        event: 'definition_run_failed',
        module: 'subagents',
        message: '执行图定义失败',
        extra: { error: String(err) },
      })
      setError(getErrorMessage(err, '执行图定义失败'))
    } finally {
      if (mountedRef.current) setIsRunning(false)
    }
  }, [selectedDefId, runContext, runMessages])

  /* ---- 图定义编辑操作 ---- */

  /** 添加节点 */
  const handleAddNode = useCallback(() => {
    setEditGraph(prev => ({
      ...prev,
      nodes: [
        ...prev.nodes,
        { name: `node_${prev.nodes.length + 1}`, agent: '', description: '' },
      ],
    }))
  }, [])

  /** 修改节点字段 */
  const handleNodeChange = useCallback(
    (index: number, field: keyof GraphNodeSchema, value: string) => {
      setEditGraph(prev => ({
        ...prev,
        nodes: prev.nodes.map((n, i) => (i === index ? { ...n, [field]: value } : n)),
      }))
    },
    [],
  )

  /** 删除节点（同时清理相关边和入口/终点） */
  const handleDeleteNode = useCallback((index: number) => {
    setEditGraph(prev => {
      const nodeName = prev.nodes[index]?.name
      return {
        ...prev,
        nodes: prev.nodes.filter((_, i) => i !== index),
        edges: prev.edges.filter(e => e.source !== nodeName && e.target !== nodeName),
        entry_point: prev.entry_point === nodeName ? '' : prev.entry_point,
        finish_points: prev.finish_points.filter(n => n !== nodeName),
      }
    })
  }, [])

  /** 添加边 */
  const handleAddEdge = useCallback(() => {
    setEditGraph(prev => ({
      ...prev,
      edges: [...prev.edges, { source: '', target: '', condition: '' }],
    }))
  }, [])

  /** 修改边字段 */
  const handleEdgeChange = useCallback(
    (index: number, field: keyof GraphEdgeSchema, value: string) => {
      setEditGraph(prev => ({
        ...prev,
        edges: prev.edges.map((e, i) => (i === index ? { ...e, [field]: value } : e)),
      }))
    },
    [],
  )

  /** 删除边 */
  const handleDeleteEdge = useCallback((index: number) => {
    setEditGraph(prev => ({
      ...prev,
      edges: prev.edges.filter((_, i) => i !== index),
    }))
  }, [])

  /** 设置入口节点 */
  const handleEntryPointChange = useCallback((value: string) => {
    setEditGraph(prev => ({ ...prev, entry_point: value }))
  }, [])

  /** 切换终点节点 */
  const handleToggleFinishPoint = useCallback((nodeName: string) => {
    setEditGraph(prev => {
      const exists = prev.finish_points.includes(nodeName)
      return {
        ...prev,
        finish_points: exists
          ? prev.finish_points.filter(n => n !== nodeName)
          : [...prev.finish_points, nodeName],
      }
    })
  }, [])

  /** 切换历史记录展开 */
  const handleToggleHistory = useCallback((id: number) => {
    setExpandedHistoryId(prev => (prev === id ? null : id))
  }, [])

  /* ---- 图视图节点编辑 ---- */

  /** 可视化视图节点双击：打开编辑弹窗 */
  const handleNodeDoubleClick = useCallback(
    (_event: unknown, node: Node<SubagentNodeData>) => {
      if (isReadOnly) return
      const idx = node.data.index
      const target = editGraph.nodes[idx]
      if (!target) return
      setEditingNodeIndex(idx)
      setNodeEditDraft({ ...target })
    },
    [editGraph.nodes, isReadOnly],
  )

  /** 节点编辑弹窗字段变更 */
  const handleNodeDraftChange = useCallback(
    (field: keyof GraphNodeSchema, value: string) => {
      setNodeEditDraft(prev => (prev ? { ...prev, [field]: value } : prev))
    },
    [],
  )

  /** 保存节点编辑（同步回 editGraph，可视化与表格双向同步） */
  const handleNodeEditSave = useCallback(() => {
    if (editingNodeIndex === null || !nodeEditDraft) return
    setEditGraph(prev => ({
      ...prev,
      nodes: prev.nodes.map((n, i) => (i === editingNodeIndex ? { ...nodeEditDraft } : n)),
    }))
    setEditingNodeIndex(null)
    setNodeEditDraft(null)
  }, [editingNodeIndex, nodeEditDraft])

  /** 取消节点编辑 */
  const handleNodeEditCancel = useCallback(() => {
    setEditingNodeIndex(null)
    setNodeEditDraft(null)
  }, [])

  /* ---- 委派任务处理 ---- */

  /** 更新委派任务表单行字段 */
  const handleDelegateTaskChange = useCallback(
    (index: number, field: keyof DelegateTaskFormRow, value: string | IsolationLevel) => {
      setDelegateTasks(prev =>
        prev.map((t, i) => (i === index ? { ...t, [field]: value } : t)),
      )
    },
    [],
  )

  /** 添加委派任务行 */
  const handleAddDelegateTask = useCallback(() => {
    setDelegateTasks(prev => [
      ...prev,
      { instruction: '', allowedTools: '', isolationLevel: 1, maxTurns: '', maxTokens: '', maxTime: '' },
    ])
  }, [])

  /** 删除委派任务行 */
  const handleDeleteDelegateTask = useCallback((index: number) => {
    setDelegateTasks(prev => prev.filter((_, i) => i !== index))
  }, [])

  /** 发起委派：将表单转换为 SubagentTaskInput 并调用 API */
  const handleDelegate = useCallback(async () => {
    /* 校验：至少一个任务有指令 */
    const validTasks = delegateTasks.filter(t => t.instruction.trim())
    if (validTasks.length === 0) {
      setError('至少需要填写一个任务的指令')
      return
    }

    setIsDelegating(true)
    setError(null)
    setDelegateResult(null)
    try {
      const tasks: SubagentTaskInput[] = validTasks.map((t, i) => {
        const task: SubagentTaskInput = {
          task_id: `task_${Date.now().toString(36)}_${i}`,
          instruction: t.instruction.trim(),
        }
        const tools = t.allowedTools.split(',').map(s => s.trim()).filter(Boolean)
        if (tools.length > 0) task.allowed_tools = tools
        task.isolation_level = t.isolationLevel
        /* 资源限制：仅当至少一个字段填写时携带 */
        const maxTurns = Number(t.maxTurns)
        const maxTokens = Number(t.maxTokens)
        const maxTime = Number(t.maxTime)
        if (t.maxTurns || t.maxTokens || t.maxTime) {
          task.resource_limits = {}
          if (t.maxTurns && !Number.isNaN(maxTurns)) task.resource_limits.max_turns = maxTurns
          if (t.maxTokens && !Number.isNaN(maxTokens)) task.resource_limits.max_tokens = maxTokens
          if (t.maxTime && !Number.isNaN(maxTime)) task.resource_limits.max_time_seconds = maxTime
        }
        return task
      })

      const payload: DelegateRequest = { tasks, merge_strategy: mergeStrategy }
      const result = await subagentsApi.delegate(payload)
      if (!mountedRef.current) return
      setDelegateResult(result)
      appLogger.info({
        event: 'subagents_delegate_completed',
        module: 'subagents',
        message: '委派任务完成',
        extra: { success: result.success, taskCount: tasks.length },
      })
      /* 委派后立即刷新活跃任务 */
      loadActiveTasks()
    } catch (err) {
      if (!mountedRef.current) return
      appLogger.error({
        event: 'subagents_delegate_failed',
        module: 'subagents',
        message: '委派任务失败',
        extra: { error: String(err) },
      })
      setError(getErrorMessage(err, '委派任务失败'))
    } finally {
      if (mountedRef.current) setIsDelegating(false)
    }
  }, [delegateTasks, mergeStrategy, loadActiveTasks])

  /** 取消指定活跃任务 */
  const handleCancelTask = useCallback(async (taskId: string) => {
    setCancellingTaskId(taskId)
    try {
      await subagentsApi.cancelTask(taskId)
      if (!mountedRef.current) return
      appLogger.info({
        event: 'subagents_task_cancelled',
        module: 'subagents',
        message: '任务已取消',
        extra: { taskId },
      })
      /* 立即刷新活跃任务状态 */
      loadActiveTasks()
    } catch (err) {
      if (!mountedRef.current) return
      appLogger.error({
        event: 'subagents_task_cancel_failed',
        module: 'subagents',
        message: '取消任务失败',
        extra: { taskId, error: String(err) },
      })
      setError(getErrorMessage(err, '取消任务失败'))
    } finally {
      if (mountedRef.current) setCancellingTaskId(null)
    }
  }, [loadActiveTasks])

  /* ---- 标签页配置 ---- */
  const tabs: Array<{ key: TabKey; label: string }> = [
    { key: 'definitions', label: '图定义管理' },
    { key: 'history', label: '执行历史' },
    { key: 'agents', label: '已注册 Agent' },
    { key: 'delegate', label: '委派任务' },
  ]

  /* ---- 渲染 ---- */
  return (
    <div className={styles.container}>
      {/* 头部 */}
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <Network size={24} />
          <h1>SubAgent 管理</h1>
        </div>
        <div className={styles.headerActions}>
          <Button variant="ghost" onClick={handleRefresh} disabled={isLoadingDefs || isLoadingHistory || isLoadingAgents}>
            <RefreshCw
              size={16}
              className={
                (activeTab === 'definitions' && isLoadingDefs)
                || (activeTab === 'history' && isLoadingHistory)
                || (activeTab === 'agents' && isLoadingAgents)
                  ? styles.spinning
                  : undefined
              }
            />
            刷新
          </Button>
          {activeTab === 'definitions' && (
            <Button variant="primary" onClick={() => setShowCreateModal(true)}>
              <Plus size={16} />
              新建定义
            </Button>
          )}
        </div>
      </header>

      {/* 错误横幅 */}
      {error && (
        <div className={styles.errorBanner}>
          <div className={styles.errorBannerContent}>
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} aria-label="关闭错误提示">
            <X size={16} />
          </button>
        </div>
      )}

      {/* 标签页导航 */}
      <nav className={styles.tabNav} role="tablist">
        {tabs.map(tab => (
          <button
            key={tab.key}
            className={`${styles.tabButton} ${activeTab === tab.key ? styles.tabActive : ''}`}
            onClick={() => handleTabChange(tab.key)}
            role="tab"
            aria-selected={activeTab === tab.key}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {/* 标签页内容 */}
      <div className={styles.tabContent}>
        {/* ---- 图定义管理 ---- */}
        {activeTab === 'definitions' && (
          <div className={styles.definitionsLayout}>
            {/* 左侧：定义列表 */}
            <aside className={styles.sidebar}>
              <h2 className={styles.sidebarTitle}>图定义列表 ({definitions.length})</h2>
              {isLoadingDefs ? (
                <div className={styles.loadingText}>加载中...</div>
              ) : definitions.length === 0 ? (
                <EmptyState title="暂无图定义" description="点击右上角新建按钮创建" />
              ) : (
                <ul className={styles.definitionList}>
                  {definitions.map(def => (
                    <li key={def.id}>
                      <button
                        className={`${styles.definitionItem} ${selectedDefId === def.id ? styles.active : ''}`}
                        onClick={() => handleSelectDefinition(def)}
                      >
                        <div className={styles.definitionItemName}>
                          {def.name}
                          {def.is_builtin && (
                            <Badge variant="warning" text="内置" />
                          )}
                        </div>
                        {def.description && (
                          <div className={styles.definitionItemDesc}>{def.description}</div>
                        )}
                        <div className={styles.definitionItemMeta}>
                          <span>{def.graph_definition.nodes.length} 节点</span>
                          <span>{def.graph_definition.edges.length} 边</span>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </aside>

            {/* 右侧：编辑器 */}
            <main className={styles.editor}>
              {!selectedDef ? (
                <EmptyState
                  title="未选择图定义"
                  description="从左侧列表选择一个图定义进行编辑，或点击新建按钮创建"
                />
              ) : (
                <div className={styles.editorInner}>
                  <div className={styles.editorHeader}>
                    <Input
                      value={editName}
                      onChange={e => setEditName(e.target.value)}
                      placeholder="图定义名称"
                      className={styles.nameInput}
                      disabled={isReadOnly}
                    />
                    <div className={styles.editorActions}>
                      <Button
                        variant="primary"
                        onClick={handleSave}
                        disabled={isSaving || isReadOnly}
                        loading={isSaving}
                      >
                        <Save size={16} />
                        保存
                      </Button>
                      <Button
                        variant="secondary"
                        onClick={handleOpenRunModal}
                        disabled={isRunning}
                      >
                        <Play size={16} />
                        运行
                      </Button>
                      <Button
                        variant="danger"
                        onClick={handleDelete}
                        disabled={isDeleting || isReadOnly}
                        loading={isDeleting}
                      >
                        <Trash2 size={16} />
                      </Button>
                    </div>
                  </div>

                  <div className={styles.editorBody}>
                    {/* 基本信息表单 */}
                    <div className={styles.formRow}>
                      <label className={styles.formLabel}>描述</label>
                      <Input
                        value={editDescription}
                        onChange={e => setEditDescription(e.target.value)}
                        placeholder="图定义描述（可选）"
                        disabled={isReadOnly}
                      />
                    </div>
                    <div className={styles.formRow}>
                      <label className={styles.formLabel}>标签</label>
                      <Input
                        value={editTags}
                        onChange={e => setEditTags(e.target.value)}
                        placeholder="标签（逗号分隔，可选）"
                        disabled={isReadOnly}
                      />
                    </div>

                    {/* 图定义编辑器：视图切换工具栏 */}
                    <div className={styles.graphSection}>
                      <div className={styles.graphSectionHeader}>
                        <h3>图定义编辑 ({editGraph.nodes.length} 节点 / {editGraph.edges.length} 边)</h3>
                        <div className={styles.viewToggle}>
                          <button
                            className={graphViewMode === 'table' ? styles.toggleActive : ''}
                            onClick={() => setGraphViewMode('table')}
                            aria-label="表格视图"
                          >
                            表格
                          </button>
                          <button
                            className={graphViewMode === 'visual' ? styles.toggleActive : ''}
                            onClick={() => setGraphViewMode('visual')}
                            aria-label="可视化视图"
                          >
                            <Network size={14} />
                            可视化
                          </button>
                        </div>
                      </div>

                      {/* 表格视图：节点 + 边列表 */}
                      {graphViewMode === 'table' && (
                        <>
                          <div className={styles.subSectionHeader}>
                            <span>节点 ({editGraph.nodes.length})</span>
                            {!isReadOnly && (
                              <Button variant="secondary" size="sm" onClick={handleAddNode}>
                                <Plus size={14} />
                                添加节点
                              </Button>
                            )}
                          </div>
                          {editGraph.nodes.length === 0 ? (
                            <p className={styles.emptyHint}>暂无节点，点击添加节点按钮创建</p>
                          ) : (
                            <div className={styles.nodeList}>
                              {editGraph.nodes.map((node, index) => (
                                <div key={index} className={styles.nodeRow}>
                                  <Input
                                    value={node.name}
                                    onChange={e => handleNodeChange(index, 'name', e.target.value)}
                                    placeholder="节点名称"
                                    className={styles.nodeNameInput}
                                    disabled={isReadOnly}
                                  />
                                  <Input
                                    value={node.agent}
                                    onChange={e => handleNodeChange(index, 'agent', e.target.value)}
                                    placeholder="Agent 名称"
                                    className={styles.nodeAgentInput}
                                    disabled={isReadOnly}
                                  />
                                  <Input
                                    value={node.description || ''}
                                    onChange={e => handleNodeChange(index, 'description', e.target.value)}
                                    placeholder="描述（可选）"
                                    className={styles.nodeDescInput}
                                    disabled={isReadOnly}
                                  />
                                  {!isReadOnly && (
                                    <button
                                      className={styles.iconButtonDanger}
                                      onClick={() => handleDeleteNode(index)}
                                      aria-label="删除节点"
                                    >
                                      <Trash2 size={16} />
                                    </button>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}

                          <div className={styles.subSectionHeader}>
                            <span>边 ({editGraph.edges.length})</span>
                            {!isReadOnly && (
                              <Button variant="secondary" size="sm" onClick={handleAddEdge}>
                                <Plus size={14} />
                                添加边
                              </Button>
                            )}
                          </div>
                          {editGraph.edges.length === 0 ? (
                            <p className={styles.emptyHint}>暂无边，点击添加边按钮创建</p>
                          ) : (
                            <div className={styles.edgeList}>
                              {editGraph.edges.map((edge, index) => (
                                <div key={index} className={styles.edgeRow}>
                                  <select
                                    className={styles.select}
                                    value={edge.source}
                                    onChange={e => handleEdgeChange(index, 'source', e.target.value)}
                                    disabled={isReadOnly}
                                  >
                                    <option value="">源节点</option>
                                    {nodeNames.map(name => (
                                      <option key={name} value={name}>{name}</option>
                                    ))}
                                  </select>
                                  <select
                                    className={styles.select}
                                    value={edge.target}
                                    onChange={e => handleEdgeChange(index, 'target', e.target.value)}
                                    disabled={isReadOnly}
                                  >
                                    <option value="">目标节点</option>
                                    {nodeNames.map(name => (
                                      <option key={name} value={name}>{name}</option>
                                    ))}
                                  </select>
                                  <Input
                                    value={edge.condition || ''}
                                    onChange={e => handleEdgeChange(index, 'condition', e.target.value)}
                                    placeholder="条件（可选）"
                                    className={styles.edgeConditionInput}
                                    disabled={isReadOnly}
                                  />
                                  {!isReadOnly && (
                                    <button
                                      className={styles.iconButtonDanger}
                                      onClick={() => handleDeleteEdge(index)}
                                      aria-label="删除边"
                                    >
                                      <Trash2 size={16} />
                                    </button>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </>
                      )}

                      {/* 可视化视图：reactflow 画布（按 agent 着色，dagre 自动布局） */}
                      {graphViewMode === 'visual' && (
                        <>
                          {!isReadOnly && (
                            <div className={styles.subSectionHeader}>
                              <span>节点 ({editGraph.nodes.length})</span>
                              <Button variant="secondary" size="sm" onClick={handleAddNode}>
                                <Plus size={14} />
                                添加节点
                              </Button>
                            </div>
                          )}
                          {editGraph.nodes.length === 0 ? (
                            <p className={styles.emptyHint}>暂无节点，点击添加节点按钮创建</p>
                          ) : (
                            <div className={styles.graphContainer}>
                              <ReactFlow
                                nodes={computedFlow.nodes}
                                edges={computedFlow.edges as Edge[]}
                                nodeTypes={nodeTypes}
                                onNodeDoubleClick={handleNodeDoubleClick}
                                fitView
                                minZoom={0.2}
                                maxZoom={2}
                                nodesDraggable={!isReadOnly}
                              >
                                <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
                                <Controls />
                              </ReactFlow>
                            </div>
                          )}
                          <p className={styles.hint}>双击节点可编辑名称/Agent/描述；边条件以标签显示</p>
                        </>
                      )}
                    </div>

                    <div className={styles.graphSection}>
                      <div className={styles.graphSectionHeader}>
                        <h3>入口节点</h3>
                      </div>
                      <select
                        className={styles.select}
                        value={editGraph.entry_point}
                        onChange={e => handleEntryPointChange(e.target.value)}
                        disabled={isReadOnly}
                      >
                        <option value="">选择入口节点</option>
                        {nodeNames.map(name => (
                          <option key={name} value={name}>{name}</option>
                        ))}
                      </select>
                    </div>

                    <div className={styles.graphSection}>
                      <div className={styles.graphSectionHeader}>
                        <h3>终点节点</h3>
                      </div>
                      {nodeNames.length === 0 ? (
                        <p className={styles.emptyHint}>暂无节点可选</p>
                      ) : (
                        <div className={styles.finishPointsList}>
                          {nodeNames.map(name => (
                            <label key={name} className={styles.checkboxLabel}>
                              <input
                                type="checkbox"
                                checked={editGraph.finish_points.includes(name)}
                                onChange={() => handleToggleFinishPoint(name)}
                                disabled={isReadOnly}
                              />
                              <span>{name}</span>
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 运行结果展示 */}
                  {runResult && (
                    <div className={styles.runResultArea}>
                      <RunResultDisplay result={runResult} />
                    </div>
                  )}
                </div>
              )}
            </main>
          </div>
        )}

        {/* ---- 执行历史 ---- */}
        {activeTab === 'history' && (
          <div className={styles.historyContainer}>
            <div className={styles.historyToolbar}>
              <label className={styles.formLabel}>按图名称过滤</label>
              <select
                className={styles.select}
                value={historyFilter}
                onChange={e => setHistoryFilter(e.target.value)}
              >
                <option value="">全部</option>
                {graphNameOptions.map(name => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </div>

            {isLoadingHistory ? (
              <div className={styles.loadingText}>加载中...</div>
            ) : filteredHistory.length === 0 ? (
              <EmptyState title="暂无执行历史" description="运行图定义后将在此显示执行记录" />
            ) : (
              <div className={styles.historyList}>
                {filteredHistory.map(item => {
                  const expanded = expandedHistoryId === item.id
                  return (
                    <div key={item.id} className={styles.historyItem}>
                      <button
                        className={styles.historyItemHeader}
                        onClick={() => handleToggleHistory(item.id)}
                      >
                        <div className={styles.historyItemLeft}>
                          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                          <span className={styles.historyGraphName}>{item.graph_name}</span>
                          <Badge
                            variant={item.success ? 'success' : 'error'}
                            text={item.success ? '成功' : '失败'}
                          />
                          <span className={styles.historyMode}>#{item.id} {item.execution_mode}</span>
                        </div>
                        <div className={styles.historyItemRight}>
                          <span className={styles.historyDuration}>
                            <Clock size={14} />
                            {formatDuration(item.duration_seconds)}
                          </span>
                          <span className={styles.historyTime}>{formatTimestamp(item.created_at)}</span>
                        </div>
                      </button>
                      {expanded && (
                        <div className={styles.historyItemBody}>
                          <div className={styles.historyDetailSection}>
                            <h5>初始上下文</h5>
                            <pre className={styles.jsonBlock}>{prettyJson(item.initial_context)}</pre>
                          </div>
                          <div className={styles.historyDetailSection}>
                            <h5>结果</h5>
                            <pre className={styles.jsonBlock}>{prettyJson(item.results)}</pre>
                          </div>
                          {Object.keys(item.errors).length > 0 && (
                            <div className={styles.historyDetailSection}>
                              <h5>错误</h5>
                              <pre className={styles.jsonBlock}>{prettyJson(item.errors)}</pre>
                            </div>
                          )}
                          {item.execution_log.length > 0 && (
                            <div className={styles.historyDetailSection}>
                              <h5>执行日志</h5>
                              <pre className={styles.jsonBlock}>{prettyJson(item.execution_log)}</pre>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* ---- 已注册 Agent ---- */}
        {activeTab === 'agents' && (
          <div className={styles.agentsContainer}>
            {isLoadingAgents ? (
              <div className={styles.loadingText}>加载中...</div>
            ) : agents.length === 0 ? (
              <EmptyState title="暂无已注册 Agent" description="后端注册 Agent 后将在此显示" />
            ) : (
              <div className={styles.agentsGrid}>
                {agents.map(agent => (
                  <Card key={agent.name} className={styles.agentCard}>
                    <div className={styles.agentCardHeader}>
                      <CheckCircle size={18} className={styles.agentIcon} />
                      <h3 className={styles.agentName}>{agent.name}</h3>
                    </div>
                    <p className={styles.agentDescription}>{agent.description}</p>
                    {agent.capabilities.length > 0 && (
                      <div className={styles.agentCapabilities}>
                        {agent.capabilities.map(cap => (
                          <Badge key={cap} variant="primary" text={cap} />
                        ))}
                      </div>
                    )}
                    <div className={styles.agentMeta}>
                      <Clock size={12} />
                      <span>注册于 {formatUnixTimestamp(agent.registered_at)}</span>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ---- 委派任务 ---- */}
        {activeTab === 'delegate' && (
          <div className={styles.delegateContainer}>
            <div className={styles.delegateLayout}>
              {/* 左侧：任务表单 */}
              <section className={styles.delegateFormPanel}>
                <div className={styles.delegateSectionHeader}>
                  <h3>任务列表 ({delegateTasks.length})</h3>
                  <Button variant="secondary" size="sm" onClick={handleAddDelegateTask}>
                    <Plus size={14} />
                    添加任务
                  </Button>
                </div>

                <div className={styles.taskFormList}>
                  {delegateTasks.map((task, index) => (
                    <div key={index} className={styles.taskFormRow}>
                      <div className={styles.taskFormMain}>
                        <div className={styles.formRow}>
                          <label className={styles.formLabel}>指令 #{index + 1}</label>
                          <Textarea
                            value={task.instruction}
                            onChange={e => handleDelegateTaskChange(index, 'instruction', e.target.value)}
                            rows={2}
                            placeholder="任务指令"
                          />
                        </div>
                        <div className={styles.taskFormInline}>
                          <div className={styles.formRow}>
                            <label className={styles.formLabel}>允许工具（逗号分隔）</label>
                            <Input
                              value={task.allowedTools}
                              onChange={e => handleDelegateTaskChange(index, 'allowedTools', e.target.value)}
                              placeholder="tool_a, tool_b"
                            />
                          </div>
                          <div className={styles.formRow}>
                            <label className={styles.formLabel}>隔离级别</label>
                            <select
                              className={styles.select}
                              value={task.isolationLevel}
                              onChange={e => handleDelegateTaskChange(index, 'isolationLevel', Number(e.target.value) as IsolationLevel)}
                            >
                              {ISOLATION_LEVEL_OPTIONS.map(opt => (
                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                              ))}
                            </select>
                          </div>
                        </div>
                        <div className={styles.taskFormInline}>
                          <div className={styles.formRow}>
                            <label className={styles.formLabel}>最大轮次（可选）</label>
                            <Input
                              type="number"
                              value={task.maxTurns}
                              onChange={e => handleDelegateTaskChange(index, 'maxTurns', e.target.value)}
                              placeholder="如 10"
                            />
                          </div>
                          <div className={styles.formRow}>
                            <label className={styles.formLabel}>最大 Token（可选）</label>
                            <Input
                              type="number"
                              value={task.maxTokens}
                              onChange={e => handleDelegateTaskChange(index, 'maxTokens', e.target.value)}
                              placeholder="如 4096"
                            />
                          </div>
                          <div className={styles.formRow}>
                            <label className={styles.formLabel}>最大时间秒（可选）</label>
                            <Input
                              type="number"
                              value={task.maxTime}
                              onChange={e => handleDelegateTaskChange(index, 'maxTime', e.target.value)}
                              placeholder="如 120"
                            />
                          </div>
                        </div>
                      </div>
                      {delegateTasks.length > 1 && (
                        <button
                          className={styles.iconButtonDanger}
                          onClick={() => handleDeleteDelegateTask(index)}
                          aria-label="删除任务"
                        >
                          <Trash2 size={16} />
                        </button>
                      )}
                    </div>
                  ))}
                </div>

                {/* 合并策略 + 委派按钮 */}
                <div className={styles.delegateFooter}>
                  <div className={styles.formRow}>
                    <label className={styles.formLabel}>合并策略</label>
                    <select
                      className={styles.select}
                      value={mergeStrategy}
                      onChange={e => setMergeStrategy(e.target.value as MergeStrategy)}
                    >
                      {MERGE_STRATEGY_OPTIONS.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </div>
                  <Button
                    variant="primary"
                    onClick={handleDelegate}
                    disabled={isDelegating}
                    loading={isDelegating}
                  >
                    {isDelegating ? <Loader size={16} className={styles.spinning} /> : <Send size={16} />}
                    {isDelegating ? '委派中...' : '发起委派'}
                  </Button>
                </div>

                {/* 编排器能力提示 */}
                {capabilities && (
                  <div className={styles.capabilitiesHint}>
                    <span>默认轮次: {capabilities.default_limits.max_turns}</span>
                    <span>默认 Token: {capabilities.default_limits.max_tokens}</span>
                    <span>默认超时: {capabilities.default_limits.max_time_seconds}s</span>
                    {activeTasks && <span>最大并行: {activeTasks.max_parallel}</span>}
                  </div>
                )}
              </section>

              {/* 右侧：活跃任务 + 委派结果 */}
              <section className={styles.delegateSidePanel}>
                {/* 活跃任务列表（每 3 秒轮询） */}
                <div className={styles.delegateSectionHeader}>
                  <h3>活跃任务</h3>
                  <span className={styles.pollHint}>每 3 秒自动刷新</span>
                </div>
                {!activeTasks || Object.keys(activeTasks.active_tasks).length === 0 ? (
                  <EmptyState title="暂无活跃任务" description="发起委派后将在此显示任务状态" />
                ) : (
                  <div className={styles.activeTaskList}>
                    {Object.entries(activeTasks.active_tasks).map(([taskId, state]) => (
                      <div key={taskId} className={styles.activeTaskItem}>
                        <div className={styles.activeTaskInfo}>
                          <span className={styles.activeTaskId}>{taskId}</span>
                          <Badge variant={getLifecycleBadgeVariant(state)} text={state} />
                        </div>
                        <button
                          className={styles.iconButtonDanger}
                          onClick={() => handleCancelTask(taskId)}
                          disabled={cancellingTaskId === taskId || state === 'completed' || state === 'cancelled' || state === 'terminated'}
                          aria-label="取消任务"
                        >
                          {cancellingTaskId === taskId ? <Loader size={16} className={styles.spinning} /> : <XCircle size={16} />}
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {/* 委派结果 */}
                {delegateResult && (
                  <div className={styles.delegateResult}>
                    <div className={styles.runResultHeader}>
                      <h4>委派结果</h4>
                      <Badge
                        variant={delegateResult.success ? 'success' : 'error'}
                        text={delegateResult.success ? '成功' : '失败'}
                      />
                    </div>
                    {delegateResult.merged_output && (
                      <div className={styles.runResultSection}>
                        <h5>合并输出</h5>
                        <pre className={styles.jsonBlock}>{delegateResult.merged_output}</pre>
                      </div>
                    )}
                    {delegateResult.results.length > 0 && (
                      <div className={styles.runResultSection}>
                        <h5>任务结果 ({delegateResult.results.length})</h5>
                        <div className={styles.executionLogList}>
                          {delegateResult.results.map((r, i) => (
                            <div key={i} className={styles.executionLogItem}>
                              <div className={styles.executionLogHeader}>
                                <span className={styles.executionLogNode}>{r.task_id}</span>
                                <Badge
                                  variant={r.success ? 'success' : 'error'}
                                  text={r.success ? '成功' : '失败'}
                                />
                                <Badge variant="primary" text={r.lifecycle_state} />
                                {r.elapsed_seconds > 0 && (
                                  <span className={styles.executionLogDuration}>
                                    {formatDuration(r.elapsed_seconds)}
                                  </span>
                                )}
                              </div>
                              {r.error && (
                                <div className={styles.executionLogError}>{r.error}</div>
                              )}
                              {r.output && (
                                <div className={styles.messageContent}>{r.output}</div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {delegateResult.security_issues.length > 0 && (
                      <div className={styles.runResultSection}>
                        <h5>安全问题</h5>
                        <pre className={styles.jsonBlock}>{prettyJson(delegateResult.security_issues)}</pre>
                      </div>
                    )}
                  </div>
                )}
              </section>
            </div>
          </div>
        )}
      </div>

      {/* 创建图定义弹窗 */}
      <Modal
        open={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        title="新建图定义"
      >
        <div className={styles.modalForm}>
          <div className={styles.formRow}>
            <label className={styles.formLabel}>名称 *</label>
            <Input
              value={createName}
              onChange={e => setCreateName(e.target.value)}
              placeholder="图定义名称"
            />
          </div>
          <div className={styles.formRow}>
            <label className={styles.formLabel}>描述</label>
            <Input
              value={createDescription}
              onChange={e => setCreateDescription(e.target.value)}
              placeholder="图定义描述（可选）"
            />
          </div>
          <div className={styles.formRow}>
            <label className={styles.formLabel}>标签</label>
            <Input
              value={createTags}
              onChange={e => setCreateTags(e.target.value)}
              placeholder="标签（逗号分隔，可选）"
            />
          </div>
          <p className={styles.hint}>创建后将生成空图定义，可在编辑器中添加节点和边</p>
          <div className={styles.modalFooter}>
            <Button variant="ghost" onClick={() => setShowCreateModal(false)}>取消</Button>
            <Button variant="primary" onClick={handleCreate} disabled={!createName.trim() || isCreating} loading={isCreating}>
              创建
            </Button>
          </div>
        </div>
      </Modal>

      {/* 运行图定义弹窗 */}
      <Modal
        open={showRunModal}
        onClose={() => !isRunning && setShowRunModal(false)}
        title={`运行图定义 - ${selectedDef?.name || ''}`}
      >
        <div className={styles.modalForm}>
          <div className={styles.formRow}>
            <label className={styles.formLabel}>上下文 (JSON)</label>
            <Textarea
              value={runContext}
              onChange={e => setRunContext(e.target.value)}
              rows={4}
              placeholder='{"key": "value"}'
              className={styles.jsonTextarea}
            />
          </div>
          <div className={styles.formRow}>
            <label className={styles.formLabel}>消息 (JSON 数组)</label>
            <Textarea
              value={runMessages}
              onChange={e => setRunMessages(e.target.value)}
              rows={4}
              placeholder='[{"role": "user", "content": "你好"}]'
              className={styles.jsonTextarea}
            />
          </div>

          {runResult && <RunResultDisplay result={runResult} />}

          <div className={styles.modalFooter}>
            <Button variant="ghost" onClick={() => setShowRunModal(false)} disabled={isRunning}>
              关闭
            </Button>
            <Button variant="primary" onClick={handleRun} disabled={isRunning} loading={isRunning}>
              <Play size={16} />
              {isRunning ? '执行中...' : '运行'}
            </Button>
          </div>
        </div>
      </Modal>

      {/* 节点编辑弹窗（可视化视图双击节点触发） */}
      <Modal
        open={editingNodeIndex !== null}
        onClose={handleNodeEditCancel}
        title={`编辑节点 #${editingNodeIndex !== null ? editingNodeIndex + 1 : ''}`}
      >
        {nodeEditDraft && (
          <div className={styles.modalForm}>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>节点名称</label>
              <Input
                value={nodeEditDraft.name}
                onChange={e => handleNodeDraftChange('name', e.target.value)}
                placeholder="节点名称"
              />
            </div>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>Agent 名称</label>
              <Input
                value={nodeEditDraft.agent}
                onChange={e => handleNodeDraftChange('agent', e.target.value)}
                placeholder="Agent 名称"
              />
            </div>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>描述</label>
              <Textarea
                value={nodeEditDraft.description || ''}
                onChange={e => handleNodeDraftChange('description', e.target.value)}
                rows={3}
                placeholder="节点描述（可选）"
              />
            </div>
            <div className={styles.modalFooter}>
              <Button variant="ghost" onClick={handleNodeEditCancel}>取消</Button>
              <Button variant="primary" onClick={handleNodeEditSave}>保存</Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
