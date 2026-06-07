# 单用户 + API Key 认证 + 后端独立化 设计方案

> 创建日期：2026-06-07
> 状态：已确认
> 目标：将多人系统改造为单人唯一账号，通过 API Key 认证，后端可独立运行服务 Android/Windows 桌面应用

---

## 一、需求背景

当前 Open-AwA 是一个多用户 Web 应用，用户通过 `config/users.yaml` 管理，前端 React SPA 作为主要交互界面。需要改造为：

1. **单用户唯一账号** — 不再需要注册和多用户管理
2. **API Key 认证** — 前端和外部客户端都用同一个全局 API Key
3. **后端独立化** — 后端可作为独立 API 服务器，对接 Android/Windows 桌面应用，通过 API 驱动 AI 自主执行任务

---

## 二、设计目标

| 目标 | 说明 |
|------|------|
| 全局 API Key | `.env` 配置一个 Key，所有客户端共用 |
| 单用户 | 启动时自动创建唯一 owner 用户，无需手动管理 |
| 全功能保留 | 对话、技能、插件、定时任务、记忆、工作流、用户画像全部保留 |
| API 驱动自主执行 | 外部客户端发送 prompt → AI 自主规划执行 → 返回结果 |
| 前后端统一认证 | 前端和外部 app 使用相同的 Bearer token 认证方式 |
| 数据库兼容 | 不加 ALTER TABLE，业务层适配 |
| 向后兼容 JWT | 可选保留 JWT 验证路径，不影响已有功能 |

---

## 三、认证模型

### 3.1 架构图

```
.env 配置                  客户端
┌──────────────────┐       ┌─────────────────┐
│ OPENAWA_API_KEY  │       │ React Frontend   │
│ = sk-xxx...      │       │ Android App      │
│                  │       │ Windows Desktop  │
│ OPENAWA_OWNER_   │       │ CI/CD Pipeline   │
│ USERNAME=admin   │       └──────┬──────────┘
│ OPENAWA_OWNER_   │              │ Authorization:
│ PASSWORD=...     │              │ Bearer sk-xxx...
└──────────────────┘              ▼
                          ┌──────────────┐
                          │  FastAPI      │
                          │  认证中间件    │
                          │  API Key 验证  │
                          └──────────────┘
```

### 3.2 认证流程

```
请求到达
    │
    ▼
提取 Authorization Header
    │
    ├─ Bearer <token>
    │     │
    │     ├─ token == OPENAWA_API_KEY? → 返回 owner 用户，跳过 CSRF
    │     │
    │     └─ token != API Key? → 尝试 JWT 验证（兼容旧前端）
    │           ├─ 有效 → 返回对应用户
    │           └─ 无效 → 401
    │
    └─ 无 Authorization → 尝试 Cookie（兼容旧前端）
          ├─ 有效 JWT Cookie → 返回对应用户
          └─ 无效 → 401
```

### 3.3 环境变量

```bash
# ═══════════════════════════════════════════════════════
# 认证配置
# ═══════════════════════════════════════════════════════

# API Key（至少 32 字符，未设置时自动生成并写入 .env.local）
OPENAWA_API_KEY=

# Owner 用户名（默认 admin）
OPENAWA_OWNER_USERNAME=admin

# Owner 密码（用于兼容 JWT 登录，未设置时自动生成）
OPENAWA_OWNER_PASSWORD=

# Owner 昵称（可选）
OPENAWA_OWNER_NICKNAME=

# Owner 邮箱（可选）
OPENAWA_OWNER_EMAIL=
```

### 3.4 API Key 初始化和持久化

```python
# 启动时
api_key = os.getenv("OPENAWA_API_KEY", "").strip()
if not api_key:
    import secrets
    api_key = "sk-" + secrets.token_urlsafe(32)
    logger.warning(
        f"[SECURITY] OPENAWA_API_KEY 未设置，已自动生成。"
        f"请妥善保存: {api_key}"
    )
    # 自动写入 .env.local
    _persist_api_key(api_key)

settings.OPENAWA_API_KEY = api_key
```

---

## 四、认证依赖注入（改 `get_current_user`）

### 4.1 新实现

```python
# backend/api/dependencies.py

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    统一认证：API Key 优先 → JWT 降级 → Cookie 兜底。
    API Key 绕过 CSRF、JWT 黑名单检查。
    """
    api_key = settings.OPENAWA_API_KEY

    if credentials:
        token = credentials.credentials
        # API Key 认证
        if api_key and secrets.compare_digest(token, api_key):
            return _get_or_create_owner_user(db)
        # JWT 认证（兼容）
        return await _resolve_jwt_user(token, db)

    # Cookie 降级（兼容旧前端）
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    if cookie_token:
        return await _resolve_jwt_user(cookie_token, db)

    raise HTTPException(status_code=401)
```

### 4.2 关键变更点

| 变更 | 说明 |
|------|------|
| API Key 认证是字符串常量比较 | 不需要 JWT 编解码、不检查黑名单、不检查过期 |
| CSRF 中间件对 API Key 跳过 | `Authorization: Bearer <api_key>` 时 `_extract_user_id_from_request` 返回 None → 中间件跳过校验 |
| `get_current_admin_user` → 直接返回 owner | 单用户永远具有管理员权限 |
| 移除 JWT 黑名单检查 | API Key 无 jti |

---

## 五、用户模型（Owner 自动化）

### 5.1 启动时 Ensure Owner

```python
# main.py lifespan
async def _ensure_owner_user(db: Session) -> User:
    """确保唯一的 owner 用户存在，不存在则创建。"""
    from db.models import User
    from config.security import get_password_hash
    import secrets, uuid

    username = os.getenv("OPENAWA_OWNER_USERNAME", "admin").strip() or "admin"
    password = (os.getenv("OPENAWA_OWNER_PASSWORD", "").strip()
                or secrets.token_urlsafe(16))
    nickname = os.getenv("OPENAWA_OWNER_NICKNAME", "").strip()
    email = os.getenv("OPENAWA_OWNER_EMAIL", "").strip()

    user = db.query(User).filter(User.username == username).first()
    if not user:
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=get_password_hash(password),
            role="admin",
            nickname=nickname or None,
            email=email or None,
        )
        db.add(user)
        db.commit()
        logger.info(f"已创建 owner 用户: {username}")
    else:
        # 更新昵称/邮箱（如果环境变量有值）
        updated = False
        if nickname and user.nickname != nickname:
            user.nickname = nickname
            updated = True
        if email and user.email != email:
            user.email = email
            updated = True
        if updated:
            db.commit()

    return user
```

### 5.2 Owner 角色绑定

```python
# 启动时确保 owner 拥有 admin 角色
from security.rbac import RBACManager
rbac = RBACManager(db)
rbac.ensure_built_in_roles()
await rbac.set_user_role(owner.id, "admin")
```

---

## 六、Remove Items（明确删除）

| 删除项 | 文件/位置 | 原因 |
|--------|----------|------|
| `config/users.yaml` | `backend/config/users.yaml` | 不再需要多用户配置文件 |
| `config/local_users.py` | `backend/config/local_users.py` | 用户同步逻辑废弃 |
| `sync_local_users_to_db` 调用 | `main.py` startup | 替换为 `_ensure_owner_user` |
| 注册 API | `auth.py` `/register` | 已禁用，彻底删除 |
| 用户管理 UI | 前端 `SettingsPage` 用户管理页 | 单用户无需管理 |
| `LoginPage` | 前端 | 改为 API Key 配置页 |
| `RegisterPage` | 前端 | 删除 |

---

## 七、数据库业务层适配

原则：**不删字段、不加 ALTER TABLE**，只在业务层统一 `user_id` 为 owner.id。

| 表 | 当前 | 改后 |
|---|------|------|
| `users` | 多用户 | 仅一条 owner 记录 |
| `conversations` | 按 `user_id` 过滤 | 不过滤（或按 owner 过滤） |
| `scheduled_tasks` | FK `user_id` | 新建时填 owner.id |
| `workflows` | `user_id` 索引 | 新建时填 owner.id |
| `long_term_memory` | `user_id` 可空 | 写入时填 owner.id |
| `experience_memory` | 按 `user_id` 查 | 不过滤 |
| `behavior_logs` | 按 `user_id` 查 | 不过滤 |
| `profile_facts` | FK `user_id` | 新建时填 owner.id |
| `user_roles` | 多对多 | 保留表但不再查询（owner = 全权限） |
| `permission_saved` | 按 `created_by` 过滤 | 不过滤 |
| `login_devices` | FK `user_id` | API Key 来源记录 device_type="api" |
| `user_feedback` | `user_id` 列 | 新建时填 owner.id |
| `weixin_bindings` | `user_id` 列 | 保留 |
| `weixin_auto_reply_rules` | FK `user_id` | 新建时填 owner.id |
| `audit_logs` | `user_id` 可空 | 操作时填 owner.id |

### 辅助函数

```python
# backend/api/dependencies.py 或新建 backend/core/owner.py

_owner_cache: Optional[User] = None
_owner_lock = asyncio.Lock()

async def get_owner_user(db: Session) -> User:
    """获取唯一 owner 用户（带缓存）。"""
    global _owner_cache
    if _owner_cache:
        return _owner_cache
    async with _owner_lock:
        if _owner_cache:
            return _owner_cache
        from db.models import User
        # 从 settings 获取 owner username
        username = os.getenv("OPENAWA_OWNER_USERNAME", "admin").strip() or "admin"
        _owner_cache = db.query(User).filter(User.username == username).first()
        if not _owner_cache:
            raise RuntimeError("Owner 用户未初始化")
        return _owner_cache

def get_owner_id(db: Session) -> str:
    """获取 owner 用户 ID（同步版本，用于非 async 上下文）。"""
    # 从数据库查（利用 SQLAlchemy session cache）
    ...
```

---

## 八、后端独立执行能力

### 8.1 现有 Chat 端点增强

`POST /api/chat/send` 新增 `autonomous` 参数：

```json
{
  "message": "帮我把 data/raw/*.csv 合并成一个文件",
  "provider": "deepseek",
  "model": "deepseek-chat",
  "mode": "nonstream",
  "autonomous": true
}
```

`autonomous: true` 时：
- 权限检查全部 `auto_approve`
- 不创建 `PermissionRequest` 阻塞等待
- SSE 流可选（`stream` 模式正常推送，`nonstream` 模式一次性返回）
- 工具调用回环正常进行（最多 `MAX_TOOL_CALL_ROUNDS` 轮）

### 8.2 新增任务执行端点

`POST /api/tasks/execute` — 为自动化场景设计：

```json
{
  "prompt": "检查所有 .py 文件的 import 是否有循环依赖",
  "provider": "deepseek",
  "model": "deepseek-chat",
  "timeout_seconds": 300,
  "webhook_url": "https://..."
}
```

特点：
- 一次性返回完整结果（JSON），不做 SSE 流
- 支持 `webhook_url` 异步回调（长时间任务）
- 错误详情结构完整返回

### 8.3 定时任务手动触发

`POST /api/scheduled-tasks/{task_id}/trigger` — 立即执行一次（不等 cron）

---

## 九、前端适配

### 9.1 认证层改造

| 组件/模块 | 当前 | 改后 |
|-----------|------|------|
| `useAuthStore` | JWT + CSRF，login/logout 流程 | 存 `api_key`，直接可用 |
| `LoginPage` | 用户名密码登录 | API Key 配置页（首次/换 Key） |
| `RegisterPage` | 注册页 | 删除 |
| 路由守卫 | 未登录 → `/login` | 无 Key → 配置页 |
| SettingsPage 用户管理 | 用户列表/角色管理 | 删除 |
| `authApi.ts` | login/logout/me/csrf | 仅 `/auth/me` + `/auth/rotate-api-key` |
| Axios interceptor | Cookie + CSRF Header | `Authorization: Bearer <api_key>` |

### 9.2 前端 API Key 加载顺序

```
1. localStorage.getItem("openawa_api_key")
2. import.meta.env.VITE_OPENAWA_API_KEY（开发用）
3. 都没有 → 显示 API Key 配置页
4. 有 Key → /auth/me 验证 → 通过 → 进主页
```

### 9.3 前端环境变量

```
VITE_OPENAWA_API_KEY=     # 开发时可选
VITE_API_BASE_URL=         # 后端地址（默认 http://localhost:8000）
```

---

## 十、安全考虑

| 风险 | 措施 |
|------|------|
| API Key 泄露 | `.env.local` 文件权限 600；日志脱敏；Key 长度 ≥ 43 字符 (sk- + 40 chars) |
| 暴力破解 | Rate Limit 保护（60 req/min），失败后指数退避 |
| Key 轮转 | `POST /api/auth/rotate-api-key` — 旧 Key 立即失效 |
| 前端 localStorage XSS | 桌面/移动端使用系统安全存储；Web 前端建议后续加 CSP nonce |
| 公网部署 | 前面放 Nginx/Caddy 反代 + HTTPS，不直接暴露 FastAPI |

---

## 十一、启动流程

```
main.py lifespan 启动
    │
    ├─ 1. 日志初始化
    ├─ 2. 基础设施检查（litellm, provider）
    ├─ 3. 🆕 API Key 初始化（未设置则生成 + 持久化）
    ├─ 4. DB 初始化
    ├─ 5. 计费配置
    ├─ 6. RBAC 角色初始化
    ├─ 7. 🆕 Owner 用户创建/更新 + admin 角色绑定
    ├─ 8. 🗑️ 移除 sync_local_users_to_db 调用
    ├─ 9. 插件系统初始化
    ├─ 10. 后台任务启动
    └─ 11. 自主模式（可选）
```

---

## 十二、文件变更清单

### 后端新增
| 文件 | 说明 |
|------|------|
| `backend/core/owner.py` | Owner 用户管理辅助函数 |

### 后端修改
| 文件 | 变更 |
|------|------|
| `backend/config/settings.py` | 新增 `OPENAWA_API_KEY` 字段 |
| `backend/api/dependencies.py` | `get_current_user` 支持 API Key |
| `backend/api/routes/auth.py` | 删除 `/register`，简化 login/logout，新增 `/rotate-api-key` |
| `backend/main.py` | startup 新增 API Key 初始化和 owner 创建，移除 user sync |
| `backend/api/routes/chat.py` | ChatMessage 新增 `autonomous` 字段 |
| `backend/api/routes/scheduled_tasks.py` | 新增 `/trigger` 端点 |
| `backend/core/executor.py` | 自主模式下跳过权限确认 |
| `backend/security/permission_manager.py` | 单用户模式下 `user_id` 使用 owner.id |

#### 后端删除
| 文件 | 说明 |
|------|------|
| `backend/config/users.yaml` | 不再需要 |
| `backend/config/local_users.py` | 用户同步已废弃 |

### 前端修改
| 文件 | 变更 |
|------|------|
| `src/shared/store/authStore.ts` | JWT → API Key |
| `src/shared/api/apiClient.ts` | Cookie/CSRF → Bearer + API Key |
| `src/features/auth/LoginPage.tsx` | 登录页 → API Key 配置页 |
| `src/features/auth/RegisterPage.tsx` | 删除 |
| `src/features/settings/SettingsPage.tsx` | 移除用户管理 tab |
| `src/shared/api/authApi.ts` | 简化 API 调用 |
| 路由配置 | 移除 `/register`，调整守卫逻辑 |

---

## 十三、API 端点变更汇总

| 端点 | 当前 | 改后 |
|------|------|------|
| `POST /api/auth/register` | 返回 403 | 删除 |
| `POST /api/auth/login` | JWT 登录 | API Key 验证 + 返回确认信息（可选保留 JWT 发放） |
| `POST /api/auth/logout` | JWT 登出 | 保留（JWT 兼容） |
| `GET /api/auth/me` | JWT 用户信息 | 用 API Key 也能调用 |
| `GET /api/auth/csrf-token` | 返回 CSRF | 保留但 API Key 模式不需要 |
| 🆕 `POST /api/auth/rotate-api-key` | — | 轮转 API Key |
| `POST /api/chat/send` | 聊天 | 新增 `autonomous` 参数 |
| 🆕 `POST /api/tasks/execute` | — | 非交互式任务执行 |
| 🆕 `POST /api/scheduled-tasks/{id}/trigger` | — | 手动触发定时任务 |

---

## 十四、测试策略

| 类别 | 内容 |
|------|------|
| 认证 | API Key 验证通过/失败；无 Key 时 401；Rate Limit |
| 用户初始化 | 首次启动创建 owner；重复启动不重复创建；owner 角色绑定 |
| Chat 自主模式 | `autonomous: true` 下 AI 不等待权限确认直接执行 |
| 任务执行 | `/tasks/execute` 正常返回；超时处理；webhook 回调 |
| 前端 | API Key 配置页；路由守卫；AuthStore 状态 |
| 兼容性 | JWT 登录仍可用；Cookie 认证仍可用 |
| 迁移 | 已有数据库（含多用户）启动不报错 |

---

## 十五、边界（明确不做）

- 不做 OAuth2 / 多客户端 API Key 管理
- 不实现多用户兼容（单用户就是单用户）
- 不砍任何功能模块（全功能保留）
- 不对数据库执行 ALTER TABLE
- 不做桌面/移动端 native app 开发（仅提供 API）

---

## 十六、后续扩展（不在本次范围）

- Tauri/Electron 桌面应用开发
- Android Kotlin/Jetpack Compose 客户端
- API Key 多客户端管理（如需要区分设备）
- Webhook 事件订阅系统
