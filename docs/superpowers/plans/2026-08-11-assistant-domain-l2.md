# 助手域真实 L2 与移动域内导航实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `/assistant`、`/assistant/sessions`、`/assistant/context` 从同一聊天页别名收口为真实的当前对话、会话管理和每会话上下文，并在移动 Web 投影当前领域 L2。

**Architecture:** 移动域内导航只消费现有版本化 `navigationManifest`，不建立第二套路径常量。会话管理从聊天侧栏抽取无外壳的管理主体和纯列表动作；上下文写入已有 `Conversation.conversation_metadata.assistant_context`，不新增数据库表，并由所有聊天传输共享的装配边界注入角色、工作区和显式长期记忆。声音只作为每会话 TTS 偏好保存，不伪装成 LLM 上下文。

**Tech Stack:** React 18、TypeScript、TanStack Router、Zustand、React Query、CSS Modules、FastAPI、Pydantic、SQLAlchemy、Vitest、Pytest、Playwright。

**执行边界:** 当前任务继续使用包含用户未提交改动的共享工作树，不创建或切换 Git worktree；每个并行执行者只能修改明确分配的文件，不得回退其他改动。完整门禁通过前不提交，不推送。

---

## 文件职责图

- `frontend/src/shared/components/DomainLocalNav/`：把当前领域 children 投影成仅 `<768px` 可见的横向 L2 导航。
- `frontend/src/features/chat/components/ConversationManager.tsx`：会话筛选、虚拟列表、选择、批量工具栏和重命名 UI，不包含侧栏、账户或路由职责。
- `frontend/src/features/chat/components/ConversationSidebar.tsx`：保留聊天页侧栏外壳，组合 `ConversationManager`。
- `frontend/src/features/chat/hooks/useConversationListActions.ts`：创建、重命名、删除、恢复、批量删除和确认状态，不读取消息流状态。
- `frontend/src/features/assistant/AssistantSessionsPage.tsx`：全页会话管理器，选择会话后进入 L3 聊天详情。
- `backend/api/services/assistant_context_service.py`：解析、校验、读取和保存每会话助手上下文，供 conversation/chat 两条路由复用。
- `backend/api/routes/conversation.py`：暴露上下文 GET/PATCH，不改变既有重命名契约。
- `backend/api/routes/chat.py` 与聊天协议共享入口：把已保存上下文注入 Agent context。
- `backend/memory/manager.py`：提供按 ID、用户、工作区加载长期记忆的公共异步方法。
- `frontend/src/features/assistant/AssistantContextPage.tsx`：角色、项目、知识和声音四分区选择器，保存到当前会话。

## Task 1：修复隔离 E2E 后端端口契约

**Files:**
- Modify: `frontend/tests/e2e/support/start_backend.py`
- Test: `frontend/tests/e2e/support/test_start_backend.py`

- [x] **Step 1: 写 RED，要求有效 E2E 端口同步到 `BACKEND_PORT`**

```python
def test_configure_environment_exports_effective_backend_port(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENAWA_E2E_BACKEND_PORT", "19001")
    monkeypatch.delenv("BACKEND_PORT", raising=False)
    effective_port = start_backend._configure_environment(tmp_path)
    assert effective_port == 19001
    assert os.environ["BACKEND_PORT"] == "19001"
```

- [x] **Step 2: 运行 RED 并确认 `KeyError: BACKEND_PORT`**

Run: `D:\代码\Open-AwA\.venv\Scripts\python.exe -m pytest --no-cov frontend/tests/e2e/support/test_start_backend.py -q`

Expected: `1 failed`，失败点为 `os.environ["BACKEND_PORT"]`。

- [x] **Step 3: 在隔离环境字典中加入端口桥接**

```python
"BACKEND_PORT": str(backend_port),
```

- [x] **Step 4: 运行 GREEN 与真实 run-all**

Expected: 单测 `1 passed`；Playwright `2 passed`；系统场景 `9/10`，唯一失败为结构化 `llm_api_key_missing`。

## Task 2：实现移动 `DomainLocalNav`

**Files:**
- Create: `frontend/src/shared/components/DomainLocalNav/DomainLocalNav.tsx`
- Create: `frontend/src/shared/components/DomainLocalNav/DomainLocalNav.module.css`
- Modify: `frontend/src/layouts/AppShell.tsx`
- Test: `frontend/src/__tests__/shared/components/DomainLocalNav.test.tsx`

- [x] **Step 1: 写组件 RED**

```tsx
it('在助手深链中投影三个 L2 且仅会话项为当前页', () => {
  renderWithRouter(<DomainLocalNav />, { route: '/assistant/sessions/session-42' })
  const nav = screen.getByRole('navigation', { name: '助手页面导航' })
  expect(within(nav).getAllByRole('link')).toHaveLength(3)
  expect(within(nav).getByRole('link', { name: '会话' })).toHaveAttribute('aria-current', 'page')
  expect(within(nav).getAllByRole('link').filter((link) => link.hasAttribute('aria-current'))).toHaveLength(1)
})

it('全局页面不渲染域内导航', () => {
  renderWithRouter(<DomainLocalNav />, { route: '/settings/general' })
  expect(screen.queryByRole('navigation', { name: /页面导航/ })).not.toBeInTheDocument()
})
```

- [x] **Step 2: 运行 RED**

Run: `cd frontend; npx vitest run --no-coverage src/__tests__/shared/components/DomainLocalNav.test.tsx`

Expected: FAIL，模块不存在。

- [x] **Step 3: 用清单和最长前缀选择器实现组件**

```tsx
export default function DomainLocalNav() {
  const location = useLocation()
  const domain = getActiveDomain(location.pathname)
  if (!domain) return null
  const activeChild = getActiveChild(domain, location.pathname)
  return (
    <nav className={styles.root} aria-label={`${t(domain.labelKey)}页面导航`}>
      <div className={styles.scroller}>
        {domain.children.map((entry) => (
          <Link
            key={entry.id}
            to={entry.canonicalPath}
            className={styles.link}
            aria-current={entry.id === activeChild?.id ? 'page' : undefined}
          >
            {t(entry.labelKey)}
          </Link>
        ))}
      </div>
    </nav>
  )
}
```

CSS 默认隐藏；`@media (max-width: 767px)` 显示，横向滚动，链接 `min-height: 44px`，不得 fixed 覆盖内容。

- [x] **Step 4: 在 `main-content` 内、keyed page wrapper 外挂载**

```tsx
<main id="main-content" className="main-content" tabIndex={-1}>
  <DomainLocalNav />
  <div className="page-transition-wrapper" key={location.pathname}>
    <Outlet />
  </div>
</main>
```

- [x] **Step 5: 运行 GREEN、Sidebar/MobileTabBar 回归**

Run: `cd frontend; npx vitest run --no-coverage src/__tests__/shared/components/DomainLocalNav.test.tsx src/__tests__/shared/components/Sidebar/Sidebar.test.tsx src/__tests__/shared/components/MobileTabBar.test.tsx`

Expected: 全部通过；每个导航容器内部至多一个 `aria-current="page"`。

## Task 3：抽取会话管理主体与列表动作

**Files:**
- Create: `frontend/src/features/chat/components/ConversationManager.tsx`
- Create: `frontend/src/features/chat/components/ConversationManager.module.css`
- Create: `frontend/src/features/chat/hooks/useConversationListActions.ts`
- Modify: `frontend/src/features/chat/components/ConversationSidebar.tsx`
- Modify: `frontend/src/features/chat/hooks/useChatConversationActions.ts`
- Test: `frontend/src/__tests__/features/chat/ConversationManager.test.tsx`
- Test: `frontend/src/__tests__/features/chat/hooks/useConversationListActions.test.ts`
- Test: `frontend/src/__tests__/features/chat/hooks/useChatConversationActions.test.ts`

- [x] **Step 1: 写 RED，锁定无侧栏依赖的管理主体**

```tsx
it('渲染筛选、批量工具栏和会话列表但不渲染账户或折叠按钮', () => {
  render(<ConversationManager {...managerProps} />)
  expect(screen.getByRole('searchbox')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '批量删除' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /收起历史/ })).not.toBeInTheDocument()
  expect(screen.queryByText('退出登录')).not.toBeInTheDocument()
})
```

- [x] **Step 2: 写动作 hook RED**

```ts
it('删除会话必须确认后才请求 API', async () => {
  const { result } = renderHook(() => useConversationListActions(options))
  act(() => result.current.requestDelete('session-1'))
  expect(conversationAPI.deleteSession).not.toHaveBeenCalled()
  await act(() => result.current.confirmDelete())
  expect(conversationAPI.deleteSession).toHaveBeenCalledWith('session-1')
})
```

- [x] **Step 3: 抽取 UI，不改变现有侧栏可观察行为**

`ConversationManager` 接收列表数据和回调；`ConversationSidebar` 只保留 `<aside>`、移动用户卡、标题与折叠控制，再组合管理主体。

- [x] **Step 4: 抽取 CRUD，不让列表 hook读取消息 Store**

`useConversationListActions` 只依赖 `conversationAPI`、列表刷新函数、导航回调和 toast。禁止调用 `setSessionId`、`setMessages`、流式 reset 或历史消息 API。

- [x] **Step 5: 删除双 mount 列表请求**

列表首载只由 `useConversationHistory` 或拆出的 `useConversationList` 所有；删除 `useChatConversationActions` 中第二个 mount load，并将原测试改为“该 hook 不主动拉会话列表”。

- [x] **Step 6: 运行相关 GREEN**

Run: `cd frontend; npx vitest run --no-coverage src/__tests__/features/chat/ConversationManager.test.tsx src/__tests__/features/chat/ConversationSidebar.test.tsx src/__tests__/features/chat/hooks/useConversationListActions.test.ts src/__tests__/features/chat/hooks/useChatConversationActions.test.ts`

## Task 4：实现真实 `/assistant/sessions` 页面

**Files:**
- Create: `frontend/src/features/assistant/AssistantSessionsPage.tsx`
- Create: `frontend/src/features/assistant/AssistantSessionsPage.module.css`
- Modify: `frontend/src/router/index.tsx`
- Test: `frontend/src/__tests__/features/assistant/AssistantSessionsPage.test.tsx`
- Test: `frontend/src/__tests__/features/assistant/AssistantRoutes.test.tsx`

- [x] **Step 1: 写路由差异 RED**

```tsx
it.each([
  ['/assistant', 'AI 助手'],
  ['/assistant/sessions', '会话管理'],
])('路径 %s 渲染对应 L2', async (path, heading) => {
  renderAppAt(path)
  expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument()
})
```

同时断言 sessions 页没有 ChatInput。

- [x] **Step 2: 写副作用 RED**

打开空 sessions 页时 `listSessions` 一次，`createSession` 和 `chatAPI.getHistory` 均为零；点击行只导航，不提前调用 `sessionStore.setSessionId`。

- [x] **Step 3: 实现页面并改路由**

```tsx
{ path: '/assistant/sessions', element: withPageBoundary('AssistantSessions', <AssistantSessionsPage />) }
```

页面组合 `ConversationManager`、列表 hook、动作 hook 和现有 `ConfirmDialog`；选择会话导航到 `/assistant/sessions/${sessionId}`。

- [x] **Step 4: 运行 GREEN**

Run: `cd frontend; npx vitest run --no-coverage src/__tests__/features/assistant/AssistantSessionsPage.test.tsx src/__tests__/features/assistant/AssistantRoutes.test.tsx src/__tests__/router/index.test.tsx`

## Task 5：建立每会话助手上下文后端契约

**Files:**
- Create: `backend/api/services/assistant_context_service.py`
- Modify: `backend/api/schemas.py`
- Modify: `backend/api/routes/conversation.py`
- Test: `backend/tests/test_conversation_assistant_context.py`

- [x] **Step 1: 写 API RED**

覆盖：GET 空上下文、PATCH 保存和恢复、他人会话拒绝、不可见角色拒绝、禁用工作区拒绝、非本人或非当前工作区记忆拒绝、最多 20 条记忆、speaker 长度校验、校验失败不部分写入。

```python
response = client.patch(
    f"/api/conversations/{session_id}/assistant-context",
    json={
        "role_id": role.id,
        "workspace_id": workspace.id,
        "selected_memory_ids": [memory.id],
        "speaker_id": "zh_female_qingxin",
    },
    headers=auth_headers,
)
assert response.status_code == 200
assert response.json()["selected_memory_ids"] == [memory.id]
```

- [x] **Step 2: 定义严格 schema**

```python
class ConversationAssistantContext(BaseModel):
    role_id: Optional[str] = Field(default=None, max_length=64)
    workspace_id: str = Field(default="default", min_length=1, max_length=50)
    selected_memory_ids: List[int] = Field(default_factory=list, max_length=20)
    speaker_id: Optional[str] = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="forbid")
```

- [x] **Step 3: 服务层一次性校验后再写 metadata**

元数据键固定为 `assistant_context`。只有全部引用验证通过后才复制并替换 JSON，调用 `flag_modified(conversation, "conversation_metadata")`，避免 SQLAlchemy JSON 原地修改不落库。

- [x] **Step 4: 添加 GET/PATCH 路由**

路径固定为：

```text
GET   /api/conversations/{session_id}/assistant-context
PATCH /api/conversations/{session_id}/assistant-context
```

- [x] **Step 5: 运行 GREEN**

Run: `cd backend; D:\代码\Open-AwA\.venv\Scripts\python.exe -m pytest --no-cov tests/test_conversation_assistant_context.py -q`

## Task 6：让保存的上下文真实进入聊天执行

**Files:**
- Modify: `backend/api/services/assistant_context_service.py`
- Modify: `backend/api/routes/chat.py`
- Modify: `backend/api/services/chat_protocol.py` 或其共享 Agent context 装配边界
- Modify: `backend/memory/manager.py`
- Modify: `backend/core/agent.py`
- Test: `backend/tests/test_chat_assistant_context.py`
- Test: `backend/tests/test_memory_manager.py`

- [x] **Step 1: 写 HTTP/SSE/WS RED**

断言同一会话保存上下文后，三条聊天路径传给 Agent 的 context 均包含相同 `role_id`、`workspace_id`、`selected_memory_ids`；旧会话保持 `workspace_id="default"` 且不含 role/显式记忆。

- [x] **Step 2: 提供公共按 ID 加载方法**

```python
async def get_memories_by_ids(
    self,
    memory_ids: List[int],
    *,
    user_id: Optional[str],
    workspace_id: str,
) -> List[LongTermMemory]:
    return await asyncio.to_thread(
        self._get_memories_by_ids_sync,
        memory_ids,
        user_id,
        False,
        False,
        workspace_id,
    )
```

- [x] **Step 3: 在共享 context 装配边界注入 metadata**

禁止由前端 chat payload 直接提交 role/workspace/memory ID；服务端按已认证用户和 session 读取已验证 metadata。

- [x] **Step 4: 合并显式记忆和相关性检索结果**

显式记忆先按 ID 加载，再与搜索结果按 memory ID 去重；不得加载 archived、deprecated、他人或其他 workspace 记忆。角色继续复用 `RoleEngine`，工作区沿现有 `context["workspace_id"]` 进入短期/长期记忆隔离。

- [x] **Step 5: 运行核心 GREEN**

Run: `cd backend; D:\代码\Open-AwA\.venv\Scripts\python.exe -m pytest --no-cov tests/test_chat_assistant_context.py tests/test_memory_manager.py tests/test_agent_architecture.py -q`

## Task 7：实现真实 `/assistant/context` 页面

**Files:**
- Create: `frontend/src/features/assistant/AssistantContextPage.tsx`
- Create: `frontend/src/features/assistant/AssistantContextPage.module.css`
- Modify: `frontend/src/shared/api/conversationApi.ts`
- Modify: `frontend/src/router/index.tsx`
- Test: `frontend/src/__tests__/features/assistant/AssistantContextPage.test.tsx`
- Test: `frontend/src/__tests__/features/assistant/AssistantRoutes.test.tsx`

- [x] **Step 1: 写四分区 RED**

```tsx
expect(screen.getByRole('group', { name: '角色上下文' })).toBeInTheDocument()
expect(screen.getByRole('group', { name: '项目上下文' })).toBeInTheDocument()
expect(screen.getByRole('group', { name: '知识上下文' })).toBeInTheDocument()
expect(screen.getByRole('group', { name: '声音偏好' })).toBeInTheDocument()
```

同时断言：没有活动会话时不自动创建会话；单个分区加载失败不遮蔽其他分区；保存失败保留用户选择并显示 `role="alert"`。

- [x] **Step 2: 增加 API 类型和方法**

```ts
export interface AssistantConversationContext {
  session_id: string
  role_id: string | null
  workspace_id: string
  selected_memory_ids: number[]
  speaker_id: string | null
}

getAssistantContext(sessionId: string)
updateAssistantContext(sessionId: string, context: Omit<AssistantConversationContext, 'session_id'>)
```

- [x] **Step 3: 并行加载四类资源**

角色复用 `getRoles`，项目复用 `workspaceApi.list`，知识复用 `memoryAPI.getLongTerm`，声音复用 `ttsApi.listSpeakers`。独立错误边界，不调用会虚增 usage_count 的 `activateRole`，不调用会吞错的 `ttsStore.loadSpeakers`。

- [x] **Step 4: 使用原生 radio/checkbox 语义**

角色、项目、声音单选；知识最多 20 项多选。触控目标至少 44px，小字号紫色文字使用深紫令牌，支持 200% 字体与 reduced-motion。

- [x] **Step 5: 改路由并运行 GREEN**

```tsx
{ path: '/assistant/context', element: withPageBoundary('AssistantContext', <AssistantContextPage />) }
```

Run: `cd frontend; npx vitest run --no-coverage src/__tests__/features/assistant/AssistantContextPage.test.tsx src/__tests__/features/assistant/AssistantRoutes.test.tsx src/__tests__/router/index.test.tsx`

## Task 8：集成验收与回归

**Files:**
- Modify: `frontend/tests/e2e/compatibility/responsive-layout.spec.ts`
- Create: `frontend/tests/e2e/compatibility/assistant-domain-acceptance.spec.ts`

- [x] **Step 1: 运行前后端定向测试**

Expected: 助手、导航、会话上下文、chat 三传输和 memory 定向套件全部通过。

- [x] **Step 2: 运行前端类型与定向 lint**

Run: `cd frontend; npm run typecheck`

Run: `cd frontend; npx eslint <本计划修改的 TS/TSX 文件>`

- [x] **Step 3: 构建**

Run: `cd frontend; npm run build`

- [x] **Step 4: 五档浏览器验收**

在 375、480、768、1024、1440 px 验证：

- 375/480 有 L2 横向导航，助手三项可达。
- sessions 页搜索、归档、批量确认可用，点击会话进入 L3。
- context 页四分区选择刷新后恢复。
- 768 及以上不显示 `DomainLocalNav`，桌面 Sidebar 继续唯一承载 L2。
- 每个 nav 内至多一个 current，页面无横向溢出、page error 或 console error。
- 200% 字体下 L2 和四分区不截断，触控目标不小于 44px。

- [x] **Step 5: 服务闭环**

重跑后端定向 pytest、`/api/system/ping`、run-all 和生产构建。`chat-nonstream` 只有在结构化 `llm_api_key_missing` 时可作为明确例外，不能宣称真实模型成功。

- [x] **Step 6: 更新记忆与提交审查**

把真实上下文契约、重复请求修复和任何新坑点写入当日 `topics.md`；只有完整门禁通过且任务范围 diff 审查无误后，才评估是否提交到 main。永不自主 push。

## 计划自审

- 规格覆盖：助手三个 L2、移动 L2、会话管理、四类上下文和聊天真实生效均有任务。
- 兼容性：不新增数据库表；旧会话无 `assistant_context` 时保持现有默认行为；重命名 API 不改变。
- 安全性：上下文引用由服务端按认证用户与 workspace 校验；前端不能通过 chat payload 绕过。
- 传输一致性：上下文装配必须覆盖非流式、SSE 和 WebSocket。
- 范围边界：speaker 只作为 TTS 偏好；正式品牌图标、favicon、PWA、Android 和桌面资源仍不在本计划内。
- 占位符扫描：计划无 TBD、TODO 或“稍后实现”步骤。
