# Tasks

- [x] 任务1：实现聊天页面的后台节流机制
  - [x] 子任务1.1：在 `ChatPage.tsx` 中引入用于缓冲 `content` 和 `reasoning` 的引用 (`useRef`) 和相关时间戳引用。
  - [x] 子任务1.2：修改 `handleSend` 中的 `onChunk` 回调，根据 `document.hidden` 动态决定是直接调用 `updateLastMessage` 还是累加到缓冲区并节流更新（如 1000ms）。

- [x] 任务2：实现页面可见性恢复逻辑
  - [x] 子任务2.1：在 `ChatPage.tsx` 中添加 `useEffect` 监听 `visibilitychange` 事件。
  - [x] 子任务2.2：当页面重新变为可见时，如果有缓冲数据，立即调用 `updateLastMessage` 刷新并清空缓冲区。

- [x] 任务3：优化流结束逻辑与自动滚动
  - [x] 子任务3.1：在流结束（正常或错误）时，确保最后清空并刷新所有剩余的缓冲数据。
  - [x] 子任务3.2：在 `scrollToBottom` 方法中增加判断，当 `document.hidden` 为 true 时跳过滚动，并在 `visibilitychange` 恢复时主动触发一次滚动。

- [x] 任务4：质量保障与测试
  - [x] 子任务4.1：运行前端类型检查和 Lint，确保没有引入错误。
  - [x] 子任务4.2：通过测试脚本或手工验证，模拟快速切换标签页及后台长期等待的场景，确认不会发生内存溢出和输出截断。

# Task Dependencies
- 任务2 依赖 任务1 建立的缓冲区机制。
- 任务3 依赖 任务1 和 任务2。
- 任务4 依赖 所有逻辑的顺利合入。