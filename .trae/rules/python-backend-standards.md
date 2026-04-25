# Python 后端开发规范

## 异常处理

### 1.1 使用具体异常类型
```python
# 正确: 区分具体异常类型
try:
    result = await llm_call()
except LLMTimeoutError:
    return fallback_response()
except LLMValidationError:
    return invalid_request_response()
except LLMError as e:
    logger.error("LLM调用失败", exc_info=e)
    raise

# 错误: 过于宽泛的异常捕获
try:
    result = await llm_call()
except Exception:
    return "出错了"
```

### 1.2 禁止静默吞异常
```python
# 正确: 至少记录日志
try:
    await process_message(msg)
except MessageError as e:
    logger.warning("消息处理异常", exc_info=e)
    return graceful_error_response(e)

# 错误: try/except/pass (bandit B110)
try:
    await process_message(msg)
except Exception:
    pass
```

### 1.3 关键路径必须传播错误
- Agent 执行、计费扣减、记忆持久化等关键路径的错误必须传播到上层
- 使用自定义异常类（继承 `AppError`）携带上下文
- API 层统一转换为用户友好的错误消息

### 1.4 资源泄露防护
- `response` 等 HTTP/流式对象必须在使用后 close
- 使用 `try/finally` 或 `contextlib.closing` 确保资源释放
- 数据库 session 使用 `with db_session() as session:` 上下文管理器

## 输入验证

### 2.1 所有外部输入必须有 Schema 校验
```python
# 正确: 使用 Pydantic schema 定义请求体
class ChatRequest(BaseModel):
    message: str = Field(..., max_length=32000, description="用户消息")
    conversation_id: str = Field(..., description="会话ID")
    stream: bool = Field(default=False)

# 错误: 使用裸 Dict
def save_config(data: Dict[str, Any]): ...
```

### 2.2 文件上传安全
- 校验 `Content-Length` 和文件大小（最大 50MB）
- 解压 ZIP 前校验总大小、文件数量
- 解压时校验成员路径，防止路径穿越
- 校验文件 MIME 类型白名单

### 2.3 命令执行安全
- 使用 `shlex.quote()` 转义所有 shell 参数
- 在隔离环境（Docker/子进程）中执行
- 限制网络和文件系统访问

### 2.4 路径安全
```python
from pathlib import Path

ALLOWED_DIR = Path("/data/sandbox")

def safe_path(user_path: str) -> Path:
    resolved = (ALLOWED_DIR / user_path).resolve()
    if not str(resolved).startswith(str(ALLOWED_DIR)):
        raise SecurityError("路径越权")
    return resolved
```

## 日志记录

### 3.1 结构化日志
- 使用 `structlog` 或 `logging.LoggerAdapter` 绑定上下文
- 每条日志必须包含：`request_id`、`user_id`、`conversation_id`
- 关键事件使用结构化格式，便于日志检索

### 3.2 日志级别规范
- `DEBUG`: 开发调试信息
- `INFO`: 正常操作的关键生命周期事件（请求开始/完成、工具调用）
- `WARNING`: 预期内的异常（重试、降级、限流触发）
- `ERROR`: 未预期的异常（需人工关注的问题）
- `CRITICAL`: 系统级故障（需立即响应）

### 3.3 敏感信息保护
- 禁止记录：令牌、密钥、密码、个人信息
- 禁止记录：完整的请求/响应体（仅记录结构化的摘要）
- 使用 `PII_REMOVER` 过滤器脱敏

### 3.4 请求关联
- 在 API 入口生成唯一 `trace_id`
- 通过 `contextvars` 传播到整个调用链
- 异步任务链保持 `trace_id` 传递

## 并发安全

### 4.1 全局状态管理
- 避免模块级可变全局变量
- 必须使用时，使用 `asyncio.Lock` 或 `threading.Lock` 保护
- 优先使用依赖注入传递状态

### 4.2 异步协程安全
- 事件循环中禁止阻塞调用（`time.sleep()`、同步 I/O）
- 使用 `asyncio.wait_for` 设置超时
- 创建 Task 时注册回调处理异常

### 4.3 数据库 Session 安全
- 会话必须绑定到请求生命周期
- 使用 `FastAPI Depends` 或上下文管理器管理
- 异常时确保回滚和关闭

## 类型标注

### 5.1 函数签名必须完整
```python
# 正确: 完整类型标注
async def process_message(
    message: str,
    user_id: int,
    session: AsyncSession
) -> MessageResult: ...

# 错误: 缺少类型标注
def process_message(message, user_id, session): ...
```

### 5.2 Optional 和 Union
```python
from typing import Optional, Union

def get_config(key: str) -> Optional[Config]:
    ...

def handle_value(value: Union[str, int, float]) -> str:
    ...
```

### 5.3 None 安全
```python
# 正确: 先检查 None
result = await find_user(user_id)
if result is None:
    raise UserNotFoundError(user_id)
return result.name

# 正确: 使用 Optional 链式访问
name = user and user.profile and user.profile.name
```

## 测试标准

### 6.1 测试覆盖要求
- 核心业务逻辑覆盖率 >= 80%
- 异常路径必须单独编写测试用例
- 每个 `except` 分支应有对应测试

### 6.2 测试命名规范
```python
# 正常路径: test_{function}_{expected_result}
async def test_process_message_returns_response(): ...

# 异常路径: test_{function}_{error_condition}
async def test_process_message_raises_on_empty_input(): ...
async def test_process_message_handles_timeout(): ...
```

### 6.3 Mock 原则
- mock 外部服务（LLM、数据库、网络），不 mock 内部逻辑
- 集成测试减少 mock，验证真实交互

## 命名规范

### 7.1 命名风格
| 元素 | 规范 | 示例 |
|------|------|------|
| 函数/方法 | snake_case | `process_message` |
| 变量 | snake_case | `user_name` |
| 类 | PascalCase | `ChatProcessor` |
| 常量 | UPPER_SNAKE | `MAX_RETRY_COUNT` |
| 私有函数 | 前缀 `_` | `_validate_input` |
| 异步函数 | `async def` 前缀 | `async def fetch_data()` |

### 7.2 导入顺序
```python
# 1. 标准库
import asyncio
from pathlib import Path

# 2. 第三方库
from fastapi import APIRouter
from pydantic import BaseModel, Field

# 3. 项目内部
from api.dependencies import get_current_user
from core.exceptions import ValidationError
```

## 性能规范

### 8.1 ORM 查询
- 避免 N+1 查询，使用 `joinedload` 或 `selectinload`
- 大数据量查询必须分页
- 频繁查询的条件必须建索引

### 8.2 LLM 调用
- 始终设置超时（`asyncio.wait_for` 或 `httpx.Timeout`）
- 实现退避重试（指数退避 + 随机抖动）
- 设置最大连续错误阈值

### 8.3 文件 I/O
- 大文件使用流式读写
- 短时间大量小文件读写使用缓冲区
- 日志写入使用异步日志处理器
