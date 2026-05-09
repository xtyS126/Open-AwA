# Checklist: 连续工具调用前端显示增强

## 类型定义完整性
- [ ] `ToolEventMeta` 包含 input/output/startedAt/completedAt/sequence 字段定义
- [ ] `ChatMessage` 包含 toolEvents 可选字段定义
- [ ] `AssistantExecutionMeta` 包含 totalDuration 可选字段定义
- [ ] 所有新增字段使用正确的 TypeScript 可选类型标记

## InlineToolCallCard 组件
- [ ] 单工具调用时卡片正确渲染（名称、状态、入口）
- [ ] 多工具调用时卡片按 sequence 排序
- [ ] running 状态徽章有脉冲动画
- [ ] completed 状态左侧边框为绿色
- [ ] error 状态左侧边框为红色，显示错误信息
- [ ] 输入参数区域可折叠/展开
- [ ] 输出结果区域可折叠/展开
- [ ] 输入展开后 JSON 语法高亮正确
- [ ] 输出展开后 JSON 语法高亮正确
- [ ] 卡片入场有滑入动画

## ToolParamViewer 组件
- [ ] 基础 JSON 正确语法高亮渲染
- [ ] 嵌套对象层级 > 2 默认折叠
- [ ] 嵌套数组层级 > 2 默认折叠
- [ ] 长字符串（> 200 字符）自动截断，有展开按钮
- [ ] 复制按钮可复制 JSON 文本到剪贴板
- [ ] 样式与当前主题兼容

## ChatMessage 渲染流程
- [ ] assistant 消息按新顺序渲染（ReasoningContent → 卡片 → MessageContent → 详情面板）
- [ ] user 消息渲染不受影响
- [ ] 无工具调用的 assistant 消息正常渲染（不显示空卡片区域）
- [ ] 时间线连接线在卡片间正确显示
- [ ] 时间线连接线 CSS 正确

## 时间线可视化
- [ ] AssistantExecutionDetails 面板以时间线样式展示
- [ ] 各步骤显示对应图标（根据 StepType）
- [ ] 各步骤显示状态标签和耗时
- [ ] pending → running 有渐入脉冲动画
- [ ] running → completed 有打勾滑入动画
- [ ] running → error 有抖动动画
- [ ] 总耗时统计条正确计算和显示

## 流式事件处理
- [ ] tool 事件 input 字段正确写入 messageMeta
- [ ] tool 事件自动计算 sequence 序号
- [ ] result 事件 output 字段更新到对应 toolEvent
- [ ] 流结束时 toolEvents 同步到 ChatMessage 对象

## 持久化
- [ ] 页面刷新后历史消息的工具调用信息恢复显示
- [ ] 消息缓存保存 toolEvents 字段
- [ ] 消息缓存加载恢复 toolEvents 字段

## 构建验证
- [ ] `npm run build` 构建成功，无错误
- [ ] `npm run typecheck` 类型检查通过
- [ ] ESLint 无新增警告或错误
- [ ] 无 console.log 残留
- [ ] 无 TODO/FIXME 残留

## 兼容性
- [ ] 直接模式（非流式）下工具调用正常显示
- [ ] 流式模式下工具调用实时更新正常
- [ ] 历史会话（无 toolEvents 字段的旧消息）正常显示不报错
- [ ] 浮动面板（renderFloatingExecutionPanel）功能保持不变
