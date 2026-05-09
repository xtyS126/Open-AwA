# 连续工具调用前端显示增强 Spec

## Why
当前工具调用显示采用浮动面板 + 底部折叠面板模式，与 DeepSeek、Kimi、Claude 等主流产品采用的"内联工具卡片 + 时间线 + 流式参数预览"模式差距较大。用户无法在消息文本之间看到工具调用的参数和执行结果，也无法直观感知多步连续工具调用的时序关系。

## What Changes
- 新增 `InlineToolCallCard` 组件，在消息文本之间嵌入工具调用卡片
- 新增 `ToolParamViewer` 组件，提供 JSON 语法高亮的参数/结果查看
- 改造 `ChatMessage` 渲染顺序：推理内容 → 内联工具卡片 → 消息文本 → 执行详情面板
- 增强 `AssistantExecutionDetails` 时间线可视化 + 状态切换动画
- 扩展 `ToolEventMeta` 类型，新增 input/output/sequence/startedAt/completedAt 字段
- 扩展 `ChatMessage` 类型，新增 toolEvents 持久化字段
- 增强 `ChatPage` 流式事件处理，支持 tool 事件携带 input/output
- 增强 CSS 动画：脉冲运行态、卡片滑入、时间线连线生长、完成打勾
- 工具元数据持久化到消息对象，页面刷新后不丢失

## Impact
- Affected specs: 无现有 spec 被修改
- Affected code:
  - `frontend/src/features/chat/types.ts` — 类型扩展
  - `frontend/src/features/chat/utils/executionMeta.ts` — applyToolUpdate 增强
  - `frontend/src/features/chat/components/ChatMessage.tsx` — 渲染流程改造
  - `frontend/src/features/chat/components/AssistantExecutionDetails.tsx` — 时间线增强
  - `frontend/src/features/chat/components/AssistantExecutionDetails.module.css` — 动画增强
  - `frontend/src/features/chat/ChatPage.tsx` — 事件处理增强
  - `frontend/src/features/chat/ChatPage.module.css` — 全局动画
  - `frontend/src/features/chat/store/chatStore.ts` — 持久化支持
  - 新增文件:
    - `frontend/src/features/chat/components/InlineToolCallCard.tsx`
    - `frontend/src/features/chat/components/InlineToolCallCard.module.css`
    - `frontend/src/features/chat/components/ToolParamViewer.tsx`
    - `frontend/src/features/chat/components/ToolParamViewer.module.css`

## ADDED Requirements

### Requirement: 内联工具调用卡片
系统 SHALL 在 assistant 消息的文本内容之间显示工具调用卡片，卡片展示工具名称、状态、输入参数和执行结果。

#### Scenario: 单个工具调用显示
- **WHEN** AI 回复中包含一次工具调用
- **THEN** 消息内容中嵌入一张工具调用卡片，显示工具名称和运行状态

#### Scenario: 多个连续工具调用显示
- **WHEN** AI 回复中包含多次连续工具调用（如搜索→读网页→分析）
- **THEN** 消息内容中按序嵌入多张工具调用卡片，卡片间通过时间线连接线相连

#### Scenario: 工具调用流式更新
- **WHEN** 工具调用从 running 变为 completed
- **THEN** 卡片状态徽章从脉冲动画切换为完成状态，对应输入/输出区域显示完整内容

#### Scenario: 工具调用失败
- **WHEN** 工具调用状态变为 error
- **THEN** 卡片左侧边框变为红色，显示错误详情

### Requirement: 工具参数/结果 JSON 查看器
系统 SHALL 提供可展开的 JSON 语法高亮查看器，用于展示工具调用的输入参数和执行结果。

#### Scenario: JSON 参数展开
- **WHEN** 用户点击工具卡片中的"输入参数"区域
- **THEN** 展开显示语法高亮的 JSON 内容

#### Scenario: 深层嵌套展开
- **WHEN** JSON 内容包含嵌套对象或数组且层级超过 2 层
- **THEN** 嵌套节点默认折叠，可逐层展开

#### Scenario: 长字符串截断
- **WHEN** JSON 中字符串值超过 200 字符
- **THEN** 自动截断显示，末尾显示"展开"按钮

### Requirement: 工具调用时间线可视化
系统 SHALL 在 AssistantExecutionDetails 面板中以时间线样式展示工具调用步骤，包含竖线连接、状态节点和执行耗时。

#### Scenario: 时间线节点渲染
- **WHEN** AssistantExecutionDetails 面板展开
- **THEN** 工具调用步骤以时间线样式渲染，左侧竖线连接各节点，每个节点显示步骤图标、名称、状态、耗时

#### Scenario: 状态切换动画
- **WHEN** 步骤从 pending 变为 running
- **THEN** 节点背景渐入 + 边框脉冲动画
- **WHEN** 步骤从 running 变为 completed
- **THEN** 绿色对勾滑入动画
- **WHEN** 步骤从 running 变为 error
- **THEN** 红色抖动动画

### Requirement: 工具元数据持久化
系统 SHALL 将工具调用元数据（toolEvents）与消息对象关联存储，确保页面刷新后重新加载时工具调用信息不丢失。

#### Scenario: 页面刷新恢复
- **WHEN** 用户刷新页面并重新加载历史消息
- **THEN** 已完成的工具调用卡片和时间线信息仍可见

#### Scenario: 流结束持久化
- **WHEN** SSE 流结束（收到 usage 或 stream complete 事件）
- **THEN** 当前 messageMeta 中的 toolEvents 同步写入对应 ChatMessage 对象的 toolEvents 字段

### Requirement: CSS 动画效果
系统 SHALL 为工具调用卡片和状态节点提供平滑的 CSS 动画效果。

#### Scenario: 卡片入场动画
- **WHEN** 新增工具调用显示
- **THEN** 卡片从下方 8px 滑入 + 透明渐显（0.3s ease-out）

#### Scenario: 运行态脉冲
- **WHEN** 工具处于 running 状态
- **THEN** 状态徽章持续脉冲动画（1s 循环，透明度 1→0.5→1）

#### Scenario: 时间线连线生长
- **WHEN** 新增工具调用节点
- **THEN** 上方连接线从 0 高度生长到完整高度（0.3s ease-out）

## MODIFIED Requirements

### Requirement: ChatMessage 渲染流程
系统 SHALL 按以下顺序渲染 assistant 消息内容：推理内容（ReasoningContent）→ 内联工具调用卡片（InlineToolCallCard[]）→ 消息文本（MessageContent）→ 执行详情面板（AssistantExecutionDetails）。

### Requirement: ToolEventMeta 类型
系统 SHALL 扩展 ToolEventMeta 接口，新增 input（Record<string, unknown>）、output（unknown）、startedAt（number）、completedAt（number）、sequence（number）字段。

### Requirement: ChatMessage 类型
系统 SHALL 扩展 ChatMessage 接口，新增 toolEvents（ToolEventMeta[]）可选字段，用于持久化存储工具调用信息。

### Requirement: ChatPage 流式事件处理
系统 SHALL 在收到 type === 'tool' 事件时，将 input 字段和 sequence 序号一并应用到 messageMeta。在收到 type === 'result' 事件时，将 output 字段更新到对应 toolEvent。

## REMOVED Requirements
无移除的需求。
