# Fix Stream Truncation on Hidden Tab Spec

## Why
当用户在流式输出模型结果时切换标签页、最小化浏览器或锁屏，前端可能会因为频繁的状态更新（每秒几十次渲染）而累积大量的内存与渲染队列，最终触发浏览器的后台资源限制或导致内存泄漏，导致标签页崩溃或网络请求被强行切断，造成输出截断的数据丢失。需要优化后台运行时的前端流式处理逻辑，通过缓冲与降频渲染策略保障长文本推理的可靠性。

## What Changes
- **流式数据缓冲机制**：在 `ChatPage.tsx` 中引入针对后台状态的流数据缓冲区（Buffer）。
- **页面可见性监听与动态节流**：
  - 当 `document.hidden` 为 `false`（前台）时，接收到 SSE chunk 立即更新到状态库以保证实时性。
  - 当 `document.hidden` 为 `true`（后台）时，将接收到的 `content` 和 `reasoning_content` 累加到缓冲区中，采用低频节流策略（如每 1000ms 执行一次真正的状态更新）。
  - 注册 `visibilitychange` 事件监听器，一旦页面重新回到前台可见状态，立刻强制刷新缓冲区，将所有积压的数据一次性展示，确保“自动恢复并展示完整的模型输出结果”。
- **平滑滚动优化**：当 `document.hidden` 时，暂时停止平滑滚动指令的触发，防止在后台排队产生大量无效渲染请求；在前台恢复时立即执行一次补漏滚动。
- **流结束强制刷新**：无论页面是否在后台，流式请求正常结束或报错时，均清空并刷新所有剩余的缓冲数据，防止数据遗漏。

## Impact
- Affected specs: 聊天页面的流式输出与状态渲染逻辑。
- Affected code:
  - `frontend/src/features/chat/ChatPage.tsx`
  
## ADDED Requirements
### Requirement: 页面后台节流与前台恢复
系统 SHALL 在后台运行流式任务时控制渲染频率，前台恢复时确保内容无损。

#### Scenario: 用户切走标签页
- **WHEN** 页面在流式输出中被切换至后台 (`document.hidden = true`)
- **THEN** 系统降低消息更新频率，缓冲期间收到的所有数据。

#### Scenario: 用户切回标签页
- **WHEN** 页面重新获得焦点 (`visibilitychange` 触发)
- **THEN** 系统立刻清空缓冲区，将完整的最新流式输出呈现在聊天界面上。