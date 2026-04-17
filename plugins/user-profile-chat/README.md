# User Profile Chat 插件

基于聊天记录分析并生成用户画像的插件。

## 功能

- **analyze_user_profile**: 分析用户历史聊天记录，提取兴趣偏好、交流风格、关注领域等画像维度
- **get_user_profile**: 获取指定用户的已有画像数据
- **on_chat_message**: 监听聊天消息事件，实时增量更新用户画像

## 画像维度

| 维度 | 说明 |
|------|------|
| interests | 用户兴趣标签列表，按出现频率排序 |
| communication_style | 交流风格分析（简洁/详细、正式/随意等） |
| expertise_areas | 用户擅长或频繁讨论的专业领域 |
| activity_pattern | 活跃时段和使用频率统计 |
| sentiment_tendency | 整体情感倾向分析 |

## 配置项

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| max_messages_per_analysis | int | 100 | 单次分析最多使用的消息条数 |
| min_messages_for_profile | int | 5 | 生成画像所需的最少消息数 |
| profile_update_interval | int | 10 | 每隔多少条新消息触发一次画像更新 |
