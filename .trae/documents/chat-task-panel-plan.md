# 聊天界面竖向可折叠任务栏实现计划

## 目标

在聊天对话框右侧添加一个贴着对话框的、可自动折叠的、竖向排列的任务栏。

## 需求要点

1. **贴着对话框**：任务栏位于聊天消息区域的右侧，与消息列表并排
2. **自动折叠**：当没有活跃任务（无 running/pending 状态）时自动收起；也可手动切换展开/折叠
3. **竖向排列**：任务项从上到下排列，绝不横向排列或横向换行
4. **复用现有数据**：读取 `messageMeta` 中的 `steps`（任务步骤）和 `toolEvents`（工具事件）作为任务数据源

## 当前架构回顾

```
.chat-body (flex row)
  ├── ConversationSidebar (左侧会话列表，条件渲染)
  └── .chat-main (flex:1, flex column)
        ├── MessageList (flex:1, 可滚动)
        ├── [floating-execution 已禁用]
        └── ChatInput (固定底部)
```

## 设计方案

将 `.chat-body` 改为容纳右侧任务面板：

```
.chat-body (flex row, overflow:hidden)
  ├── ConversationSidebar (条件渲染)
  ├── .chat-main (flex:1, flex column) — 消息+输入保持不变
  └── .task-panel-wrapper (可折叠的任务面板，右侧)
        └── TaskPanel
              ├── 折叠/展开按钮
              ├── 活跃任务列表 (竖向)
              └── 已完成任务列表 (竖向)
```

## 实现步骤

### 步骤 1：创建 TaskPanel 组件

**文件**：`frontend/src/features/chat/components/TaskPanel.tsx`

**Props**：
```typescript
interface TaskPanelProps {
  steps: TaskStepMeta[]       // 来自 messageMeta.steps
  toolEvents: ToolEventMeta[] // 来自 messageMeta.toolEvents
  isStreaming: boolean         // 是否正在流式输出
  onStopAgent: (agentId: string) => void  // 停止代理回调
}
```

**功能**：
- 默认展开状态：有 `running`/`pending` 状态的任务时自动展开，全完成/空闲时自动折叠
- 手动切换：点击折叠按钮可强制展开/折叠
- 任务项竖向排列，每项显示：状态圆点 + 任务名称 + 类型标签
- `running` 状态的任务显示停止按钮
- 已完成任务折叠在下方，可展开查看历史

### 步骤 2：创建 TaskPanel 样式

**文件**：`frontend/src/features/chat/components/TaskPanel.module.css`

**样式要点**：
- `.panel`：`display: flex; flex-direction: column;` — 竖向排列
- `.panel.collapsed`：宽度收缩至仅显示切换按钮
- `.taskList`：`display: flex; flex-direction: column; gap: 8px;` — 纯竖向，不换行
- `.taskItem`：单行显示，`flex-shrink: 0`，不折行
- 状态圆点：沿用 ChatPage.module.css 中已有的 `.status-dot-*` 样式
- 过渡动画：`transition: width 0.25s ease`

### 步骤 3：修改 ChatPage.tsx

1. 导入 `TaskPanel` 组件
2. 新增 `taskPanelManuallyToggled` 状态（用户手动切换标记）和 `taskPanelExpanded` 状态（当前展开状态）
3. 在 `chat-body` 的 `chat-main` 右侧插入 `TaskPanel`：
   ```tsx
   <div className={styles['chat-body']}>
     {/* ConversationSidebar ... */}
     <div className={styles['chat-main']}>
       <MessageList ... />
       <ChatInput ... />
     </div>
     <TaskPanel
       steps={activeMeta?.steps || []}
       toolEvents={activeMeta?.toolEvents || []}
       isStreaming={isStreaming}
       onStopAgent={handleStopAgent}
       expanded={taskPanelExpanded}
       onToggle={() => { setTaskPanelManuallyToggled(true); setTaskPanelExpanded(prev => !prev); }}
     />
   </div>
   ```
4. 自动折叠逻辑：当无活跃任务且用户未手动切换时，自动设为折叠状态
5. 需要提取活跃的 `AssistantExecutionMeta`（复用已有的 `getLatestActiveExecution` 逻辑）

### 步骤 4：修改 ChatPage.module.css

1. 确保 `.chat-body` 为 `display: flex; flex-direction: row; overflow: hidden;`
2. 确保 `.chat-main` 为 `flex: 1; min-width: 0;`
3. 新增任务面板容器样式（如需要外层 wrapper）

### 步骤 5：验证

1. `npm run typecheck` 通过
2. `npm run lint` 通过
3. 手动测试：发送消息触发工具调用，观察任务栏是否显示任务列表
4. 确认竖向排列，无横向排列
5. 确认折叠/展开功能正常

## 不改动的部分

- `MessageList` 组件 — 保持不变
- `ChatInput` 组件 — 保持不变
- `ConversationSidebar` — 保持不变
- 现有的 `TaskTracker` 组件 — 保持不变（它是消息内嵌组件，不同于这个独立面板）
- 后端代码 — 完全不涉及
