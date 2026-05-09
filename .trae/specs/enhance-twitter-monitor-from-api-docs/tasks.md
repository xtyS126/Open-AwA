# Tasks

- [x] Task 1: 重构 twitter_api.py 客户端，覆盖全部读取端点
  - [x] 新增 `get_user_info()` 方法，使用专用 `GET /twitter/user/info` 端点
  - [x] 新增 `get_user_timeline()` 方法，使用 `GET /twitter/user/tweet_timeline` 端点（支持 userId、includeReplies、includeParentTweet、cursor 参数）
  - [x] 新增 `search_tweets()` 方法，使用 `GET /twitter/tweet/advanced_search` 端点（支持 query、queryType、cursor 参数）
  - [x] 新增 `get_tweet_replies()` 方法，使用 `GET /twitter/tweet/replies` 端点（支持 tweetId、sinceTime、untilTime、cursor 参数）
  - [x] 新增 `get_user_followers()` 方法，使用 `GET /twitter/user/followers` 端点（支持 userName、cursor、pageSize 参数）
  - [x] 新增 `get_user_followings()` 方法，使用 `GET /twitter/user/followings` 端点（支持 userName、cursor、pageSize 参数）
  - [x] 保留现有 `get_user_last_tweets()` 和 `search_users()` 方法
  - [x] 统一错误处理和超时配置（30s 超时 + 指数退避重试）

- [x] Task 2: 扩展 index.py 的 `_simplify_tweet` 字段
  - [x] 新增 `entities` 字段（含 hashtags 文本列表、urls 的 display_url/expanded_url、user_mentions 的 screen_name/name）
  - [x] 新增 `quote_count`、`view_count`、`bookmark_count` 字段
  - [x] 新增 `lang`、`is_reply`、`conversation_id`、`in_reply_to_id` 字段
  - [x] 新增 `quoted_tweet`（含 id、text、author.user_name 简版）和 `retweeted_tweet`（含 id、text、author.user_name 简版）字段
  - [x] 确保字段从 API 原始响应字段正确映射（如 `quoteCount` → `quote_count`）

- [x] Task 3: index.py 统一使用 twitter_api.py 客户端
  - [x] 移除 `_request_twitter_api()` 方法
  - [x] `fetch_user_tweets()` 改用 `self._twitter_api.get_user_last_tweets()`
  - [x] `fetch_twitter_tweets()` 改用 `self._twitter_api.get_user_last_tweets()`
  - [x] `search_twitter_users()` 改用 `self._twitter_api.search_users()`
  - [x] `get_twitter_user_info()` 改用 `self._twitter_api.get_user_info()`（专用端点）
  - [x] `_auto_fetch_loop()` 改用 `self._twitter_api.get_user_last_tweets()`

- [x] Task 4: 新增 4 个 AI 可调用工具到 index.py
  - [x] 实现 `search_tweets()` 工具方法：调用 `TwitterAPI.search_tweets()` + `_simplify_tweet()` + 缓存
  - [x] 实现 `get_tweet_replies()` 工具方法：调用 `TwitterAPI.get_tweet_replies()` + `_simplify_tweet()`
  - [x] 实现 `get_user_followers()` 工具方法：调用 `TwitterAPI.get_user_followers()` + 简化用户数据
  - [x] 实现 `get_user_following()` 工具方法：调用 `TwitterAPI.get_user_followings()` + 简化用户数据
  - [x] 在 `execute()` 的 actions 字典中注册 4 个新工具
  - [x] 在 `get_tools()` 中注册 4 个新工具的 Schema 定义

- [x] Task 5: 统一 summarizer.py 字段命名
  - [x] 将 `format_tweets()` 中的 `userName` → `user_name`
  - [x] 将 `createdAt` → `created_at`
  - [x] 将 `likeCount` → `likes`、`retweetCount` → `retweets`
  - [x] 确保与 `_simplify_tweet()` 输出的字段完全一致

- [x] Task 6: 更新 manifest.json 扩展点
  - [x] 注册 `search_tweets` 工具扩展点
  - [x] 注册 `get_tweet_replies` 工具扩展点
  - [x] 注册 `get_user_followers` 工具扩展点
  - [x] 注册 `get_user_following` 工具扩展点

# Task Dependencies

- Task 2 依赖 Task 1（需先确定 API 返回字段结构）
- Task 3 依赖 Task 1（需先用客户端封装好端点）
- Task 4 依赖 Task 1、Task 2、Task 3（需客户端、简化函数、统一调用就绪）
- Task 5 依赖 Task 2（需先确定统一字段命名）
- Task 6 依赖 Task 4（需先确定工具名和参数 Schema）
