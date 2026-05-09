# Tasks

- [x] 任务1：创建基础 `ReasoningContent` 组件与样式
  - [x] 子任务1.1：在 `frontend/src/features/chat/components/` 下新建 `ReasoningContent.tsx` 和 `ReasoningContent.module.css`。
  - [x] 子任务1.2：编写基础的带标题栏的展开/折叠容器样式，设置 `max-height: 320px`、`overflow-y: auto` 及 `transition` 平滑过渡效果。

- [x] 任务2：实现自动滚动与折叠控制逻辑
  - [x] 子任务2.1：利用 `useRef` 获取内容区 DOM，并在 `useEffect` 中监听 `content` 变化，实现向下滚动。
  - [x] 子任务2.2：通过传入 `isStreaming` 等标志位判断，在流式输出结束时自动折叠容器。

- [x] 任务3：状态持久化与组件整合
  - [x] 子任务3.1：使用 `localStorage` 记录该消息级别的展开/收起状态（可以通过特定的 `message_id` 作为键名）。
  - [x] 子任务3.2：将 `ChatPage.tsx` 中的旧思维链 `div` 替换为新开发的 `ReasoningContent` 组件，并正确传递 `content` 和 `isStreaming`。

- [x] 任务4：质量保障与测试用例编写
  - [x] 子任务4.1：编写单元测试 `ReasoningContent.test.tsx` 覆盖默认折叠逻辑、高度变化监听、自动滚动方法调用、以及 localStorage 存取。
  - [x] 子任务4.2：补充 E2E 测试用例，模拟思维链输出超过阈值（如 `320px`）、点击收起、流式输出完成后的最终 UI 呈现等交互。
  - [x] 子任务4.3：验证在不同分辨率与主题下，动画无卡顿，视觉样式一致，无明显回退或报错。

# Task Dependencies
- 任务2 依赖 任务1 的基础组件。
- 任务3 依赖 任务2 完成自动逻辑。
- 任务4 依赖 所有功能实现后进行验证。