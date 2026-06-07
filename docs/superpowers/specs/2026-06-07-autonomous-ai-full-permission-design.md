# AI 自主运行 + 全权限授予 设计方案

> 创建日期：2026-06-07
> 状态：已确认
> 参考：Claude Code、OpenCode、QwenPaw 安全设计

---

## 一、需求背景

当前 Open-AwA 的权限模型依赖用户实时交互——每次工具执行前需通过 PermissionManager 评估权限，ask 模式会阻塞等待用户回复。这在以下场景中存在局限性：

1. **定时/后台任务** — 通过 cron 触发的自动化任务无法等待人工确认
2. **Headless/CI 模式** — CI/CD 流水线中无人值守，需要 AI 全权执行
3. **长时自主对话** — 用户希望一次性委托任务，由 AI 独立完成全部操作

**核心需求**：提供一个仅通过 `.env` 环境变量配置的自主运行模式，AI 在全权限下自主执行，同时通过多层安全边界守住底线。

---

## 二、设计目标

| 目标 | 说明 |
|------|------|
| 唯一入口 | 仅通过 `.env` 环境变量控制，不暴露 API/UI |
| 分层安全 | 硬底线 → 工作区边界 → 网络策略 → 资源限制，四层洋葱模型 |
| 非阻塞拒绝 | 自主模式下被拒操作直接返回错误，绝不阻塞等待用户 |
| 完整审计 | 所有操作全量记录，包含决策、耗时、资源用量 |
| 防误开启 | 确认密钥机制，防止环境变量误设导致意外开启 |
| 自动回滚 | 文件操作前自动创建检查点，支持事后恢复 |

---

## 三、参考文献

### Claude Code
- **自主模式入口**：`--dangerously-skip-permissions` CLI 标志 + 环境变量组合
- **沙箱设计**：`sandbox` 模式限制文件系统和网络访问，可配置工作区边界
- **权限体系**：approve/deny/always 三级，`always` 持久化到 `settings.json`
- **环境变量**：通过 `.env` 和 `settings.json` 双层配置，启动时一次性加载

### OpenCode
- **权限模型**：PermissionV2 使用 `ask/allow/deny` 三元组 + 通配符匹配
- **工具优先级**：LOCATION(100) > APPLICATION(50) > MCP(10)
- **持久化权限**：`PermissionSaved` 表，`always` 决策跨会话生效
- **代理权限**：build（全权限）/ plan（只读）/ Explore（只读）三级代理

### QwenPaw
- **环境配置**：通过 `.env` 控制自主模式和 API 密钥
- **工作区隔离**：基于 workspace root 的文件访问边界
- **命令沙箱**：白名单 + 黑名单双层命令过滤

---

## 四、环境变量设计

所有自主模式配置项，仅通过 `.env` 文件定义：

```bash
# ═══════════════════════════════════════════════════════
# AI 自主运行配置（仅通过 .env 配置，不暴露 API/UI）
# 所有项均有安全默认值
# ═══════════════════════════════════════════════════════

# ──── 主开关 ──────────────────────────────────────────
# 开启后 AI 不再向用户请求权限确认
# 类型: bool  默认: false
OPENAWA_AUTONOMOUS_MODE=false

# ──── 确认密钥 ────────────────────────────────────────
# 设置后，开启自主模式需同时提供此密钥，防止误设环境变量
# 类型: str  默认: ""
OPENAWA_AUTONOMOUS_CONFIRM_KEY=

# ──── 生效范围 ────────────────────────────────────────
# 逗号分隔：scheduled(定时任务), chat(对话), ci(Headless)
# 默认: 空（需明确指定，防止意外全局生效）
OPENAWA_AUTONOMOUS_SCOPE=

# ──── 工作区边界 ──────────────────────────────────────
# 文件操作的硬边界，路径穿越到此外即拒绝
# 自主模式下必填，不设置或路径不可写则启动失败
OPENAWA_AUTONOMOUS_WORKSPACE=

# ──── 网络策略 ────────────────────────────────────────
# allow_all:  允许所有出站（默认）
# block_local: 拒绝内网地址 (10/8, 172.16/12, 192.168/16, 127/8)，允许外网
# allowlist:  仅允许白名单内的地址
# 默认: allow_all
OPENAWA_AUTONOMOUS_NETWORK_POLICY=allow_all

# 网络白名单（逗号分隔的 CIDR），仅 NETWORK_POLICY=allowlist 时生效
OPENAWA_AUTONOMOUS_NETWORK_ALLOWLIST=

# ──── 命令安全 ────────────────────────────────────────
# 命令执行超时（秒），默认 120
OPENAWA_AUTONOMOUS_CMD_TIMEOUT=120

# 总任务超时（秒），默认 1800（30 分钟）
OPENAWA_AUTONOMOUS_TASK_TIMEOUT=1800

# 内存限制（MB），默认 1024
OPENAWA_AUTONOMOUS_MEMORY_LIMIT=1024

# ──── 自动回滚 ────────────────────────────────────────
# 文件操作前自动创建检查点，默认开启
OPENAWA_AUTONOMOUS_CHECKPOINT_ENABLED=true

# ──── 审计日志 ────────────────────────────────────────
# minimal: 仅记录被拒绝的操作
# full:    记录所有操作（默认）
OPENAWA_AUTONOMOUS_AUDIT_LEVEL=full

# ──── 通知告警 ────────────────────────────────────────
# 危险操作通知 Webhook URL（如 Slack/Discord）
# 即使操作未被拒绝，也可选推送到此 URL 供人工事后审查
OPENAWA_AUTONOMOUS_ALERT_WEBHOOK=
```

### 配置验证规则

启动时 `AutonomousModeManager` 执行以下验证：

1. `OPENAWA_AUTONOMOUS_MODE=true` 时：
   - 若 `CONFIRM_KEY` 已设置，必须同时设置且匹配
   - `SCOPE` 不能为空（至少指定一个有效范围）
   - `WORKSPACE` 必须指向存在且可写的目录
   - `NETWORK_POLICY` 必须是三个有效值之一
   - `CMD_TIMEOUT` 必须 > 0 且 ≤ 600
   - `TASK_TIMEOUT` 必须 > 0 且 ≤ 86400
   - `MEMORY_LIMIT` 必须 > 0 且 ≤ 16384
2. 任一验证失败 → 拒绝启动，输出明确错误信息
3. 验证通过 → 初始化单例，写入启动审计日志

---

## 五、系统架构

### 5.1 安全洋葱模型（4 层）

```
用户请求 / 定时任务 / CI 触发
             │
             ▼
┌─────────────────────────────────────────────────────┐
│  ① 硬底线层 (HardDenyLayer)                          │
│     无论何种模式、任何配置，以下操作永远返回错误       │
│                                                      │
│   · 系统破坏命令: rm -rf /, format, shutdown, reboot │
│   · 敏感系统目录: /etc/shadow, /etc/passwd, /proc/*, │
│                   /sys/*, /boot/*                     │
│   · 修改自身: .env, .env.local, CLAUDE.md,            │
│              settings.json, config/*.py               │
│   · 提权操作: sudo, su, chmod 777 关键路径            │
│                                                      │
│   → 被拒绝时: 立即返回 {"ok": False, "error": "..."} │
│     绝不阻塞，绝不询问用户                             │
└─────────────────────────────────────────────────────┘
             │ (通过)
             ▼
┌─────────────────────────────────────────────────────┐
│  ② 工作区边界层 (WorkspaceBoundary)                   │
│     文件操作限制在 WORKSPACE 根目录内                  │
│                                                      │
│   · 路径穿越检测: ../ 序列、绝对路径越界              │
│   · 符号链接解析后二次校验                            │
│   · 禁止创建硬链接                                    │
│                                                      │
│   → 被拒绝时: 立即返回错误 + 拒绝原因 + 建议          │
└─────────────────────────────────────────────────────┘
             │ (通过)
             ▼
┌─────────────────────────────────────────────────────┐
│  ③ 网络边界层 (NetworkPolicy)                         │
│     根据配置策略过滤网络出站请求                       │
│                                                      │
│   allow_all:   无限制（默认）                         │
│   block_local: 拒绝 RFC 1918 内网段，允许外网          │
│   allowlist:   仅允许白名单 CIDR                       │
│                                                      │
│   → 被拒绝时: 返回错误 + 被拒绝的地址 + 当前策略      │
└─────────────────────────────────────────────────────┘
             │ (通过)
             ▼
┌─────────────────────────────────────────────────────┐
│  ④ 资源限制层 (ResourceLimits)                        │
│     防止失控进程耗尽系统资源                           │
│                                                      │
│   · 单命令超时: CMD_TIMEOUT 秒 (默认 120)            │
│   · 内存限制:   MEMORY_LIMIT MB (默认 1024)          │
│   · 总任务超时: TASK_TIMEOUT 秒 (默认 1800)          │
│   · 自动终止超出限制的进程                            │
│                                                      │
│   → 被拒绝时: 返回超时/资源耗尽错误 + 当前用量        │
└─────────────────────────────────────────────────────┘
             │ (通过)
             ▼
        执行操作 + 审计日志 + 检查点创建
```

### 5.2 文件结构

```
backend/core/autonomous/
├── __init__.py              # 导出 AutonomousModeManager 单例
├── config.py                # AutonomousConfig Pydantic 模型 + 环境变量读取
├── manager.py               # AutonomousModeManager 单例（生命周期管理）
├── hard_deny.py             # 硬底线检查器（命令/路径/配置保护）
├── workspace_boundary.py    # 工作区路径边界校验
├── network_policy.py        # 网络出站策略执行
├── resource_limits.py       # CPU/内存/时间 资源限制
├── checkpoint.py            # 文件操作自动检查点
├── audit.py                 # 自主模式专用审计日志
└── tests/
    ├── test_config.py
    ├── test_hard_deny.py
    ├── test_workspace_boundary.py
    ├── test_network_policy.py
    └── test_checkpoint.py
```

### 5.3 数据流

```
main.py lifespan 启动
       │
       ▼
ConfigManager 加载 .env → AutonomousConfig
       │
       ├─ OPENAWA_AUTONOMOUS_MODE=false → 跳过，正常模式
       │
       └─ OPENAWA_AUTONOMOUS_MODE=true
              │
              ├─ 1. 验证 CONFIRM_KEY
              ├─ 2. 验证 SCOPE 非空
              ├─ 3. 验证 WORKSPACE 存在且可写
              ├─ 4. 初始化 AutonomousModeManager 全局单例
              ├─ 5. 注册中间件（网络策略拦截器）
              └─ 6. 记录启动审计日志

executor._execute_tool_call() 每次调用
       │
       ▼
if autonomous_manager.is_autonomous():
    │
    ├──→ hard_deny.check(action, command, params)
    │        ├─ 系统破坏命令? → DENY + 返回错误
    │        ├─ 敏感路径访问? → DENY + 返回错误
    │        └─ 修改自身配置? → DENY + 返回错误
    │
    ├──→ workspace_boundary.check(file_path)
    │        ├─ 路径穿越? → DENY + 返回错误
    │        ├─ 符号链接越界? → DENY + 返回错误
    │        └─ 通过 → 继续
    │
    ├──→ network_policy.check(url) [if applicable]
    │        ├─ allow_all → 通过
    │        ├─ block_local + 目标内网? → DENY + 返回错误
    │        └─ allowlist + 不在白名单? → DENY + 返回错误
    │
    ├──→ checkpoint.create(file_path) [if mutating operation]
    │        └─ 保存文件快照
    │
    ├──→ audit.record(action, params, decision, context)
    │        └─ 写入审计日志
    │
    └──→ 执行工具（带超时和内存限制）
else:
    → 正常流程：PermissionManager.ask/assert

发生超时/内存溢出时:
    ├──→ resource_limits.enforce()
    └──→ 终止进程 → 返回错误 + 资源使用信息
```

### 5.4 AutonomousModeManager 核心接口

```python
class AutonomousModeManager:
    """自主运行模式管理器（单例）"""

    # ── 属性 ──
    config: AutonomousConfig         # 完整配置
    is_autonomous: bool              # 是否开启自主模式
    scope_scheduled: bool            # 定时任务场景
    scope_chat: bool                 # 对话场景
    scope_ci: bool                   # CI 场景

    # ── 方法 ──
    def is_active_for(self, scope: str) -> bool:
        """判断当前 scope 是否启用自主模式"""

    def is_command_hard_denied(self, command: str) -> tuple[bool, str]:
        """检查命令是否被硬底线拒绝 → (是否拒绝, 原因)"""

    def is_path_allowed(self, path: Path) -> tuple[bool, str]:
        """检查路径是否在工作区边界内 → (是否允许, 原因)"""

    def is_network_allowed(self, url: str) -> tuple[bool, str]:
        """检查网络目标是否允许 → (是否允许, 原因)"""

    def check_all(self, action: str, params: dict) -> Optional[Dict]:
        """一站式检查：返回 None 表示全部通过，返回 dict 表示拒绝原因"""

    def record_audit(self, event: dict) -> None:
        """记录审计事件"""

    def get_effective_config_summary(self) -> dict:
        """获取当前安全配置摘要（不含密钥）"""
```

---

## 六、硬底线清单（不可逾越）

以下操作在任何自主模式下**永远拒绝**，不询问用户，直接返回错误：

### 6.1 系统破坏命令

| 模式 | 说明 |
|------|------|
| `rm -rf /` | 递归删除根目录 |
| `rm -rf /*` | 通配符删除根目录 |
| `del /s /q \\*` | Windows 系统盘删除 |
| `format` | 格式化磁盘 |
| `mkfs.*` | 创建文件系统 |
| `dd of=/dev/*` | 直接写入块设备 |
| `shutdown` / `reboot` / `halt` | 系统关机/重启 |
| `sudo` / `su` | 提权操作 |
| `:(){ :\|:& };:` | Fork 炸弹 |

### 6.2 敏感系统路径（读写均拒绝）

| 路径 | 说明 |
|------|------|
| `/etc/shadow`、`/etc/passwd` | 用户密码文件 |
| `/etc/sudoers`、`/etc/sudoers.d/*` | sudo 配置 |
| `/proc/*`、`/sys/*` | 内核虚拟文件系统 |
| `/boot/*` | 引导文件 |
| `~/.ssh/*`、`/root/.ssh/*` | SSH 密钥 |
| `C:\Windows\System32\*` | Windows 系统目录 |

### 6.3 自身配置文件（修改拒绝，可读）

| 文件 | 说明 |
|------|------|
| `*.env`、`*.env.local` | 环境变量文件 |
| `CLAUDE.md` | 项目指令文件 |
| `config/settings.py` | 后端设置 |
| `.claude/settings.json` | Claude Code 设置 |
| `scripts/code-audit.ps1` | 审计脚本自身 |

### 6.4 危险网络目标（始终拒绝）

| 目标 | 说明 |
|------|------|
| `169.254.0.0/16` | 链路本地地址（AWS 元数据等） |
| `metadata.google.internal` | GCP 元数据端点 |
| `169.254.169.254` | AWS/云元数据端点 |
| `localhost:*/admin` 等 | 本地管理端口（可配置） |

---

## 七、非阻塞拒绝机制

这是自主模式最关键的设计原则：

### 7.1 核心原则

> 自主模式下，权限检查返回的 `Deny` 必须是**即时决策**，绝不创建 `PermissionRequest` 等待用户回复。

```python
# 正确做法：立即返回错误
if autonomous_manager.is_autonomous():
    denied, reason = autonomous_manager.is_command_hard_denied(command)
    if denied:
        return {"ok": False, "error": reason, "denied_by": "hard_deny"}
    # 继续执行...

# 错误做法：创建 PermissionRequest 阻塞等待
# ❌ await permission_manager.ask(...)  # 这会阻塞直至超时
```

### 7.2 错误返回格式

所有拒绝均返回统一格式，让 AI 能理解原因并尝试替代方案：

```json
{
  "ok": false,
  "error": "硬底线拒绝: 命令 'rm -rf /tmp/*' 匹配了禁止模式 'rm -rf'。请使用更安全的单文件删除方式。",
  "denied_by": "hard_deny",
  "recoverable": false,
  "suggestion": "请尝试逐个删除文件，或使用 trash/回收站替代方案"
}
```

字段说明：
- `denied_by`: `hard_deny` | `workspace` | `network` | `resource`
- `recoverable`: AI 是否可以尝试替代方案（硬底线为 `false`，网络/资源为 `true`）
- `suggestion`: 给 AI 的替代方案建议

### 7.3 各类拒绝的 AI 处理建议

| 拒绝类型 | recoverable | AI 行为 |
|---------|-------------|---------|
| hard_deny | false | 跳过该操作，告知用户此操作不可执行 |
| workspace | true | 检查路径，尝试将操作限定在工作区内 |
| network | true | 检查 URL，尝试使用允许范围内的替代地址 |
| resource | true | 减少请求量、拆分任务、或增加超时重试 |

---

## 八、审计日志

### 8.1 日志等级

| 等级 | 记录内容 |
|------|---------|
| `full`（默认） | 所有操作：允许的 + 拒绝的 + 资源超限的 |
| `minimal` | 仅记录被拒绝的操作和资源超限事件 |

### 8.2 日志格式（JSONL）

```json
{
  "timestamp": "2026-06-07T12:00:00.000Z",
  "session_id": "sess_abc123",
  "task_id": "task_xyz789",
  "mode": "autonomous",
  "scope": "chat",
  "action": "execute_command",
  "parameters": {
    "command": "npm run build"
  },
  "decision": "allowed",
  "denied_by": null,
  "workspace_boundary": {
    "requested_path": "/app/workspace/src",
    "workspace_root": "/app/workspace",
    "violation": false
  },
  "network_target": null,
  "execution_time_ms": 5234,
  "resource_usage": {
    "memory_mb": 45,
    "cpu_percent": 12.3
  },
  "checkpoint_id": null,
  "error": null
}
```

### 8.3 审计日志存储

- 路径：`{WORKSPACE}/.openawa/audit/{YYYY-MM-DD}.jsonl`
- 格式：每行一条 JSON，追加写入
- 轮转：按天轮转，保留 90 天
- 查询：通过 `GET /api/system/audit?date=2026-06-07` 查询（需管理员权限）

---

## 九、通知告警

### 9.1 Webhook 触发条件

即使操作未被拒绝，以下情况也可选推送到 Webhook：

| 事件 | Always | Optional |
|------|--------|----------|
| 自主模式启动/关闭 | 是 | - |
| 硬底线拒绝事件 | 是 | - |
| 资源超限（OOM/超时） | 是 | - |
| 文件修改（批量 > 10 文件） | - | 是 |
| 网络请求（首次新域名） | - | 是 |

### 9.2 Webhook Payload

```json
{
  "event": "autonomous.hard_deny",
  "severity": "warning",
  "timestamp": "2026-06-07T12:00:00Z",
  "message": "AI 试图执行被禁止命令: rm -rf /tmp/cache",
  "session_id": "sess_abc123",
  "suggestion": "已向 AI 返回错误，AI 应尝试替代方案"
}
```

---

## 十、启动流程集成

### 10.1 main.py lifespan 修改点

```python
# main.py lifespan startup
from core.autonomous import AutonomousModeManager, AutonomousConfig

async def startup():
    # ... 现有初始化 ...

    # 17. 自主模式初始化（在所有其他初始化之后）
    autonomous_config = AutonomousConfig.from_env()
    autonomous_manager = AutonomousModeManager(autonomous_config)
    if autonomous_manager.is_autonomous:
        if not autonomous_config.validate():
            logger.error("自主模式配置验证失败，拒绝启动")
            raise SystemExit(1)
        autonomous_manager.initialize()
        logger.warning(
            f"[SECURITY] 自主运行模式已开启: "
            f"scope={autonomous_config.scope}, "
            f"workspace={autonomous_config.workspace_root}"
        )
```

### 10.2 executor.py 拦截点修改

```python
# executor._execute_tool_call() 开头
async def _execute_tool_call(self, tool_call, context, ...):
    # 自主模式：先做安全拦截
    auth_manager = get_autonomous_manager()
    if auth_manager.is_autonomous_for(context.get("scope", "chat")):
        denial = auth_manager.check_all(action, params)
        if denial:
            return denial  # {"ok": False, "error": "...", "denied_by": "..."}

    # 原有权限检查...
```

---

## 十一、禁止事项（反模式）

| 禁止 | 原因 |
|------|------|
| 通过 API 修改 `OPENAWA_AUTONOMOUS_MODE` | 必须仅 .env 控制 |
| 自主模式下的 PermissionManager.ask() | 会阻塞导致卡住 |
| 跳过 hard_deny 检查 | 安全底线不可绕过 |
| 默认开启自主模式 | 必须用户明确 opt-in |
| 在日志中记录完整 API Key | 敏感信息脱敏 |

---

## 十二、测试策略

| 测试类别 | 内容 |
|---------|------|
| 配置验证 | 各种非法配置组合应拒绝启动 |
| 硬底线 | 所有禁止命令/路径/文件应返回错误 |
| 工作区边界 | 路径穿越、符号链接越界应拦截 |
| 网络策略 | 三种策略的允/拒行为验证 |
| 资源限制 | 超时、内存溢出自动终止 |
| 非阻塞 | 被拒操作响应时间 < 1ms（无等待） |
| 审计日志 | 全量/最小日志级别的正确记录 |
| 集成测试 | scheduled/chat/ci 三种 scope 端到端 |

---

## 十三、后续扩展（不在本次范围）

- 按 Agent 类型差异化配置（build 全权 vs plan 只读等）
- 自主模式的 token 消耗预算上限
- 操作前模拟（dry-run）模式
- 第三方安全审计集成（SOC2 合规日志格式）
