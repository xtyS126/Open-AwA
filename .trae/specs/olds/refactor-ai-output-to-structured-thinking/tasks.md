# Tasks

- [x] Task 1: 新增基础结构化 UI 组件库
  - [x] SubTask 1.1: 创建 `ThinkingProcess` 容器组件，支持折叠/展开功能及标题（思考过程）。
  - [x] SubTask 1.2: 创建 `FileReference` 组件，渲染为药丸状标签（包含文件图标）。
  - [x] SubTask 1.3: 创建 `TaskTracker` 和 `TaskStep` 组件，支持渲染已完成（绿色对勾）、进行中（Spinner）状态图标。
  - [x] SubTask 1.4: 创建 `ThoughtBlock` 组件，作为嵌套在任务步骤下的可折叠文本区域。
  - [x] SubTask 1.5: 确保所有组件支持暗黑模式并遵循前端统一的样式规范（无emoji，使用图标库）。

- [x] Task 2: 增强流式响应解析器 (Stream Parser)
  - [x] SubTask 2.1: 在 `streamParser.ts` 中新增解析逻辑，从 Markdown 或特定的 XML/JSON 结构中提取思考内容、参考文件和任务列表。
  - [x] SubTask 2.2: 设计状态模型，用于维护流式输出中的：当前是否处于思考状态、正在引用的文件列表、任务列表及其进行中/已完成状态。
  - [x] SubTask 2.3: 编写单元测试覆盖流式解析器的各种状态变化（如步骤状态的流式切换）。

- [x] Task 3: 改造聊天消息组件 (ChatMessage)
  - [x] SubTask 3.1: 将原有的纯 Markdown 渲染拆分为“思考元数据区”和“最终结果区”。
  - [x] SubTask 3.2: 引入 `ThinkingProcess` 组件，绑定解析后的状态模型，并渲染内部的引用文件和步骤追踪器。
  - [x] SubTask 3.3: 添加流式输出时的 "思考中 ..." 底部动画指示器。

- [x] Task 4: 样式优化与集成测试
  - [x] SubTask 4.1: 对齐设计图的视觉层级（缩进、颜色、线条、图标大小）。
  - [x] SubTask 4.2: 修复可能的重渲染性能问题（如使用 `React.memo` 优化不需要重复渲染的子步骤）。
  - [x] SubTask 4.3: 测试实际环境下的数据流并验证显示正确性。

# Task Dependencies
- [Task 3] depends on [Task 1]
- [Task 3] depends on [Task 2]
- [Task 4] depends on [Task 3]
