# 通过 ACP 集成新 Coding Agent

本文档介绍如何通过 ACP（Agent Client Protocol）为 Open-AwA 集成新的本地 vibe coding Agent。

## 背景

Open-AwA 通过 ACP 协议统一调用本地 vibe coding 应用（如 Claude Code、Codex、OpenClaw、OpenCode）。每个 Agent 通过一个 Python 配置文件声明其启动命令、参数、环境变量与解析模式，由 `acp_host/agents/` 目录下的发现机制自动注册。

集成新 Agent 的成本极低：只需新增一个配置文件，无需修改任何核心代码。

## 前置条件

1. 已安装 `acp` Python SDK（见 `backend/requirements.txt`）。SDK 缺失时 `ACPService` 会优雅降级，`run_turn` 抛 `ACPConfigurationError`。
2. 目标 Agent 的 CLI 已安装且可通过 `<command> --version` 探测（exit code == 0 视为可用）。
3. Open-AwA 后端服务可正常启动（参考 [后端架构说明](../架构/后端架构说明.md)）。

## 步骤 1: 创建 Agent 配置文件

在 `backend/acp_host/agents/` 目录下新建 `<agent_id>.py` 文件，文件中定义模块级变量 `AGENT_CONFIG: ACPAgentConfig`。

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `agent_id` | `str` | 是 | Agent 唯一标识，用于 API 路由与会话索引 |
| `name` | `str` | 是 | Agent 展示名称，用于日志与前端展示 |
| `command` | `str` | 是 | 启动 Agent 子进程的命令（可执行文件名或路径） |
| `args` | `list[str]` | 否 | 传递给启动命令的参数列表，默认 `[]` |
| `env` | `dict[str, str]` | 否 | 子进程环境变量覆盖项，默认 `{}` |
| `cwd` | `Optional[str]` | 否 | 子进程工作目录，`None` 表示继承父进程 |
| `tool_parse_mode` | `Literal["update_detail", "call_title"]` | 否 | 工具调用解析模式，默认 `update_detail` |
| `stdio_buffer_limit_bytes` | `int` | 否 | stdio 单条缓冲上限字节数，默认 1MB |
| `enabled` | `bool` | 否 | 是否启用该 Agent，默认 `True` |
| `permission_rules` | `dict[str, Any]` | 否 | Agent 权限规则配置，默认 `{}` |

## 步骤 2: 配置示例

以 `claude_code.py` 为参考：

```python
# -*- coding: utf-8 -*-
"""Claude Code agent 配置。"""
from acp_host.core import ACPAgentConfig

AGENT_CONFIG = ACPAgentConfig(
    agent_id="claude_code",
    name="Claude Code",
    command="claude",
    args=[],
    env={},
    tool_parse_mode="update_detail",
    stdio_buffer_limit_bytes=1024 * 1024,
    enabled=True,
    permission_rules={},
)
```

其他内置 Agent（`codex.py`、`openclaw.py`、`opencode.py`）结构相同，仅 `agent_id`/`name`/`command` 不同。

## 步骤 3: 验证 agent 发现

启动后端服务后调用 `GET /api/acp/agents`，确认新 agent 出现在列表中：

```bash
# 使用 API Key 认证（从 backend/.env.local 读取）
API_KEY=$(grep OPENAWA_API_KEY backend/.env.local | cut -d'=' -f2- | tr -d '"')

# 列出所有 agent
curl -s http://localhost:8000/api/acp/agents \
  -H "Authorization: Bearer $API_KEY"
```

预期响应包含新 agent 的 `id`、`name`、`command`、`enabled` 与 `available` 字段。

`discover_agents()` 扫描 `agents/` 目录下所有 `.py` 文件（除 `__init__.py`），动态导入并读取 `AGENT_CONFIG` 变量。单个模块导入失败或缺少 `AGENT_CONFIG` 时跳过，不影响其他 agent。

## 步骤 4: 验证 agent 可用性

`available` 字段通过 `is_agent_available(agent_id)` 探测：

```python
# 探测逻辑（见 agents/__init__.py）
result = subprocess.run(
    [agent_config.command, "--version"],
    capture_output=True,
    timeout=5,
)
return result.returncode == 0
```

如探测失败，请确认：

1. 命令在 `PATH` 中可执行（终端运行 `<command> --version` 返回 0）
2. 命令有执行权限（POSIX 系统 `chmod +x`）
3. 探测超时不超过 5 秒

`available=False` 不会阻止会话创建，但 `run_turn` 拉起子进程时可能失败。

## OpenCode 项目内安装与 ACP 启动

OpenCode 使用 ACP 时必须以 `opencode acp` 启动。Open-AwA 的内置 OpenCode 配置已包含 `args=["acp"]`，并会优先使用会话工作目录下的 `node_modules/.bin/opencode`，因此无需把 OpenCode 全局安装到系统 PATH。

在 Vibe Coding 页面选择 OpenCode，填写已配置到 `ACP_ALLOWED_WORKDIRS` 白名单内、且含有 `package.json` 的 Node.js 项目目录，然后点击“安装 OpenCode”并确认。后端固定执行：

```text
npm install --save-dev opencode-ai@latest --no-audit --no-fund
npm audit --audit-level=high --json
```

该接口不接收自定义包名或任意 shell 命令；npm 子进程只保留运行所需环境变量，避免将服务密钥交给依赖安装脚本。安装后可直接创建 ACP 会话并在会话面板下发任务。

## 步骤 5: 测试 ACP 会话

创建会话并发送 prompt 验证 SSE 流：

```bash
# 1. 创建会话
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/acp/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"agent":"<your_agent_id>","cwd":"."}' | python -c "import sys,json;print(json.load(sys.stdin)['session_id'])")

# 2. 发送 prompt（SSE 流式响应）
curl -N -X POST http://localhost:8000/api/acp/sessions/$SESSION_ID/prompt \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"hello"}'
```

预期收到 SSE 帧，事件类型包括 `text`、`tool`、`status`、`usage`、`result`。收到 `permission` 事件时需调用 permission 端点恢复：

```bash
curl -X POST http://localhost:8000/api/acp/sessions/$SESSION_ID/permission \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"option_id":"<option_id>"}'
```

## 调试技巧

- 查看启动日志：`var/logs/` 下的日志文件，搜索 `event="acp_session_created"` 与 `module="acp"` 关键字
- 确认 `acp` SDK 已安装：`pip show acp`，缺失时 `run_turn` 抛 `ACPConfigurationError("acp SDK not installed")`
- 确认 agent 配置被加载：`discover_agents()` 返回的字典键应包含新 `agent_id`
- 子进程拉起失败：检查 `command` 路径与 `env` 环境变量是否正确

## 安全注意事项

### Permission 适配器

`ACPPermissionAdapter` 将 Agent 的工具调用转换为可挂起的审批请求。新 Agent 默认继承全局硬阻断策略，无需额外配置。

### 硬阻断策略

以下命令子串会被直接拒绝，不进入用户审批流程：

- `rm -rf /`
- `sudo rm -rf`
- `mkfs`
- `dd if=`

如需扩展黑名单，修改 `backend/acp_host/permissions.py` 中的 `BLOCKED_COMMAND_PATTERNS` 元组。

### 路径越权防护

`POST /api/acp/sessions` 的 `cwd` 参数通过 `_validate_cwd` 校验，必须位于 `_ALLOWED_WORKSPACE_ROOTS`（当前工作目录及其子目录）内。Agent 子进程的工作目录受此约束，无法访问工作区外的路径。

### 会话隔离

ACP 会话按 `chat_id = f"{user_id}:{session_id}"` 隔离，不同用户、不同会话的 Agent 子进程互不影响。模块级 `_acp_services` 字典按 agent 标识索引 service 实例。
