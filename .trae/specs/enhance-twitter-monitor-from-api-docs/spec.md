# Twitter Monitor 插件基于 API 文档集完善

## Why

当前 `twitter-monitor` 插件仅使用了 TwitterApi.io 的 2 个端点（`user/last_tweets` 和 `user/search`），但该 API 文档集提供了 7+ 个与监控场景直接相关的读取端点。同时，插件内部的 `twitter_api.py` 客户端类未被 `index.py` 实际使用，存在代码重复和维护问题。推文数据字段也仅简化了少量字段，丢失了 entities（hashtags/URLs/mentions）、quoteCount、viewCount 等有价值的信息。

## What Changes

- **twitter_api.py 客户端重构**：统一所有 API 端点调用，新增 `user/info`（专用端点）、`user/tweet_timeline`（带分页）、`tweet/advanced_search`（高级搜索）、`tweet/replies`（推文回复）、`user/followers`（粉丝列表）、`user/followings`（关注列表）
- **index.py 使用 twitter_api.py 客户端**：将 `_request_twitter_api()` 替换为直接调用 `TwitterAPI` 客户端方法，消除代码重复
- **`_simplify_tweet` 字段扩展**：补充 entities（hashtags、urls、user_mentions）、quoteCount、viewCount、bookmarkCount、lang、isReply、conversationId、inReplyToId、quoted_tweet、retweeted_tweet 等字段
- **新增 AI 工具**：`search_tweets`（高级推文搜索）、`get_tweet_replies`（获取推文回复）、`get_user_followers`（获取粉丝列表）、`get_user_following`（获取关注列表）
- **summarizer.py 统一字段命名**：改用 `_simplify_tweet` 产出的 snake_case 字段，消除与 index.py 的字段不一致
- **manifest.json 扩展**：注册新增工具扩展点

## Impact

- Affected specs: `twitter-monitor-use-platform-ai-models`（已完成的旧 spec，本次基于它进一步扩展）
- Affected code:
  - `plugins/twitter-monitor/src/twitter_api.py` — 核心 API 客户端重构
  - `plugins/twitter-monitor/src/index.py` — 主插件类改造
  - `plugins/twitter-monitor/src/summarizer.py` — 字段命名统一
  - `plugins/twitter-monitor/manifest.json` — 扩展点注册
- **BREAKING**：`summarizer.py` 的 `format_tweets()` 将从 `userName`/`createdAt`/`likeCount` 改为 `user_name`/`created_at`/`likes`，但 `summarizer.py` 仅在插件内部使用，不影响外部 API

---

## ADDED Requirements

### Requirement: TwitterAPI 客户端完整覆盖读取端点
系统 SHALL 在 `twitter_api.py` 中封装 TwitterApi.io 文档集中所有与监控场景相关的读取端点。

#### Scenario: 通过专用端点获取用户信息
- **WHEN** 调用 `get_user_info(user_name="elonmusk")`
- **THEN** 使用 `GET /twitter/user/info?userName=elonmusk` 获取用户详情
- **AND** 返回包含 `userName`、`name`、`description`、`followers`、`following`、`profilePicture`、`isBlueVerified` 等完整字段

#### Scenario: 获取用户时间线（带分页）
- **WHEN** 调用 `get_user_timeline(user_id="123", include_replies=True, cursor="abc")`
- **THEN** 使用 `GET /twitter/user/tweet_timeline?userId=123&includeReplies=true&cursor=abc`
- **AND** 返回 `tweets` 数组、`has_next_page` 和 `next_cursor`

#### Scenario: 高级推文搜索
- **WHEN** 调用 `search_tweets(query="AI from:elonmusk", query_type="Latest")`
- **THEN** 使用 `GET /twitter/tweet/advanced_search?query=AI from:elonmusk&queryType=Latest`
- **AND** 返回 `tweets` 数组、`has_next_page` 和 `next_cursor`

#### Scenario: 获取推文回复
- **WHEN** 调用 `get_tweet_replies(tweet_id="1846987139428634858")`
- **THEN** 使用 `GET /twitter/tweet/replies?tweetId=1846987139428634858`
- **AND** 返回 `replies` 数组、`has_next_page` 和 `next_cursor`

#### Scenario: 获取用户粉丝列表
- **WHEN** 调用 `get_user_followers(user_name="elonmusk", cursor="")`
- **THEN** 使用 `GET /twitter/user/followers?userName=elonmusk&cursor=`
- **AND** 返回 `followers` 数组，每页最多 200 条

#### Scenario: 获取用户关注列表
- **WHEN** 调用 `get_user_followings(user_name="elonmusk", cursor="")`
- **THEN** 使用 `GET /twitter/user/followings?userName=elonmusk&cursor=`
- **AND** 返回 `followings` 数组，每页最多 200 条

### Requirement: 推文字段完整简化
系统 SHALL 在 `_simplify_tweet()` 中补充以下字段：
- `entities`: 包含 `hashtags`（文本列表）、`urls`（display_url/expanded_url）、`user_mentions`（screen_name/name）
- `quote_count`、`view_count`、`bookmark_count`
- `lang`、`is_reply`、`conversation_id`、`in_reply_to_id`
- `quoted_tweet`（简化版）、`retweeted_tweet`（简化版）

### Requirement: 新增 AI 可调用工具
系统 SHALL 在 `index.py` 中注册以下新工具：

| 工具名 | 功能 | 参数 |
|---|---|---|
| `search_tweets` | 高级推文搜索并缓存 | query(必填), query_type, limit |
| `get_tweet_replies` | 获取指定推文的回复 | tweet_id(必填), limit |
| `get_user_followers` | 获取用户粉丝列表 | user_name(必填), limit |
| `get_user_following` | 获取用户关注列表 | user_name(必填), limit |

### Requirement: index.py 统一使用 twitter_api.py 客户端
系统 SHALL 将 `index.py` 中的 `_request_twitter_api()` 方法移除，所有 API 调用改为通过 `self._twitter_api` 客户端完成。

## MODIFIED Requirements

### Requirement: summarizer.py 字段命名统一
`summarizer.py` 中的 `format_tweets()` 方法 SHALL 统一使用与 `_simplify_tweet()` 一致的 snake_case 字段命名（`user_name`、`created_at`、`likes` 等），确保推文数据在插件内部流转时字段一致。

### Requirement: AI 总结流程推文来源扩展
`summarize_twitter_tweets` 工具 SHALL 保留当前行为（从缓存读取并返回摘要素材），而 `trigger_auto_fetch` 中的自动总结 SHALL 继续使用 `_summarizer` 进行内部总结。
