# Open-AwA LiteLLM 网关层痛点分析

> 分析日期：2026-05-04
> 分析范围：`backend/core/litellm_adapter.py`, `backend/core/model_service.py`, `backend/core/executor.py`, `backend/core/agent.py`, `backend/billing/`, `backend/config/`

---

## 一、架构层面

### 痛点1：双路径架构，model_service.py 大量死代码

系统中存在两条调用大模型的路径，但实际只有一条在使用：

| 路径 | 调用链 | 状态 |
|------|--------|------|
| 路径A | `executor.py → litellm_adapter.py → litellm.acompletion()` | 生产使用 |
| 路径B | `model_service.py → httpx.AsyncClient` | 基本废弃 |

`model_service.py` (667行) 保留了完整的 HTTP 调用逻辑（`build_provider_request`, `send_with_retries`, `send_stream_with_retries`, `discover_ollama_models`, `get_provider_connection_status`），但几乎不被任何模块引用。这造成了：
- 新人阅读代码时分不清哪条是主路径
- 维护两套逻辑但实际只用一套
- `Ollama` 模型发现和连接检测功能在两处重复实现

### 痛点2：无负载均衡与故障转移

LiteLLM 本身提供了 `Router` 和 `AdvancedRouter` 模块，支持多实例负载均衡、重试、冷却、故障转移。但当前代码**完全没有使用**这些功能：
- 没有任何 `litellm.Router` 的初始化或使用
- 每个供应商只有一个 endpoint，无法配置多实例
- 故障转移策略完全依赖手动实现的熔断器，不能跨实例路由

### 痛点3：无流量控制与速率限制

当前没有任何速率限制（Rate Limiting）实现：
- 无令牌桶/漏桶算法
- 无并发请求上限控制
- 无供应商级别的配额管理
- 多个用户同时请求同一供应商时无任何协调

---

## 二、实现层面

### 痛点4：双重重试导致指数级放大

`litellm_adapter.py` 中存在两层层叠的重试机制：

```
LiteLLM 内建重试 (num_retries=2)  ×  适配层外层重试 (最多3次)  =  最多9次请求
```

且两层的退避策略互不协调，可能导致：
- 对上游供应商造成不必要的压力
- 用户等待时间过长（外层重试间隔最长 30s，叠加内层重试延迟）
- 429 限流响应不能统一处理

### 痛点5：无类型安全，依赖字典隐式契约

```python
# litellm_adapter.py 返回无类型字典
def litellm_chat_completion(...) -> Dict[str, Any]:
    return {"ok": True, "response": "...", "provider": "...", "model": "..."}

def litellm_chat_completion_stream(...) -> AsyncGenerator[Dict[str, Any], None]:
    yield {"content": "...", "reasoning_content": "..."}
    yield {"type": "tool_calls", "tool_calls": [...]}
    yield {"error": {...}}
```

调用方（`executor.py`, `agent.py`）依赖隐式字段名，字段拼写错误只能在运行时发现。返回值和生成器产出的字典结构无编译时检查。

### 痛点6：熔断器状态纯内存，重启丢失

```python
# litellm_adapter.py 第161-171行
self._circuit_breakers: Dict[str, CircuitBreaker] = {}
```

- 服务重启后所有熔断器状态归零
- 异常供应商在重启后又获得 5 次失败配额
- 多进程部署时各进程独立计数，状态不同步
- 无共享存储（Redis / DB）持久化

### 痛点7：流式处理代码分散在三个文件中

```
litellm_adapter.py  →  原始生成器（yield chunk / tool_calls / error）
executor.py         →  包裹层（提取 reasoning，record_hook，错误标准化）
agent.py            →  最终消费（SSE 事件发射，工具循环）
```

状态管理跨越三层，任一层异常都可能破坏流。消费者中途取消（如前端关闭连接）时，底层生成器的清理逻辑不统一。

### 痛点8：工具调用错误处理粗糙

`executor.py` 第816行简单的"连续3次错误提前终止"逻辑：
- 不区分可重试错误（429/5xx）和不可重试错误（400/401）
- 不根据错误类型调整策略（如 401 应立即终止，而不是等3次）
- 工具执行和 LLM 调用的错误混在一起计数

---

## 三、配置与管理层面

### 痛点9：供应商配置硬编码，新增需改源码

```python
# executor.py 第92-100行 — 硬编码端点
self.default_provider_endpoints = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    ...
}

# executor.py 第101-105行 — 硬编码 API Key 字段
self.provider_api_key_fields = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY"
}
```

新增一个供应商需要修改 3-4 个文件。alibaba、moonshot、zhipu 等中国供应商的 API Key 没有独立的环境变量回退。

### 痛点10：API Key 明文存储

`ModelConfiguration.api_key` 在数据库中明文保存。虽然有 Fernet 加密工具类，但并未应用于此字段。任何能访问数据库的人都能直接读取所有 API Key。

### 痛点11：模型能力数据两处存储，无自动同步

- `backend/config/pricing/model_capabilities.json` (1386行)
- `ModelConfiguration` 数据库表

初始化时 JSON 导入 DB，但后续 JSON 更新无自动同步机制。两处数据会逐渐漂移。

### 痛点12：LiteLLM 模型名映射脆弱

```python
# 部分供应商使用 openai/ 前缀映射（alibaba/moonshot/zhipu）
PROVIDER_MODEL_PREFIX_MAP = {
    "alibaba": "openai/",
    "moonshot": "openai/",
    "zhipu": "openai/"
}
```

这些供应商的 API 如有细微格式差异（错误结构、`max_tokens` 参数名、thinking 参数格式差异），LiteLLM 的 OpenAI 兼容路由无法正确处理。

---

## 四、可观测性层面

### 痛点13：计费未集成到网关层

核心调用路径（`litellm_adapter.py`）中**没有任何计费记录代码**。Token 用量记录依赖上层 `agent.py` 的行为日志器和对话记录器间接完成，不仅延迟，而且：
- 如果其他模块直接调用 litellm_adapter（绕过 agent），用量将丢失
- 异步流场景下 token 统计可能不准确

### 痛点14：无请求级别追踪

- 无分布式追踪（Trace ID）贯穿整个调用链路
- 工具调用的子请求无法关联到父请求
- 调试时难以还原单次请求的完整链路

### 痛点15：缺少关键测试覆盖

现有测试 `test_litellm_adapter.py` (481行) 缺失以下场景：
- 熔断器状态转换逻辑
- 重试与指数退避正确性
- 并发请求下的竞态条件
- 流式消费者中途取消的资源释放
- 超时场景下的行为
- API Key 解析优先级链路

---

## 五、安全层面

### 痛点16：API Key 日志泄露风险

`logging.py` 的 `sanitize_for_logging` 仅对固定键名脱敏。请求 payload 中的自定义参数名、嵌套字典中的 key 值可能被完整记录。

### 痛点17：LiteLLM 依赖范围宽松

```txt
# requirements.txt
litellm>=1.80.0,<2.0.0
```

大版本范围意味着可能引入不兼容的 API 变更或安全漏洞（LiteLLM 更新频繁）。

---

## 总结：替换 LiteLLM 的核心诉求

| 维度 | 当前状态 | 期望 |
|------|---------|------|
| 负载均衡 | 无 | 多实例加权轮询/最少连接 |
| 故障转移 | 手动熔断器（内存） | 自动健康检查 + 跨实例切换 |
| 速率限制 | 无 | 令牌桶/滑动窗口，供应商级配额 |
| 类型安全 | Dict[str, Any] | Pydantic/TypedDict 类型约束 |
| 配置管理 | 硬编码 + DB | YAML/TOML 声明式配置，热加载 |
| API Key | 明文 | 加密存储 + 环境变量/Secret Manager |
| 可观测性 | 分散 | 统一 Trace，请求级追踪 |
| 重试 | 双层冲突 | 统一策略，指数退避 + jitter |
| 测试 | 覆盖不足 | 核心路径 90%+ 覆盖 |
| 供应商扩展 | 改源码 | 配置文件新增，无需改代码 |
| 中国供应商 | openai/ 映射 | 原生支持，差异化适配 |
