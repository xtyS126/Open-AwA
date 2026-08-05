/**
 * SubAgent 图转换工具：在 GraphDefinitionSchema 与 reactflow 节点/边之间转换。
 * 使用 dagre 自动布局算法计算节点坐标。
 * 按 agent 字段着色区分节点类型，边携带 condition 标签。
 */
import dagre from '@dagrejs/dagre'
import type { Edge, Node } from 'reactflow'

import type {
  GraphDefinitionSchema,
  GraphNodeSchema,
  GraphEdgeSchema,
} from '@/shared/api/subagentsApi'

/** SubAgent 节点数据：携带原始节点与显示信息 */
export interface SubagentNodeData {
  /** 原始节点对象 */
  node: GraphNodeSchema
  /** 节点在 editGraph.nodes 中的索引（用于编辑定位） */
  index: number
  /** 节点显示标题 */
  title: string
  /** Agent 名称（用于着色） */
  agent: string
  /** 是否为入口节点 */
  isEntryPoint: boolean
  /** 是否为终点节点 */
  isFinishPoint: boolean
  [key: string]: unknown
}

/** SubAgent 边数据：携带原始边与索引 */
export interface SubagentEdgeData {
  /** 原始边对象 */
  edge: GraphEdgeSchema
  /** 边在 editGraph.edges 中的索引 */
  index: number
  [key: string]: unknown
}

/** Agent 颜色调色板（按 agent 名称哈希分配，相同 agent 返回相同颜色） */
const AGENT_COLOR_PALETTE = [
  '#0d9488', // 蓝色
  '#10b981', // 绿色
  '#8b5cf6', // 紫色
  '#f59e0b', // 橙色
  '#06b6d4', // 青色
  '#ec4899', // 粉色
  '#ef4444', // 红色
  '#84cc16', // 黄绿色
]

/** 未指定 Agent 时的默认颜色 */
const DEFAULT_AGENT_COLOR = '#9ca3af'

/** dagre 布局方向：自上而下 */
const LAYOUT_RANK_DIR = 'TB' as const

/** dagre 布局参数：同层节点间距 */
const LAYOUT_NODE_SEP = 50

/** dagre 布局参数：层间距 */
const LAYOUT_RANK_SEP = 80

/** 节点宽度（用于 dagre 布局计算） */
const NODE_WIDTH = 180

/** 节点高度（用于 dagre 布局计算） */
const NODE_HEIGHT = 72

/**
 * 根据 Agent 名称生成稳定的颜色。
 * 相同 Agent 名称始终返回相同颜色，空名称返回默认灰色。
 * @param agentName Agent 名称
 */
export function getAgentColor(agentName: string): string {
  if (!agentName) return DEFAULT_AGENT_COLOR
  let hash = 0
  for (let i = 0; i < agentName.length; i++) {
    hash = (hash * 31 + agentName.charCodeAt(i)) >>> 0
  }
  return AGENT_COLOR_PALETTE[hash % AGENT_COLOR_PALETTE.length]
}

/**
 * 使用 dagre 自动布局算法计算节点坐标。
 * 就地修改传入节点的 position 字段。
 * @param nodes 节点列表
 * @param edges 边列表
 */
function applyDagreLayout(
  nodes: Node<SubagentNodeData>[],
  edges: Edge<SubagentEdgeData>[],
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
    if (edge.source && edge.target) {
      graph.setEdge(edge.source, edge.target)
    }
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
 * 将图定义转换为 reactflow 节点与边，并使用 dagre 计算布局。
 * 节点按 agent 字段着色；边携带 condition 标签。
 * 节点 ID 使用节点 name（图定义中 name 为唯一标识）。
 * @param graph 图定义
 * @returns 包含 nodes 和 edges 的对象
 */
export function graphDefinitionToFlow(
  graph: GraphDefinitionSchema,
): { nodes: Node<SubagentNodeData>[]; edges: Edge<SubagentEdgeData>[] } {
  const nodes: Node<SubagentNodeData>[] = graph.nodes.map((node, index) => ({
    id: node.name,
    position: { x: 0, y: 0 },
    data: {
      node,
      index,
      title: node.name,
      agent: node.agent,
      isEntryPoint: graph.entry_point === node.name,
      isFinishPoint: graph.finish_points.includes(node.name),
    },
    type: 'subagentNode',
  }))

  const edges: Edge<SubagentEdgeData>[] = graph.edges
    .map((edge, index) => ({
      id: `e__${edge.source}__${edge.target}__${index}`,
      source: edge.source,
      target: edge.target,
      type: 'smoothstep',
      label: edge.condition || undefined,
      data: { edge, index },
    }))
    .filter(e => e.source && e.target)

  applyDagreLayout(nodes, edges)
  return { nodes, edges }
}
