/**
 * 工作流图转换工具：在 WorkflowStep 数组与 reactflow 节点/边之间双向转换。
 * 使用 dagre 自动布局算法计算节点坐标。
 * 支持 6 种步骤类型：tool/skill/plugin/condition/parallel/sub_workflow。
 */
import dagre from '@dagrejs/dagre'
import type { Edge, Node } from 'reactflow'

import type { WorkflowStep, WorkflowStepType } from '@/shared/api/workflowApi'

/** 步骤类型扩展：包含引用占位类型 */
type GraphStepType = WorkflowStepType | 'reference'

/** 工作流节点数据：携带原始步骤与显示信息 */
export interface WorkflowNodeData {
  /** 原始步骤对象（引用占位节点时为触发引用的 sub_workflow 步骤） */
  step: WorkflowStep
  /** 是否为 sub_workflow 引用占位节点 */
  isReference?: boolean
  /** 引用工作流名称（仅 isReference=true 时有效） */
  referenceName?: string
  /** 节点显示标题 */
  title: string
  /** 步骤类型（含 reference 占位） */
  stepType: GraphStepType
  [key: string]: unknown
}

/** 工作流边数据：描述节点间关系类型 */
export interface WorkflowEdgeData {
  /** 关系类型：顺序/条件真/条件假/并行分支/子工作流引用 */
  relationship: 'sequential' | 'condition_true' | 'condition_false' | 'parallel_branch' | 'sub_workflow_ref'
  /** 分支索引（仅 parallel_branch 时有效） */
  branchIndex?: number
  [key: string]: unknown
}

/** 步骤类型对应的节点颜色（左边框 + 头部背景） */
export const STEP_TYPE_COLORS: Record<GraphStepType, string> = {
  tool: '#3b82f6',          // 蓝色 - 工具
  skill: '#10b981',         // 绿色 - 技能
  plugin: '#8b5cf6',        // 紫色 - 插件
  condition: '#f59e0b',     // 橙色 - 条件
  parallel: '#06b6d4',      // 青色 - 并行
  sub_workflow: '#ec4899',  // 粉色 - 子工作流
  reference: '#9ca3af',     // 灰色 - 引用占位
}

/** dagre 布局方向 */
const LAYOUT_RANK_DIR = 'TB' as const

/** dagre 布局参数：同层节点间距 */
const LAYOUT_NODE_SEP = 50

/** dagre 布局参数：层间距 */
const LAYOUT_RANK_SEP = 80

/** 节点宽度（用于 dagre 布局计算） */
const NODE_WIDTH = 180

/** 节点高度（用于 dagre 布局计算） */
const NODE_HEIGHT = 64

/**
 * 生成 sub_workflow 引用占位节点的唯一 ID。
 * @param referenceName 引用工作流名称
 * @param parentId 父步骤 ID
 */
function generateReferenceId(referenceName: string, parentId: string): string {
  const safeName = referenceName.replace(/[^a-zA-Z0-9_]/g, '_')
  return `ref__${parentId}__${safeName}`
}

/** 获取步骤显示标题：优先 name，回退 id */
function getStepTitle(step: WorkflowStep): string {
  return step.name || step.id
}

/**
 * 递归构建图节点与边。
 * 顺序步骤之间用无标签边连接；
 * condition 步骤用 true/false 标签边连接 on_true/on_false 子步骤；
 * parallel 步骤用 branch_N 标签边连接各分支；
 * sub_workflow 步骤用引用名标签边连接占位节点。
 * @param steps 步骤数组（顺序执行）
 * @param nodes 累积节点列表
 * @param edges 累积边列表
 */
function buildGraphRecursive(
  steps: WorkflowStep[],
  nodes: Node<WorkflowNodeData>[],
  edges: Edge<WorkflowEdgeData>[],
): void {
  if (steps.length === 0) return

  /* 为每个步骤创建节点 */
  for (const step of steps) {
    nodes.push({
      id: step.id,
      position: { x: 0, y: 0 },
      data: {
        step,
        title: getStepTitle(step),
        stepType: step.type,
      },
      type: 'workflowNode',
    })
  }

  /* 顺序步骤之间连边（无标签） */
  for (let i = 0; i < steps.length - 1; i++) {
    edges.push({
      id: `e__${steps[i].id}__${steps[i + 1].id}`,
      source: steps[i].id,
      target: steps[i + 1].id,
      type: 'smoothstep',
      data: { relationship: 'sequential' },
    })
  }

  /* 处理嵌套步骤 */
  for (const step of steps) {
    if (step.type === 'condition') {
      /* condition 步骤连 on_true 子步骤（边标签 true） */
      if (step.on_true && step.on_true.length > 0) {
        edges.push({
          id: `e__${step.id}__${step.on_true[0].id}`,
          source: step.id,
          target: step.on_true[0].id,
          type: 'smoothstep',
          label: 'true',
          data: { relationship: 'condition_true' },
        })
        buildGraphRecursive(step.on_true, nodes, edges)
      }
      /* condition 步骤连 on_false 子步骤（边标签 false） */
      if (step.on_false && step.on_false.length > 0) {
        edges.push({
          id: `e__${step.id}__${step.on_false[0].id}`,
          source: step.id,
          target: step.on_false[0].id,
          type: 'smoothstep',
          label: 'false',
          data: { relationship: 'condition_false' },
        })
        buildGraphRecursive(step.on_false, nodes, edges)
      }
    } else if (step.type === 'parallel' && step.branches) {
      /* parallel 步骤连各 branch（边标签为 branch_N） */
      step.branches.forEach((branch, index) => {
        if (branch.length > 0) {
          edges.push({
            id: `e__${step.id}__${branch[0].id}`,
            source: step.id,
            target: branch[0].id,
            type: 'smoothstep',
            label: `branch_${index}`,
            data: { relationship: 'parallel_branch', branchIndex: index },
          })
          buildGraphRecursive(branch, nodes, edges)
        }
      })
    } else if (step.type === 'sub_workflow') {
      /* sub_workflow 步骤连引用工作流占位节点（边标签为引用名） */
      const referenceName = step.workflow_name || `#${step.workflow_id ?? '?'}`
      const referenceId = generateReferenceId(referenceName, step.id)
      nodes.push({
        id: referenceId,
        position: { x: 0, y: 0 },
        data: {
          step,
          isReference: true,
          referenceName,
          title: referenceName,
          stepType: 'reference',
        },
        type: 'workflowNode',
      })
      edges.push({
        id: `e__${step.id}__${referenceId}`,
        source: step.id,
        target: referenceId,
        type: 'smoothstep',
        label: referenceName,
        data: { relationship: 'sub_workflow_ref' },
      })
    }
  }
}

/**
 * 使用 dagre 自动布局算法计算节点坐标。
 * 就地修改传入节点的 position 字段。
 * @param nodes 节点列表
 * @param edges 边列表
 */
function applyDagreLayout(
  nodes: Node<WorkflowNodeData>[],
  edges: Edge<WorkflowEdgeData>[],
): void {
  const graph = new dagre.graphlib.Graph()
  graph.setGraph({
    rankdir: LAYOUT_RANK_DIR,
    nodesep: LAYOUT_NODE_SEP,
    ranksep: LAYOUT_RANK_SEP,
  })
  graph.setDefaultEdgeLabel(() => ({}))

  for (const node of nodes) {
    graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  }
  for (const edge of edges) {
    graph.setEdge(edge.source, edge.target)
  }

  dagre.layout(graph)

  /* dagre 返回中心点坐标，reactflow 需要左上角坐标 */
  for (const node of nodes) {
    const layoutNode = graph.node(node.id)
    if (layoutNode) {
      node.position = {
        x: layoutNode.x - NODE_WIDTH / 2,
        y: layoutNode.y - NODE_HEIGHT / 2,
      }
    }
  }
}

/**
 * 将步骤数组转换为 reactflow 节点与边，并使用 dagre 计算布局。
 * @param steps 工作流步骤数组
 * @returns 包含 nodes 和 edges 的对象
 */
export function stepsToGraph(
  steps: WorkflowStep[],
): { nodes: Node<WorkflowNodeData>[]; edges: Edge<WorkflowEdgeData>[] } {
  const nodes: Node<WorkflowNodeData>[] = []
  const edges: Edge<WorkflowEdgeData>[] = []
  buildGraphRecursive(steps, nodes, edges)
  applyDagreLayout(nodes, edges)
  return { nodes, edges }
}

/**
 * 从指定节点开始，沿顺序边构建步骤链，并递归处理嵌套步骤。
 * @param startNodeId 起始节点 ID
 * @param nodeMap 节点 ID 到节点的映射（已排除引用占位节点）
 * @param outgoingEdges 节点 ID 到出边列表的映射
 * @param visited 已访问节点 ID 集合（防止循环）
 * @returns 步骤数组
 */
function buildChainFromNode(
  startNodeId: string,
  nodeMap: Map<string, Node<WorkflowNodeData>>,
  outgoingEdges: Map<string, Edge<WorkflowEdgeData>[]>,
  visited: Set<string>,
): WorkflowStep[] {
  const chain: WorkflowStep[] = []
  let currentId: string | null = startNodeId

  while (currentId !== null) {
    if (visited.has(currentId)) break
    visited.add(currentId)

    const node = nodeMap.get(currentId)
    if (!node) break

    /* 浅拷贝步骤，避免修改原始数据 */
    const step: WorkflowStep = { ...node.data.step }
    const outEdges: Edge<WorkflowEdgeData>[] = outgoingEdges.get(currentId) ?? []

    /* 处理嵌套步骤 */
    if (step.type === 'condition') {
      const trueEdge = outEdges.find((e: Edge<WorkflowEdgeData>) => e.data?.relationship === 'condition_true')
      const falseEdge = outEdges.find((e: Edge<WorkflowEdgeData>) => e.data?.relationship === 'condition_false')
      step.on_true = trueEdge
        ? buildChainFromNode(trueEdge.target, nodeMap, outgoingEdges, visited)
        : []
      step.on_false = falseEdge
        ? buildChainFromNode(falseEdge.target, nodeMap, outgoingEdges, visited)
        : []
    } else if (step.type === 'parallel') {
      const branchEdges = outEdges
        .filter((e: Edge<WorkflowEdgeData>) => e.data?.relationship === 'parallel_branch')
        .sort((a: Edge<WorkflowEdgeData>, b: Edge<WorkflowEdgeData>) => (a.data?.branchIndex ?? 0) - (b.data?.branchIndex ?? 0))
      step.branches = branchEdges.map(
        (e: Edge<WorkflowEdgeData>) => buildChainFromNode(e.target, nodeMap, outgoingEdges, visited),
      )
    }

    chain.push(step)

    /* 查找下一个顺序节点 */
    const seqEdge = outEdges.find((e: Edge<WorkflowEdgeData>) => e.data?.relationship === 'sequential')
    currentId = seqEdge ? seqEdge.target : null
  }

  return chain
}

/**
 * 将 reactflow 节点与边反向转换为步骤数组。
 * 引用占位节点会被排除；嵌套步骤根据边的关系类型重建。
 * @param nodes reactflow 节点列表
 * @param edges reactflow 边列表
 * @returns 工作流步骤数组
 */
export function graphToSteps(
  nodes: Node<WorkflowNodeData>[],
  edges: Edge<WorkflowEdgeData>[],
): WorkflowStep[] {
  /* 构建节点映射（排除引用占位节点） */
  const nodeMap = new Map<string, Node<WorkflowNodeData>>()
  for (const node of nodes) {
    if (!node.data.isReference) {
      nodeMap.set(node.id, node)
    }
  }

  /* 构建出边映射 */
  const outgoingEdges = new Map<string, Edge<WorkflowEdgeData>[]>()
  for (const edge of edges) {
    const list: Edge<WorkflowEdgeData>[] = outgoingEdges.get(edge.source) ?? []
    list.push(edge)
    outgoingEdges.set(edge.source, list)
  }

  /* 构建入边目标集合（仅非引用节点） */
  const incomingTargets = new Set<string>()
  for (const edge of edges) {
    if (nodeMap.has(edge.target)) {
      incomingTargets.add(edge.target)
    }
  }

  /* 根节点：没有入边的非引用节点 */
  const rootNodes = nodes
    .filter(n => !n.data.isReference && !incomingTargets.has(n.id))
    .sort((a, b) => {
      /* 按位置排序：先上后下，先左后右，保持确定性顺序 */
      if (Math.abs(a.position.y - b.position.y) > 5) {
        return a.position.y - b.position.y
      }
      return a.position.x - b.position.x
    })

  /* 从每个根节点出发构建步骤链 */
  const visited = new Set<string>()
  const steps: WorkflowStep[] = []
  for (const root of rootNodes) {
    const chain = buildChainFromNode(root.id, nodeMap, outgoingEdges, visited)
    steps.push(...chain)
  }

  return steps
}

/**
 * 在步骤树中按 ID 查找步骤。
 * 递归搜索 condition 的 on_true/on_false 和 parallel 的 branches。
 * @param steps 步骤数组
 * @param stepId 目标步骤 ID
 * @returns 找到的步骤，未找到返回 null
 */
export function findStepById(
  steps: WorkflowStep[],
  stepId: string,
): WorkflowStep | null {
  for (const step of steps) {
    if (step.id === stepId) return step
    if (step.type === 'condition') {
      if (step.on_true) {
        const found = findStepById(step.on_true, stepId)
        if (found) return found
      }
      if (step.on_false) {
        const found = findStepById(step.on_false, stepId)
        if (found) return found
      }
    } else if (step.type === 'parallel' && step.branches) {
      for (const branch of step.branches) {
        const found = findStepById(branch, stepId)
        if (found) return found
      }
    }
  }
  return null
}

/**
 * 在步骤树中按 ID 更新步骤（返回新树，不修改原数组）。
 * 递归搜索 condition 的 on_true/on_false 和 parallel 的 branches。
 * @param steps 原步骤数组
 * @param stepId 目标步骤 ID
 * @param updated 更新后的步骤
 * @returns 新步骤数组
 */
export function updateStepInTree(
  steps: WorkflowStep[],
  stepId: string,
  updated: WorkflowStep,
): WorkflowStep[] {
  return steps.map(step => {
    if (step.id === stepId) {
      return updated
    }
    if (step.type === 'condition') {
      return {
        ...step,
        on_true: step.on_true ? updateStepInTree(step.on_true, stepId, updated) : step.on_true,
        on_false: step.on_false ? updateStepInTree(step.on_false, stepId, updated) : step.on_false,
      }
    }
    if (step.type === 'parallel' && step.branches) {
      return {
        ...step,
        branches: step.branches.map(b => updateStepInTree(b, stepId, updated)),
      }
    }
    return step
  })
}
