# 修改 twitter-monitor 插件计划

## 目标
根据 `d:\代码\Open-AwA\插件\twitter_monitor` 参考源码，修改 `d:\代码\Open-AwA\plugins\twitter-monitor` 插件，使其提供以下能力：

1. **搜索用户** -- AI 可调用的工具
2. **获取用户指定数量推文**（用户填写推文数量） -- AI 可调用的工具
3. **每日自动获取推文并 AI 总结**（用户手动配置，AI 自行总结） -- 定时后台任务

---

## 步骤 1：分析现有插件与参考源码的差异

### 现有插件 (`plugins\twitter-monitor\src\index.py`)
- 已有 7 个工具：`fetch_twitter_tweets`、`read_twitter_cache`、`get_twitter_daily_tweets`、`get_twitter_stats`、`search_twitter_users`、`get_twitter_user_info`、`summarize_twitter_tweets`
- `fetch_twitter_tweets` 的 `limit` 参数为可选（默认 20）
- 存储基于简单文件缓存，无去重逻辑
- 总结功能调用 `self.app.agent.run()` 使用项目自身的 AI 能力

### 参考源码 (`插件\twitter_monitor\`)
- `core/api.py` -- 封装良好的 `TwitterAPI` 类，使用 TwitterApi.io
- `core/storage.py` -- 带去重功能的存储管理（基于 tweet ID 去重）
- `core/ai_summarizer.py` -- 独立的 AI 总结模块（使用 OpenAI 兼容 API）
- `monitor.py` -- 持续监控循环
- `summarize.py` -- 每日总结脚本

---

## 步骤 2：修改 `schema.json`

添加用户可配置的自动获取设置：

```json
{
  "monitored_users": {
    "type": "array",
    "items": {"type": "string"},
    "default": ["elonmusk"],
    "description": "每日自动获取推文的用户列表（无需 @ 符号）"
  },
  "tweets_per_user": {
    "type": "integer",
    "default": 8,
    "minimum": 1,
    "maximum": 50,
    "description": "每个用户每次自动获取的推文数量"
  },
  "auto_fetch_interval_hours": {
    "type": "integer",
    "default": 24,
    "minimum": 1,
    "maximum": 168,
    "description": "自动获取间隔（小时）"
  },
  "api_key": {
    "type": "string",
    "default": "",
    "description": "TwitterApi.io API 密钥"
  }
}
```

---

## 步骤 3：重写 `src/index.py`

### 3.1 保留并优化的工具

| 工具名 | 变更 |
|--------|------|
| `search_twitter_users` | 保持不变（已有搜索用户功能） |
| `fetch_user_tweets` | **新增** - 替代原有 `fetch_twitter_tweets`，`user_name` 和 `limit` 均为**必填**参数 |

### 3.2 新增的后台任务

**`auto_fetch_daily`** -- 定时后台线程，功能：
1. 从插件配置读取 `monitored_users` 和 `tweets_per_user`
2. 遍历每个配置用户，调用 Twitter API 获取推文
3. 对获取到的推文进行去重存储（引入参考源码的 storage 模块）
4. 调用 AI 自行总结（调用项目的 AI 能力）
5. 将结果保存到 `data/daily/` 和 `data/summaries/`

启动时机：插件 `on_load()` 时启动后台线程
关闭时机：插件 `on_unload()` 时关闭线程

### 3.3 整体文件结构

```
src/
├── index.py        # 主插件类（重写）
├── twitter_api.py  # TwitterApi.io 客户端（从参考源码 api.py 改造）
├── storage.py      # 存储/去重管理（从参考源码 storage.py 改造）
└── summarizer.py   # AI 总结模块（从参考源码 ai_summarizer.py 改造，适配项目 AI）
```

---

## 步骤 4：新增 `src/twitter_api.py`

从参考的 `core/api.py` 改造，提供：
- `TwitterAPI` 类
- `get_user_last_tweets(user_name, limit)` 方法
- `search_users(query)` 方法
- `get_user_info(user_name)` 方法

使用 `requests` 库调用 TwitterApi.io。

---

## 步骤 5：新增 `src/storage.py`

从参考的 `core/storage.py` 改造，提供：
- `TweetStorage` 类
- `save_latest(tweets)` -- 保存最新推文
- `save_daily(tweets, date)` -- 保存每日推文（带 ID 去重）
- `load_latest()` -- 读取最新推文
- `load_daily(date)` -- 读取某日推文
- `load_all_daily()` -- 按日期倒序读取所有每日推文

---

## 步骤 6：新增 `src/summarizer.py`

从参考的 `core/ai_summarizer.py` 改造：
- `AISummarizer` 类
- `summarize_tweets(tweets, system_prompt)` 方法
- 调用项目的 AI 能力（`self.app.agent.run()`）而非独立的 API
- 保存总结到 `data/summaries/`

---

## 步骤 7：更新 `manifest.json`

- 更新 `version` 为 `"2.0.0"`
- 更新 `description` 以反映新的能力

---

## 步骤 8：更新 `config.json`

- 添加 `api_key`、`monitored_users`、`tweets_per_user`、`auto_fetch_interval_hours` 等配置项

---

## 步骤 9：验证

1. 检查插件能否正常加载
2. 检查各工具方法签名是否符合 BasePlugin 规范
3. 检查后台线程的生命周期管理
