# Checklist

## 代码正确性
- [x] `twitter_api.py` 新增 6 个端点的 URL、参数、请求方法、响应解析均与 TwitterApi.io 文档一致
- [x] `twitter_api.py` 所有方法统一使用 `X-API-Key` Header 认证
- [x] `twitter_api.py` 所有方法有统一错误处理（timeout 30s、RequestException、JSONDecodeError）
- [x] `index.py` 中 `_request_twitter_api()` 已完全移除，所有调用走 `self._twitter_api`
- [x] `index.py` 中 `_simplify_tweet()` 包含 entities、quote_count、view_count、bookmark_count、lang、is_reply 等新增字段
- [x] `index.py` 中 4 个新工具方法实现完整且注册到 `execute()` 和 `get_tools()`
- [x] `summarizer.py` 中 `format_tweets()` 字段命名与 `_simplify_tweet()` 输出完全一致
- [x] `manifest.json` 包含 4 个新工具扩展点

## 异常处理
- [x] API 调用使用具体异常类型（`requests.exceptions.Timeout`、`requests.exceptions.ConnectionError`、`requests.exceptions.RequestException`）
- [x] 不存在 `try/except/pass` 模式
- [x] API 请求失败时有合适的错误信息返回给调用方
- [x] 关键路径（`trigger_auto_fetch`）的错误正确传播

## 日志记录
- [x] 关键操作（API 调用、工具执行）有日志记录
- [x] 日志不包含 API 密钥等敏感信息
- [x] 错误日志包含足够的上下文（端点、参数、错误类型）

## 性能
- [x] API 请求均设置 30s 超时
- [x] 分页端点（timeline、followers、followings、replies）正确使用 cursor 参数

## 测试
- [x] 运行 `python -m pytest backend/tests/test_twitter_monitor_plugin.py -v` 通过
- [x] 运行 `python -m py_compile plugins/twitter-monitor/src/twitter_api.py` 零语法错误
- [x] 运行 `python -m py_compile plugins/twitter-monitor/src/index.py` 零语法错误
- [x] 运行 `python -m py_compile plugins/twitter-monitor/src/summarizer.py` 零语法错误

## 安全
- [x] API 密钥仅通过 `config.json` 环境变量或加密配置传入，不在代码中硬编码
- [x] `_get_effective_summary_config()` 等方法暴露的配置不包含 `twitter_api_key`
