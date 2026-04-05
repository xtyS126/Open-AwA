# Refactor CoT Display with Collapse Spec

## Why
当前在聊天页面展示的模型思维链（Chain-of-Thought）内容仅仅是一个简单的 `div` 容器。当模型生成大量思维链内容时，该容器会无限制地被撑高，不仅可能将主内容挤出屏幕视口，也缺乏对已完成思考过程的整理手段，导致整体用户体验下降。因此，需要将其改造为一个具备高度限制、自动滚动以及可展开/折叠的专属组件。

## What Changes
- **思维链专属组件封装**：新建一个独立的 `ReasoningContent` 组件，包含标题栏（支持点击展开/折叠）与内容展示区。
- **最大高度与自动滚动**：为内容区设置预设高度阈值（如 `320px`）和 `overflow-y: auto`。在流式输出进行时，组件监听内容变化并将滚动条始终保持在最底部。
- **状态联动与折叠动画**：在流式输出结束（如 `isLoading` 从 `true` 变为 `false` 时，且属于最后一条消息）或收到完成标记后，默认将思维链折叠，仅展示标题。引入 CSS Transition 实现平滑的高度展开/折叠动画。
- **偏好持久化**：用户手动点击展开或收起的状态将保存至 `localStorage`。如果用户主动收起了某条消息的思维链，重新打开页面时能保持此状态。全局折叠策略与手动干预相结合。
- **全面测试覆盖**：补充前端单元测试和端到端测试，验证高度阈值、滚动条自动定位、折叠逻辑和状态持久化功能在不同边界条件下的正确性。

## Impact
- Affected specs: 聊天界面渲染与交互、流式消息输出。
- Affected code:
  - `frontend/src/features/chat/components/ReasoningContent.tsx` (New)
  - `frontend/src/features/chat/components/ReasoningContent.module.css` (New)
  - `frontend/src/features/chat/ChatPage.tsx` (Use new component)
  - `frontend/src/__tests__/ReasoningContent.test.tsx` (New)
  - E2E testing scripts

## ADDED Requirements
### Requirement: 思维链自动滚动与折叠控制
系统 SHALL 在渲染长思维链时维持视口稳定，并允许整理和回顾。

#### Scenario: 实时渲染长思维链
- **WHEN** 处于流式传输模式，思维链内容正在不断增加并超过 320px
- **THEN** 容器高度不再增加，内部自动触发向底部滚动以展示最新文本。

#### Scenario: 流式输出结束自动收起
- **WHEN** 该条消息流式输出完成
- **THEN** 组件触发动画，默认将内容区域折叠隐藏，仅展示如“思考过程”的标题栏。

#### Scenario: 用户手动展开并恢复
- **WHEN** 用户点击标题栏展开已折叠的思维链，并刷新页面
- **THEN** 页面重新渲染时，该组件读取 `localStorage` 或相关状态，保持用户最后设定的展开状态。