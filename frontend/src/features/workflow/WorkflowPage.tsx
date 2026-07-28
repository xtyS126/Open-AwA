/**
 * 工作流管理页面：可视化编辑器 + 执行监控。
 * 支持 6 种步骤类型：tool/skill/plugin/condition/parallel/sub_workflow。
 * 提供步骤的增删改查、拖拽排序、JSON 预览、执行与结果展示。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Plus,
  Trash2,
  Play,
  Save,
  Edit3,
  X,
  ChevronUp,
  ChevronDown,
  Workflow as WorkflowIcon,
  RefreshCw,
  Code,
  Eye,
  Network,
} from 'lucide-react'
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  useEdgesState,
  useNodesState,
  type NodeProps,
  type Node,
  type Edge,
} from 'reactflow'
import 'reactflow/dist/style.css'

import {
  WorkflowResponse,
  WorkflowStep,
  WorkflowStepType,
  WorkflowDefinition,
  WorkflowExecutionResponse,
  listWorkflows,
  createWorkflow,
  updateWorkflow,
  deleteWorkflow,
  executeWorkflow,
} from '@/shared/api/workflowApi'
import { appLogger } from '@/shared/utils/logger'
import { Button, Input, Modal, Textarea, EmptyState, Badge } from '@/shared/components/ui'
import {
  STEP_TYPE_COLORS,
  findStepById,
  stepsToGraph,
  updateStepInTree,
  type WorkflowEdgeData,
  type WorkflowNodeData,
} from './workflowGraph'

import styles from './WorkflowPage.module.css'

/* ---- 工具函数 ---- */

function getErrorMessage(error: unknown, fallback: string): string {
  const maybeError = error as { response?: { data?: { detail?: string } } }
  const detail = maybeError?.response?.data?.detail
  return typeof detail === 'string' && detail.trim() ? detail : fallback
}

/** 步骤类型元数据：标签、变体、描述 */
const STEP_TYPE_META: Record<WorkflowStepType, {
  label: string
  variant: 'primary' | 'success' | 'warning' | 'error'
  description: string
}> = {
  tool: { label: '工具', variant: 'primary', description: '调用内置工具执行操作' },
  skill: { label: '技能', variant: 'success', description: '调用已注册的技能' },
  plugin: { label: '插件', variant: 'primary', description: '调用插件方法' },
  condition: { label: '条件', variant: 'warning', description: '根据表达式分支执行' },
  parallel: { label: '并行', variant: 'primary', description: '多分支并行执行' },
  sub_workflow: { label: '子工作流', variant: 'warning', description: '引用其他工作流递归执行' },
}

/** 生成唯一步骤 ID */
function generateStepId(prefix: string = 'step'): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`
}

/** 创建默认步骤 */
function createDefaultStep(type: WorkflowStepType): WorkflowStep {
  const id = generateStepId(type)
  const base: WorkflowStep = { id, type, name: id }
  switch (type) {
    case 'tool':
      return { ...base, tool: '', action: '', params: {} }
    case 'skill':
      return { ...base, skill_name: '' }
    case 'plugin':
      return { ...base, plugin_name: '', plugin_method: '', kwargs: {} }
    case 'condition':
      return { ...base, expression: '', on_true: [], on_false: [] }
    case 'parallel':
      return { ...base, branches: [[]], on_error: 'stop' }
    case 'sub_workflow':
      return { ...base, workflow_id: null, workflow_name: null, inputs: {}, max_depth: 5 }
  }
}

/* ---- 图视图自定义节点 ---- */

/** 自定义节点组件：按步骤类型着色，显示类型标签与步骤名称 */
function WorkflowNodeComponent({ data }: NodeProps<WorkflowNodeData>) {
  const color = STEP_TYPE_COLORS[data.stepType]
  const typeLabel = data.isReference
    ? '引用'
    : STEP_TYPE_META[data.stepType as WorkflowStepType].label
  return (
    <div
      className={styles.graphNode}
      style={{ borderLeftColor: color }}
      data-step-type={data.stepType}
    >
      <Handle type="target" position={Position.Top} className={styles.graphNodeHandle} />
      <div className={styles.graphNodeHeader} style={{ backgroundColor: color }}>
        {typeLabel}
      </div>
      <div className={styles.graphNodeBody}>
        <span className={styles.graphNodeTitle}>{data.title}</span>
        {data.isReference && data.referenceName && (
          <span className={styles.graphNodeRef}>{data.referenceName}</span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className={styles.graphNodeHandle} />
    </div>
  )
}

/** reactflow 节点类型映射（模块级定义，避免每次渲染重建） */
const nodeTypes = { workflowNode: WorkflowNodeComponent }

/* ---- 步骤编辑器组件 ---- */

interface StepEditorProps {
  step: WorkflowStep
  onChange: (step: WorkflowStep) => void
  onCancel: () => void
}

function StepEditor({ step, onChange, onCancel }: StepEditorProps) {
  const [draft, setDraft] = useState<WorkflowStep>(step)

  const handleFieldChange = <K extends keyof WorkflowStep>(key: K, value: WorkflowStep[K]) => {
    setDraft(prev => ({ ...prev, [key]: value }))
  }

  const handleSave = () => {
    onChange(draft)
  }

  return (
    <div className={styles.stepEditor}>
      <div className={styles.stepEditorHeader}>
        <h3>编辑步骤 - {STEP_TYPE_META[step.type].label}</h3>
        <button className={styles.closeButton} onClick={onCancel} aria-label="关闭">
          <X size={18} />
        </button>
      </div>

      <div className={styles.stepEditorBody}>
        <div className={styles.formRow}>
          <label className={styles.formLabel}>步骤 ID</label>
          <Input
            value={draft.id}
            onChange={e => handleFieldChange('id', e.target.value)}
            placeholder="step_unique_id"
          />
        </div>

        <div className={styles.formRow}>
          <label className={styles.formLabel}>名称</label>
          <Input
            value={draft.name || ''}
            onChange={e => handleFieldChange('name', e.target.value)}
            placeholder="步骤显示名称"
          />
        </div>

        {draft.type === 'tool' && (
          <>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>工具名称</label>
              <Input
                value={draft.tool || ''}
                onChange={e => handleFieldChange('tool', e.target.value)}
                placeholder="例如：echo"
              />
            </div>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>操作</label>
              <Input
                value={draft.action || ''}
                onChange={e => handleFieldChange('action', e.target.value)}
                placeholder="例如：say"
              />
            </div>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>参数 (JSON)</label>
              <Textarea
                value={JSON.stringify(draft.params || {}, null, 2)}
                onChange={e => {
                  try {
                    const parsed = JSON.parse(e.target.value)
                    handleFieldChange('params', parsed)
                  } catch {
                    // 解析失败时保留原值
                  }
                }}
                rows={4}
                placeholder='{"key": "value"}'
              />
            </div>
          </>
        )}

        {draft.type === 'skill' && (
          <div className={styles.formRow}>
            <label className={styles.formLabel}>技能名称</label>
            <Input
              value={draft.skill_name || ''}
              onChange={e => handleFieldChange('skill_name', e.target.value)}
              placeholder="例如：code_review"
            />
          </div>
        )}

        {draft.type === 'plugin' && (
          <>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>插件名称</label>
              <Input
                value={draft.plugin_name || ''}
                onChange={e => handleFieldChange('plugin_name', e.target.value)}
                placeholder="例如：hello-world"
              />
            </div>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>插件方法</label>
              <Input
                value={draft.plugin_method || ''}
                onChange={e => handleFieldChange('plugin_method', e.target.value)}
                placeholder="例如：greet"
              />
            </div>
          </>
        )}

        {draft.type === 'condition' && (
          <div className={styles.formRow}>
            <label className={styles.formLabel}>条件表达式</label>
            <Textarea
              value={draft.expression || ''}
              onChange={e => handleFieldChange('expression', e.target.value)}
              rows={3}
              placeholder="例如：context.x > 10"
            />
            <p className={styles.hint}>支持变量：context.x、steps.y.success、last_result.z</p>
          </div>
        )}

        {draft.type === 'parallel' && (
          <div className={styles.formRow}>
            <label className={styles.formLabel}>错误处理策略</label>
            <select
              className={styles.select}
              value={draft.on_error || 'stop'}
              onChange={e => handleFieldChange('on_error', e.target.value as 'stop' | 'continue')}
            >
              <option value="stop">stop - 任一分支失败则停止</option>
              <option value="continue">continue - 继续执行其他分支</option>
            </select>
            <p className={styles.hint}>并行步骤的分支在保存后通过拖拽添加</p>
          </div>
        )}

        {draft.type === 'sub_workflow' && (
          <>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>引用工作流 ID</label>
              <Input
                type="number"
                value={draft.workflow_id ?? ''}
                onChange={e => handleFieldChange('workflow_id', e.target.value ? Number(e.target.value) : null)}
                placeholder="输入子工作流 ID"
              />
            </div>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>或引用工作流名称</label>
              <Input
                value={draft.workflow_name || ''}
                onChange={e => handleFieldChange('workflow_name', e.target.value || null)}
                placeholder="输入子工作流名称"
              />
            </div>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>最大递归深度</label>
              <Input
                type="number"
                value={draft.max_depth ?? 5}
                onChange={e => handleFieldChange('max_depth', Number(e.target.value) || 5)}
              />
            </div>
          </>
        )}
      </div>

      <div className={styles.stepEditorFooter}>
        <Button variant="ghost" onClick={onCancel}>取消</Button>
        <Button variant="primary" onClick={handleSave}>保存</Button>
      </div>
    </div>
  )
}

/* ---- 步骤卡片组件 ---- */

interface StepCardProps {
  step: WorkflowStep
  index: number
  total: number
  onEdit: () => void
  onDelete: () => void
  onMoveUp: () => void
  onMoveDown: () => void
}

function StepCard({ step, index, total, onEdit, onDelete, onMoveUp, onMoveDown }: StepCardProps) {
  const meta = STEP_TYPE_META[step.type]
  return (
    <div className={styles.stepCard}>
      <div className={styles.stepCardHeader}>
        <div className={styles.stepCardLeft}>
          <span className={styles.stepIndex}>{index + 1}</span>
          <Badge variant={meta.variant} text={meta.label} />
          <span className={styles.stepName}>{step.name || step.id}</span>
        </div>
        <div className={styles.stepCardActions}>
          <button
            className={styles.iconButton}
            onClick={onMoveUp}
            disabled={index === 0}
            aria-label="上移"
          >
            <ChevronUp size={16} />
          </button>
          <button
            className={styles.iconButton}
            onClick={onMoveDown}
            disabled={index === total - 1}
            aria-label="下移"
          >
            <ChevronDown size={16} />
          </button>
          <button className={styles.iconButton} onClick={onEdit} aria-label="编辑">
            <Edit3 size={16} />
          </button>
          <button className={styles.iconButtonDanger} onClick={onDelete} aria-label="删除">
            <Trash2 size={16} />
          </button>
        </div>
      </div>
      <div className={styles.stepCardBody}>
        <p className={styles.stepDescription}>{meta.description}</p>
        {step.type === 'tool' && (
          <div className={styles.stepMeta}>
            <span>工具: {step.tool || '-'}</span>
            <span>操作: {step.action || '-'}</span>
          </div>
        )}
        {step.type === 'skill' && (
          <div className={styles.stepMeta}>
            <span>技能: {step.skill_name || '-'}</span>
          </div>
        )}
        {step.type === 'plugin' && (
          <div className={styles.stepMeta}>
            <span>插件: {step.plugin_name || '-'}</span>
            <span>方法: {step.plugin_method || '-'}</span>
          </div>
        )}
        {step.type === 'condition' && (
          <div className={styles.stepMeta}>
            <span>表达式: {step.expression || '-'}</span>
          </div>
        )}
        {step.type === 'parallel' && (
          <div className={styles.stepMeta}>
            <span>分支数: {step.branches?.length || 0}</span>
            <span>错误处理: {step.on_error || 'stop'}</span>
          </div>
        )}
        {step.type === 'sub_workflow' && (
          <div className={styles.stepMeta}>
            <span>工作流 ID: {step.workflow_id ?? '-'}</span>
            <span>名称: {step.workflow_name || '-'}</span>
          </div>
        )}
      </div>
    </div>
  )
}

/* ---- 主页面组件 ---- */

export default function WorkflowPage() {
  const [workflows, setWorkflows] = useState<WorkflowResponse[]>([])
  const [selectedWorkflow, setSelectedWorkflow] = useState<WorkflowResponse | null>(null)
  const [steps, setSteps] = useState<WorkflowStep[]>([])
  const [workflowName, setWorkflowName] = useState('')
  const [workflowDescription, setWorkflowDescription] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAddStep, setShowAddStep] = useState(false)
  const [editingStep, setEditingStep] = useState<WorkflowStep | null>(null)
  const [editingIndex, setEditingIndex] = useState<number>(-1)
  const [executionResult, setExecutionResult] = useState<WorkflowExecutionResponse | null>(null)
  const [viewMode, setViewMode] = useState<'visual' | 'json' | 'graph'>('visual')
  const [editingFromGraph, setEditingFromGraph] = useState(false)

  /** 加载工作流列表 */
  const loadWorkflows = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const list = await listWorkflows()
      setWorkflows(list)
    } catch (err) {
      appLogger.error({ event: 'workflow_list_load_failed', module: 'workflow', message: '加载工作流列表失败', extra: { error: String(err) } })
      setError(getErrorMessage(err, '加载工作流列表失败'))
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadWorkflows()
  }, [loadWorkflows])

  /** 选择工作流进行编辑 */
  const handleSelectWorkflow = (wf: WorkflowResponse) => {
    setSelectedWorkflow(wf)
    setSteps(wf.definition?.steps || [])
    setWorkflowName(wf.name)
    setWorkflowDescription(wf.description || '')
    setExecutionResult(null)
  }

  /** 新建工作流 */
  const handleNewWorkflow = () => {
    setSelectedWorkflow(null)
    setSteps([])
    setWorkflowName('新工作流')
    setWorkflowDescription('')
    setExecutionResult(null)
  }

  /** 添加步骤 */
  const handleAddStep = (type: WorkflowStepType) => {
    const newStep = createDefaultStep(type)
    setSteps(prev => [...prev, newStep])
    setShowAddStep(false)
    // 自动打开编辑器
    setEditingStep(newStep)
    setEditingIndex(steps.length)
  }

  /** 更新步骤 */
  const handleUpdateStep = (updated: WorkflowStep) => {
    if (editingFromGraph && editingStep) {
      /* 图视图模式：按步骤 ID 在步骤树中递归更新 */
      setSteps(prev => updateStepInTree(prev, editingStep.id, updated))
    } else if (editingIndex >= 0) {
      setSteps(prev => prev.map((s, i) => (i === editingIndex ? updated : s)))
    }
    setEditingStep(null)
    setEditingIndex(-1)
    setEditingFromGraph(false)
  }

  /** 删除步骤 */
  const handleDeleteStep = (index: number) => {
    setSteps(prev => prev.filter((_, i) => i !== index))
  }

  /** 移动步骤 */
  const handleMoveStep = (index: number, direction: 'up' | 'down') => {
    setSteps(prev => {
      const next = [...prev]
      const targetIndex = direction === 'up' ? index - 1 : index + 1
      if (targetIndex < 0 || targetIndex >= next.length) return prev
      const tmp = next[index]
      next[index] = next[targetIndex]
      next[targetIndex] = tmp
      return next
    })
  }

  /** 保存工作流 */
  const handleSave = async () => {
    if (!workflowName.trim()) {
      setError('工作流名称不能为空')
      return
    }
    if (steps.length === 0) {
      setError('至少需要一个步骤')
      return
    }

    setIsSaving(true)
    setError(null)
    try {
      const definition: WorkflowDefinition = {
        name: workflowName,
        description: workflowDescription,
        steps,
      }

      if (selectedWorkflow) {
        const updated = await updateWorkflow(selectedWorkflow.id, {
          name: workflowName,
          description: workflowDescription,
          definition,
        })
        setSelectedWorkflow(updated)
        appLogger.info({ event: 'workflow_updated', module: 'workflow', message: '工作流更新成功', extra: { id: updated.id } })
      } else {
        const created = await createWorkflow({
          name: workflowName,
          description: workflowDescription,
          definition,
        })
        setSelectedWorkflow(created)
        appLogger.info({ event: 'workflow_created', module: 'workflow', message: '工作流创建成功', extra: { id: created.id } })
      }
      await loadWorkflows()
    } catch (err) {
      appLogger.error({ event: 'workflow_save_failed', module: 'workflow', message: '保存工作流失败', extra: { error: String(err) } })
      setError(getErrorMessage(err, '保存工作流失败'))
    } finally {
      setIsSaving(false)
    }
  }

  /** 执行工作流 */
  const handleExecute = async () => {
    if (!selectedWorkflow) {
      setError('请先保存工作流')
      return
    }
    setIsExecuting(true)
    setError(null)
    setExecutionResult(null)
    try {
      const result = await executeWorkflow(selectedWorkflow.id)
      setExecutionResult(result)
      appLogger.info({ event: 'workflow_executed', module: 'workflow', message: '工作流执行完成', extra: { id: selectedWorkflow.id, status: result.status } })
    } catch (err) {
      appLogger.error({ event: 'workflow_execute_failed', module: 'workflow', message: '工作流执行失败', extra: { error: String(err) } })
      setError(getErrorMessage(err, '工作流执行失败'))
    } finally {
      setIsExecuting(false)
    }
  }

  /** 删除工作流 */
  const handleDelete = async () => {
    if (!selectedWorkflow) return
    if (!confirm(`确认删除工作流 "${selectedWorkflow.name}"？`)) return
    try {
      await deleteWorkflow(selectedWorkflow.id)
      setSelectedWorkflow(null)
      setSteps([])
      setWorkflowName('')
      setWorkflowDescription('')
      await loadWorkflows()
      appLogger.info({ event: 'workflow_deleted', module: 'workflow', message: '工作流删除成功', extra: { id: selectedWorkflow.id } })
    } catch (err) {
      appLogger.error({ event: 'workflow_delete_failed', module: 'workflow', message: '删除工作流失败', extra: { error: String(err) } })
      setError(getErrorMessage(err, '删除工作流失败'))
    }
  }

  /** JSON 预览内容 */
  const jsonPreview = useMemo(() => {
    return JSON.stringify({
      name: workflowName,
      description: workflowDescription,
      steps,
    }, null, 2)
  }, [workflowName, workflowDescription, steps])

  /** 图视图：从 steps 计算节点与边（含 dagre 布局） */
  const computedGraph = useMemo(() => stepsToGraph(steps), [steps])

  /** reactflow 节点/边状态（允许拖拽，steps 变更时同步） */
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<WorkflowNodeData>(computedGraph.nodes)
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<WorkflowEdgeData>(computedGraph.edges)

  useEffect(() => {
    setRfNodes(computedGraph.nodes)
    setRfEdges(computedGraph.edges)
  }, [computedGraph, setRfNodes, setRfEdges])

  /** 图视图节点双击：打开 StepEditor 编辑步骤属性 */
  const handleNodeDoubleClick = useCallback((_event: unknown, node: Node<WorkflowNodeData>) => {
    /* 引用占位节点不可编辑 */
    if (node.data.isReference) return
    const found = findStepById(steps, node.id)
    if (found) {
      setEditingStep(found)
      setEditingIndex(-1)
      setEditingFromGraph(true)
    }
  }, [steps])

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <WorkflowIcon size={24} />
          <h1>工作流引擎</h1>
        </div>
        <div className={styles.headerActions}>
          <Button variant="ghost" onClick={loadWorkflows} disabled={isLoading}>
            <RefreshCw size={16} className={isLoading ? styles.spinning : undefined} />
            刷新
          </Button>
          <Button variant="ghost" onClick={handleNewWorkflow}>
            <Plus size={16} />
            新建
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            disabled={isSaving || !workflowName.trim() || steps.length === 0}
          >
            <Save size={16} />
            {isSaving ? '保存中...' : '保存'}
          </Button>
          {selectedWorkflow && (
            <>
              <Button
                variant="secondary"
                onClick={handleExecute}
                disabled={isExecuting}
              >
                <Play size={16} />
                {isExecuting ? '执行中...' : '执行'}
              </Button>
              <Button variant="danger" onClick={handleDelete}>
                <Trash2 size={16} />
              </Button>
            </>
          )}
        </div>
      </header>

      {error && (
        <div className={styles.errorBanner}>
          {error}
          <button onClick={() => setError(null)} aria-label="关闭">
            <X size={16} />
          </button>
        </div>
      )}

      <div className={styles.mainLayout}>
        {/* 左侧：工作流列表 */}
        <aside className={styles.sidebar}>
          <h2 className={styles.sidebarTitle}>工作流列表</h2>
          {workflows.length === 0 ? (
            <EmptyState
              title="暂无工作流"
              description="点击右上角新建按钮创建"
            />
          ) : (
            <ul className={styles.workflowList}>
              {workflows.map(wf => (
                <li key={wf.id}>
                  <button
                    className={`${styles.workflowItem} ${selectedWorkflow?.id === wf.id ? styles.active : ''}`}
                    onClick={() => handleSelectWorkflow(wf)}
                  >
                    <div className={styles.workflowItemName}>{wf.name}</div>
                    {wf.description && (
                      <div className={styles.workflowItemDesc}>{wf.description}</div>
                    )}
                    <div className={styles.workflowItemMeta}>
                      <span>{wf.definition?.steps?.length || 0} 步骤</span>
                      {wf.enabled ? (
                        <Badge variant="success" text="启用" />
                      ) : (
                        <Badge variant="error" text="禁用" />
                      )}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {/* 右侧：编辑区 */}
        <main className={styles.editor}>
          <div className={styles.editorHeader}>
            <div className={styles.editorHeaderLeft}>
              <Input
                value={workflowName}
                onChange={e => setWorkflowName(e.target.value)}
                placeholder="工作流名称"
                className={styles.nameInput}
              />
              <div className={styles.viewToggle}>
                <button
                  className={viewMode === 'visual' ? styles.toggleActive : ''}
                  onClick={() => setViewMode('visual')}
                  aria-label="可视化视图"
                >
                  <Eye size={16} />
                </button>
                <button
                  className={viewMode === 'graph' ? styles.toggleActive : ''}
                  onClick={() => setViewMode('graph')}
                  aria-label="图视图"
                >
                  <Network size={16} />
                </button>
                <button
                  className={viewMode === 'json' ? styles.toggleActive : ''}
                  onClick={() => setViewMode('json')}
                  aria-label="JSON 视图"
                >
                  <Code size={16} />
                </button>
              </div>
            </div>
          </div>

          <div className={styles.editorBody}>
            <div className={styles.formRow}>
              <label className={styles.formLabel}>描述</label>
              <Input
                value={workflowDescription}
                onChange={e => setWorkflowDescription(e.target.value)}
                placeholder="工作流描述（可选）"
              />
            </div>

            {viewMode === 'visual' && (
              <>
                <div className={styles.stepsHeader}>
                  <h3>步骤列表 ({steps.length})</h3>
                  <Button variant="secondary" onClick={() => setShowAddStep(true)}>
                    <Plus size={16} />
                    添加步骤
                  </Button>
                </div>

                {steps.length === 0 ? (
                  <EmptyState
                    title="暂无步骤"
                    description="点击添加步骤按钮开始构建工作流"
                  />
                ) : (
                  <div className={styles.stepsList}>
                    {steps.map((step, index) => (
                      <StepCard
                        key={step.id + index}
                        step={step}
                        index={index}
                        total={steps.length}
                        onEdit={() => {
                          setEditingStep(step)
                          setEditingIndex(index)
                        }}
                        onDelete={() => handleDeleteStep(index)}
                        onMoveUp={() => handleMoveStep(index, 'up')}
                        onMoveDown={() => handleMoveStep(index, 'down')}
                      />
                    ))}
                  </div>
                )}
              </>
            )}

            {viewMode === 'graph' && (
              <div className={styles.graphContainer}>
                {steps.length === 0 ? (
                  <EmptyState
                    title="暂无步骤"
                    description="切换到可视化视图添加步骤后查看图结构"
                  />
                ) : (
                  <ReactFlow
                    nodes={rfNodes}
                    edges={rfEdges as Edge[]}
                    nodeTypes={nodeTypes}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onNodeDoubleClick={handleNodeDoubleClick}
                    fitView
                    minZoom={0.2}
                    maxZoom={2}
                  >
                    <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
                    <Controls />
                  </ReactFlow>
                )}
              </div>
            )}

            {viewMode === 'json' && (
              <div className={styles.jsonPreview}>
                <Textarea
                  value={jsonPreview}
                  readOnly
                  rows={20}
                  className={styles.jsonTextarea}
                />
              </div>
            )}
          </div>

          {executionResult && (
            <div className={styles.executionResult}>
              <div className={styles.executionResultHeader}>
                <h3>执行结果</h3>
                <Badge
                  variant={executionResult.status === 'completed' ? 'success' : 'error'}
                  text={executionResult.status === 'completed' ? '成功' : '失败'}
                />
              </div>
              {executionResult.error && (
                <div className={styles.executionError}>{executionResult.error}</div>
              )}
              {executionResult.steps && (
                <div className={styles.executionSteps}>
                  {executionResult.steps.map((step, i) => (
                    <div key={i} className={styles.executionStep}>
                      <Badge
                        variant={(step.success as boolean) ? 'success' : 'error'}
                        text={(step.success as boolean) ? '成功' : '失败'}
                      />
                      <span>{String(step.step_id || step.id || `步骤 ${i + 1}`)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      {/* 添加步骤弹窗 */}
      <Modal
        open={showAddStep}
        onClose={() => setShowAddStep(false)}
        title="选择步骤类型"
      >
        <div className={styles.stepTypeGrid}>
          {(Object.keys(STEP_TYPE_META) as WorkflowStepType[]).map(type => {
            const meta = STEP_TYPE_META[type]
            return (
              <button
                key={type}
                className={styles.stepTypeCard}
                onClick={() => handleAddStep(type)}
              >
                <Badge variant={meta.variant} text={meta.label} />
                <p>{meta.description}</p>
              </button>
            )
          })}
        </div>
      </Modal>

      {/* 步骤编辑器弹窗 */}
      {editingStep && (
        <Modal
          open={true}
          onClose={() => {
            setEditingStep(null)
            setEditingIndex(-1)
            setEditingFromGraph(false)
          }}
          title="编辑步骤"
        >
          <StepEditor
            step={editingStep}
            onChange={handleUpdateStep}
            onCancel={() => {
              setEditingStep(null)
              setEditingIndex(-1)
              setEditingFromGraph(false)
            }}
          />
        </Modal>
      )}
    </div>
  )
}
