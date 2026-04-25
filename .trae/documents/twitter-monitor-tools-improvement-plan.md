# Twitter Monitor 插件工具改造计划

## 目标
修改 `d:\代码\Open-AwA\plugins\twitter-monitor` 插件，参考 `d:\代码\Open-AwA\插件\twitter_monitor` 源码，使其拥有以下可调用工具：
1. 搜索用户（search users）
2. 搜索用户指定数量推文，需要填写推文数量（fetch user tweets with required limit）
3. 每日自动获取指定用户的指定量推文，无需AI填写数值但需要用户手动配置，获取推文后需要AI自行总结（auto-fetch with AI summary）

## 现状分析

### 已完成（代码层面已就绪）
- `src/twitter_api.py` - Twitter API 客户端封装（search_users / get_last_tweets）
- `src/storage.py` - 推文存储与去重（latest + daily 双模式）
- `src/summarizer.py` - AI 推文总结器（通过外部 AI API 回调）
- `src/index.py` - 主插件类，包含：
  - `fetch_user_tweets(user_name, limit)` - user_name 和 limit 均为必填参数
  - `search_twitter_users(query, limit)` - 搜索用户
  - `trigger_auto_fetch` / `start_auto_fetch_scheduler` / `stop_auto_fetch_scheduler` / `get_scheduler_status` - 4个调度工具
  - `_auto_fetch_loop()` - 后台线程循环，定时获取并调用外部 AI 总结
  - `_call_external_ai_for_summary()` - 使用配置的 AI API 端点进行自动总结

### 待完成（配置文件缺失）
- `manifest.json` - 版本仍为 1.0.0，缺少新工具的 extensions
- `schema.json` - 缺少 auto_fetch_interval_hours / ai_api_key / ai_base_url / ai_model 字段
- `config.json` - 缺少上述新配置的默认值

## 实施步骤

### 步骤1：更新 `schema.json`（已完成）
添加以下配置字段：
- `auto_fetch_interval_hours` - 自动获取间隔小时数
- `ai_api_key` - 自动总结用的 AI API 密钥
- `ai_base_url` - 自动总结用的 AI API 基础 URL
- `ai_model` - 自动总结用的 AI 模型名称

### 步骤2：更新 `manifest.json`（已完成）
- 版本号改为 2.0.0
- 更新描述
- 添加新增工具的 extensions

### 步骤3：更新 `config.json`（已完成）
- 添加新配置项的默认值
- 修正 `summary_customization` 为嵌套对象格式

### 步骤4：验证（已完成）
- Python 语法检查
- 导入路径检查
- 工具注册检查
