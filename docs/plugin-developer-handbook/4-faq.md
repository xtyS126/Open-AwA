# 第四章：常见问题

## Q1：插件加载时报错 `Invalid manifest: missing required field 'extensions'`，如何解决？

**原因：** manifest.json 中缺少 `extensions` 字段，或该字段为空数组。

`extensions` 是必填字段，且至少需要包含一个扩展点声明。

**解决方法：** 确保 manifest.json 包含至少一个扩展点：

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "pluginApiVersion": "1.0",
  "extensions": [
    {
      "point": "tool",
      "name": "my_tool",
      "version": "1.0.0"
    }
  ]
}
```

---

## Q2：插件的 `initialize` 方法返回 `True`，但插件状态仍然是 `error`，这是什么原因？

**原因：** 可能是 `validate()` 方法返回了 `False`，或者 `initialize` 内部抛出了未捕获的异常。

**解决方法：**

1. 检查 `validate()` 方法逻辑，确保配置合法时返回 `True`
2. 在 `initialize` 中添加 try-except，使用 `logger.error()` 输出具体错误信息
3. 查看后端日志，搜索插件名称关键词定位具体报错

---

## Q3：我的插件使用了 `requests` 库发起 HTTP 请求，但加载时被拒绝，应如何处理？

**原因：** `requests` 属于受限网络 API，必须在 manifest.json 中声明 `network:http` 权限才能使用。

**解决方法：** 在 manifest.json 中添加权限声明：

```json
{
  "permissions": ["network:http"]
}
```

注意：推荐在插件中使用 `httpx` 而非 `requests`，因为 `httpx` 原生支持 async，与系统沙箱的异步执行模型更兼容。

---

## Q4：插件执行时提示 `Execution exceeded 30s limit`，如何提高超时限制？

**原因：** `PluginSandbox` 默认超时为 30 秒，长时间运行的任务会被中断。

**解决方法：**

1. 优先优化插件逻辑，减少执行时间
2. 将同步操作改为异步操作（`async def execute`），充分利用 IO 等待时间
3. 若确实需要更长超时，可在实例化 `PluginSandbox` 时传入自定义 `timeout` 参数（需后端管理员操作）

---

## Q5：如何在插件之间共享数据？

**原因：** 插件之间相互隔离，不能直接访问彼此的实例变量。

**推荐方案：**

1. 通过后端 REST API 接口读写数据库实现数据共享
2. 使用 `data_provider` 扩展点注册数据源，其他插件通过该扩展点查询数据
3. 使用 `event_handler` 扩展点监听另一个插件发出的事件

---

## Q6：`manifest.json` 中 `pluginApiVersion` 填什么值？

当前 Open-AwA 支持的 Plugin API 版本为 `"1.0"`，填写如下：

```json
{
  "pluginApiVersion": "1.0"
}
```

未来版本升级时，文档会同步更新此字段的有效值。若填写了系统不支持的版本，插件将无法通过 schema 校验。

---

## Q7：如何实现插件的热更新，不重启服务就能加载新版本？

系统内置了 `HotUpdateManager` 支持热更新，通过以下 REST API 触发：

```bash
curl -X POST http://localhost:8000/api/plugins/{plugin_name}/update \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/new-version"}'
```

热更新流程：
1. 系统对当前版本创建快照
2. 加载新版本插件并执行 `initialize`
3. 若新版本初始化失败，自动回滚至快照版本
4. 回滚调用插件的 `rollback` 方法，可重写该方法添加自定义回滚逻辑

---

## Q8：如何为插件编写单元测试？

直接实例化插件类，传入测试配置，调用 `initialize` 和 `execute` 即可：

```python
import pytest
from plugins.hello_world.src.index import HelloWorldPlugin


def test_hello_world_execute():
    plugin = HelloWorldPlugin(config={"greeting": "Hi"})
    assert plugin.initialize() is True
    result = plugin.execute(name="Alice")
    assert result["message"] == "Hi, Alice!"


def test_hello_world_validate():
    plugin = HelloWorldPlugin(config={"greeting": 123})
    assert plugin.validate() is False
```

运行测试：

```bash
cd backend
pytest tests/plugins/ -v
```

---

## Q9：前端插件调试面板（PluginDebugPanel）无法显示插件列表，应如何排查？

**排查步骤：**

1. 确认后端服务正在运行（`http://localhost:8000` 可访问）
2. 打开浏览器开发者工具，检查 Network 标签，查看 `/api/plugins` 请求是否返回 200
3. 若接口返回 401，检查认证 token 是否有效
4. 若接口返回 500，查看后端日志定位服务端错误
5. 检查前端 `.env` 文件中的 `VITE_API_BASE_URL` 配置是否正确

---

## Q10：插件的 `name` 字段有什么命名限制？

`name` 字段用于在系统中唯一标识插件，建议遵循以下规范：

- 只使用小写字母、数字和连字符（`-`）
- 不以连字符开头或结尾
- 长度不超过 64 个字符
- 在整个系统中全局唯一，若与已注册插件重名，后加载的插件会覆盖前者

推荐格式：`{作者}-{功能描述}`，如 `alice-weather-query`、`corp-data-export`。

---

## Q11：可以在 `initialize` 中发起 HTTP 请求吗？

可以，但需注意以下几点：

1. 必须在 manifest.json 中声明 `network:http` 权限
2. `initialize` 是同步方法，若需要发起异步请求，可将 `initialize` 改为 `async def initialize`
3. 若 HTTP 请求失败，`initialize` 应返回 `False`，不要抛出未捕获的异常

```python
async def initialize(self) -> bool:
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(self.config.get("health_url", ""))
            if response.status_code != 200:
                return False
        self._initialized = True
        return True
    except Exception as e:
        logger.error(f"初始化失败：{e}")
        return False
```

---

## Q12：如何处理插件的多版本共存问题？

当前系统通过插件 `name` 字段唯一标识一个插件实例，同一 `name` 只能有一个版本处于 `enabled` 状态。

若需要 A/B 测试不同版本，可以使用不同的 `name`，如 `my-plugin-v1` 和 `my-plugin-v2`，分别注册并通过路由逻辑决定调用哪个版本。

热更新（`HotUpdateManager`）是官方推荐的版本升级方式，支持自动回滚，适合生产环境的无缝升级。
