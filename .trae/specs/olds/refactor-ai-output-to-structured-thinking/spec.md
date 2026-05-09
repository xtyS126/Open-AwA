# 前端AI输出功能重构方案 (Structured Thinking Process)

## Why
当前的 AI 输出展示主要为扁平化的文本流式输出，缺乏对 AI 复杂内部推理逻辑、文件引用和任务执行步骤的结构化展示。参考目标图片中的 UI 设计，重构 AI 输出界面能够极大提升用户的交互体验，让用户清晰看到 AI 的“思考过程”、引用的上下文文件以及每个任务步骤的执行状态（如进行中、已完成），增加过程透明度。

## What Changes
- **新增思考过程容器 (Thinking Process)**: 将 AI 的推理过程封装在一个可折叠的 UI 块中。
- **文件引用展示组件 (File References)**: 提取 AI 提及的本地文件或参考文档，将其渲染为带有特定图标的标签/药丸(Pill)状组件。
- **任务执行追踪器 (Task Step Tracker)**:
  - 解析 AI 输出中的任务列表结构。
  - 渲染任务步骤及其状态图标（如绿色对勾代表已完成，Spinner代表进行中）。
  - 支持在任务步骤内部嵌套更细致的可折叠 "Thought" (思考) 模块。
- **流式状态提示 (Streaming Indicator)**: 在 AI 处于推理阶段时，底部展示动态的 "思考中 ..." 提示。
- **状态流式解析逻辑 (Stream Parser Update)**: 修改前端解析流式响应的逻辑，能够识别特定的 Markdown 语法或自定义标签（如 `<thought>`, `<step>`, `<file>` 等）并将其映射到对应的组件状态中。

## Impact
- Affected specs: 聊天输出展示、流式响应处理
- Affected code: 
  - `src/features/chat/components/ChatMessage.tsx` (主消息组件)
  - `src/features/chat/components/ThinkingProcess.tsx` (新增)
  - `src/features/chat/components/FileReference.tsx` (新增)
  - `src/features/chat/components/TaskTracker.tsx` (新增)
  - `src/features/chat/utils/streamParser.ts` (解析逻辑更新)

## ADDED Requirements
### Requirement: 结构化思考过程展示
系统应当能够捕获 AI 响应中的推理数据，并将其渲染为可折叠的“思考过程”面板。

#### Scenario: AI 正在执行多步任务
- **WHEN** AI 开始生成包含推理和任务步骤的响应
- **THEN** 界面上出现“思考过程”可折叠面板，并默认展开。
- **THEN** 顶部展示引用的文件列表（如有）。
- **THEN** 下方实时渲染带有状态图标（进行中/已完成）的任务步骤列表。
- **THEN** 面板底部显示 "思考中 ..." 动画。

## MODIFIED Requirements
### Requirement: 聊天消息组件渲染
修改现有的消息气泡渲染逻辑，将其拆分为“思考元数据区”和“最终结果区”。思考元数据区展示上述的新组件，最终结果区依然保持 Markdown 渲染。
