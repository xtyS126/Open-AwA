# Tasks: 连续工具调用前端显示增强

- [ ] Task 1: 扩展类型定义
  - [ ] 扩展 `ToolEventMeta` 接口，新增 `input`、`output`、`startedAt`、`completedAt`、`sequence` 字段
  - [ ] 扩展 `ChatMessage` 接口，新增 `toolEvents?: ToolEventMeta[]` 字段
  - [ ] 扩展 `AssistantExecutionMeta` 接口，新增 `totalDuration?: number` 字段
  - [ ] 运行 `npm run typecheck` 确保类型无错误

- [ ] Task 2: 创建 `ToolParamViewer` 组件
  - [ ] 创建 `ToolParamViewer.tsx`，支持 JSON 语法高亮展示
  - [ ] 支持深层嵌套的折叠/展开（默认折叠 > 2 层）
  - [ ] 支持长字符串自动截断（> 200 字符）+ 展开按钮
  - [ ] 支持复制到剪贴板功能
  - [ ] 创建 `ToolParamViewer.module.css`，适配当前主题风格

- [ ] Task 3: 创建 `InlineToolCallCard` 组件
  - [ ] 创建 `InlineToolCallCard.tsx`，渲染工具调用卡片
  - [ ] 头部显示工具名称 + kind 标签 + 状态徽章（脉冲动画 running 态）
  - [ ] 左侧彩色边框指示状态（蓝=running，绿=completed，红=error）
  - [ ] 集成 `ToolParamViewer` 显示输入参数和输出结果
  - [ ] 输入/输出区域默认折叠，点击展开
  - [ ] 显示耗时信息（startedAt → completedAt）
  - [ ] 添加卡片滑入入场动画
  - [ ] 创建 `InlineToolCallCard.module.css`

- [ ] Task 4: 改造 `ChatMessage` 渲染流程
  - [ ] 修改 `ChatMessage.tsx`，引入 `InlineToolCallCard`
  - [ ] 按新顺序渲染：ReasoningContent → InlineToolCallCard[] → MessageContent → AssistantExecutionDetails
  - [ ] toolEvents 按 sequence 排序后渲染
  - [ ] 在卡片间添加时间线连接线（CSS 竖线）
  - [ ] 添加时间线相关 CSS 到 `ChatPage.module.css`

- [ ] Task 5: 增强 `AssistantExecutionDetails` 时间线可视化
  - [ ] 当前列表样式改为时间线样式（左侧竖线 + 节点）
  - [ ] 根据 StepType 显示不同图标
  - [ ] 添加总耗时统计条
  - [ ] 添加状态切换 CSS 动画（pending→running 渐入脉冲，running→completed 打勾滑入，running→error 抖动）
  - [ ] 更新 `AssistantExecutionDetails.module.css`

- [ ] Task 6: 增强 `ChatPage` 流式事件处理
  - [ ] 在 `handleSend` 的 `type === 'tool'` 处理中，提取 input 字段写入 messageMeta
  - [ ] 自动计算 sequence 序号
  - [ ] 在 `type === 'result'` 处理中，将 output 字段更新到对应 toolEvent
  - [ ] 在流结束（usage/stream complete）时，将 messageMeta.toolEvents 同步到消息对象实现持久化

- [ ] Task 7: 更新 `chatStore` 持久化支持
  - [ ] 在消息缓存读取/写入逻辑中保留 toolEvents 字段
  - [ ] 从缓存恢复消息时，用 message.toolEvents 初始化 messageMeta

- [ ] Task 8: 全局 CSS 动画与样式
  - [ ] 在 `ChatPage.module.css` 中添加：卡片滑入动画、脉冲动画、时间线连线动画
  - [ ] 在 `AssistantExecutionDetails.module.css` 中添加：节点动画、打勾滑入、抖动

- [ ] Task 9: 类型检查与构建验证
  - [ ] 运行 `npm run build` 确保构建成功
  - [ ] 运行 `npm run typecheck` 确保类型检查通过
  - [ ] 检查 ESLint 无新增错误

# Task Dependencies
- Task 2 依赖 Task 1（类型定义必须在组件创建前完成）
- Task 3 依赖 Task 2（InlineToolCallCard 使用 ToolParamViewer）
- Task 4 依赖 Task 1 和 Task 3（ChatMessage 改造需要新类型和新组件）
- Task 5 依赖 Task 1（时间线增强需要新类型字段）
- Task 6 依赖 Task 1（事件处理增强需要新类型字段）
- Task 7 依赖 Task 1 和 Task 6（持久化需在流结束逻辑就绪后进行）
- Task 8 可与 Task 3-5 并行进行
- Task 9 在所有任务完成后执行

# 可并行任务组
- Task 2 和 Task 5 可并行（互不依赖）
- Task 8 可与 Task 3/4/5 并行
