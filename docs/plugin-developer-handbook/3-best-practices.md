# 第三章：最佳实践

## 3.1 安全规范

### 最小权限原则

只在 manifest.json 中声明插件真正需要的权限。多余的权限声明会降低用户信任度，并在代码审查中被标记为安全风险。

不推荐的写法：

```json
{
  "permissions": ["file:read", "file:write", "network:http"]
}
```

若插件只需读取一个配置文件，应只声明：

```json
{
  "permissions": ["file:read"]
}
```

### 禁止使用的 API

以下 API 在插件中无条件禁止，任何使用都会导致插件加载失败：

| 禁止 API | 禁止原因 |
|----------|----------|
| `eval()` | 动态代码执行，无法静态分析 |
| `exec()` | 动态代码执行，无法静态分析 |
| `compile()` | 编译任意代码 |
| `subprocess` | 执行系统命令 |
| `ctypes` | 调用原生库，可绕过沙箱 |
| `pickle` | 反序列化可执行任意代码 |
| `marshal` | 同 pickle，存在代码注入风险 |

### 输入校验

`execute` 方法接收来自外部的参数，务必进行类型和边界校验，防止注入攻击：

```python
def execute(self, *args, **kwargs) -> Any:
    query = kwargs.get("query", "")
    if not isinstance(query, str):
        return {"error": "query 必须是字符串"}
    if len(query) > 1000:
        return {"error": "query 长度不能超过 1000 字符"}
    return self._process(query)
```

### 敏感信息处理

- 不要在代码中硬编码 API 密钥、密码等敏感信息
- 通过 `config` 字典接收敏感配置，由系统在部署时注入
- 不要在日志中输出完整的敏感数据

```python
def initialize(self) -> bool:
    api_key = self.config.get("api_key", "")
    if not api_key:
        logger.error("api_key 未配置")
        return False
    logger.info("api_key 已加载（已隐藏）")
    self._api_key = api_key
    self._initialized = True
    return True
```

### 异常处理

`execute` 方法中的未捕获异常会被沙箱拦截并返回 error 状态。建议在方法内部主动捕获并返回结构化错误：

```python
def execute(self, *args, **kwargs) -> Any:
    try:
        return self._do_work(**kwargs)
    except ValueError as e:
        logger.warning(f"参数错误：{e}")
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error(f"未知错误：{e}")
        return {"status": "error", "message": "内部错误"}
```

---

## 3.2 性能优化

### 避免阻塞主线程

插件执行有 30 秒超时限制。对于 IO 密集型操作，使用异步方法：

```python
import asyncio
from typing import Any
from backend.plugins.base_plugin import BasePlugin
from loguru import logger


class AsyncPlugin(BasePlugin):
    name = "async-plugin"
    version = "1.0.0"
    description = "异步执行示例"

    def initialize(self) -> bool:
        self._initialized = True
        return True

    async def execute(self, *args, **kwargs) -> Any:
        result = await self._fetch_data(kwargs.get("url", ""))
        return result

    async def _fetch_data(self, url: str) -> dict:
        await asyncio.sleep(0.1)
        return {"url": url, "data": "..."}
```

`PluginSandbox` 会自动检测方法是否为协程函数并使用 `asyncio.wait_for` 执行，无需额外配置。

### 缓存重复计算结果

若 `execute` 中存在重复且耗时的计算，使用实例变量缓存：

```python
class CachedPlugin(BasePlugin):
    name = "cached-plugin"
    version = "1.0.0"
    description = "缓存示例"

    def initialize(self) -> bool:
        self._cache: dict = {}
        self._initialized = True
        return True

    def execute(self, *args, **kwargs) -> Any:
        key = kwargs.get("key", "")
        if key in self._cache:
            return {"result": self._cache[key], "from_cache": True}
        result = self._expensive_computation(key)
        self._cache[key] = result
        return {"result": result, "from_cache": False}

    def _expensive_computation(self, key: str) -> str:
        return f"computed_{key}"

    def cleanup(self) -> None:
        self._cache.clear()
        super().cleanup()
```

### 延迟初始化重型资源

不要在 `__init__` 中加载大型模型或建立数据库连接，应在 `initialize` 中执行：

```python
def __init__(self, config=None):
    super().__init__(config)
    self._model = None

def initialize(self) -> bool:
    self._model = self._load_model()
    self._initialized = True
    return True
```

### 合理使用日志级别

| 级别 | 适用场景 |
|------|----------|
| `logger.debug()` | 开发调试，生产环境应关闭 |
| `logger.info()` | 关键流程节点，如初始化、执行开始/结束 |
| `logger.warning()` | 可恢复的异常情况 |
| `logger.error()` | 错误，影响功能正常运行 |

频繁调用的热路径中避免使用 `logger.info()`，改用 `logger.debug()`，减少 IO 开销。

### 资源清理

在 `cleanup` 方法中释放所有持有的资源：

```python
def cleanup(self) -> None:
    if hasattr(self, "_connection") and self._connection:
        self._connection.close()
        self._connection = None
    super().cleanup()
```

---

## 3.3 用户体验

### 提供清晰的错误信息

`execute` 的返回值会透传给调用方，错误信息应简洁、可操作：

不推荐：

```python
return {"error": "Exception: 'NoneType' object has no attribute 'get'"}
```

推荐：

```python
return {"error": "参数 'keyword' 不能为空，请提供搜索关键词"}
```

### 结构化返回值

保持 `execute` 返回值格式一致，便于调用方处理：

```python
def execute(self, *args, **kwargs) -> dict:
    return {
        "status": "success",
        "data": {...},
        "meta": {
            "plugin": self.name,
            "version": self.version
        }
    }
```

### 版本兼容性

遵循 SemVer 语义化版本规范：

| 版本类型 | 适用场景 | 示例 |
|----------|----------|------|
| 补丁版本 | Bug 修复，向后兼容 | 1.0.0 -> 1.0.1 |
| 次版本 | 新增功能，向后兼容 | 1.0.0 -> 1.1.0 |
| 主版本 | 破坏性变更，不兼容 | 1.0.0 -> 2.0.0 |

### 提供完善的 README.md

每个插件目录应包含 README.md，至少涵盖：

1. 插件功能简介
2. 安装与配置方法（包含 config 字段说明）
3. 使用示例（输入/输出示例）
4. 权限说明
5. 已知限制

### get_tools 方法

若插件作为 AI 工具使用，应实现 `get_tools` 方法，提供标准的工具描述，以便 AI 智能体正确理解工具的用途和参数：

```python
def get_tools(self):
    return [
        {
            "name": "search_web",
            "description": "搜索互联网上的信息，返回最相关的结果摘要",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，支持自然语言查询"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量，默认为 5",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    ]
```
