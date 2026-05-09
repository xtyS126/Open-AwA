# 多模态修复 + 思考模式 + 定时任务优化 + 用户中心 Spec

## Why

当前系统存在以下四个核心问题：1) 多模态模型（如 GPT-4o/Claude）仅返回文本，无法处理图片/音频/视频输入；2) 聊天页面缺少思考深度控制，无法按厂商定义精准控制推理强度；3) 定时任务仅支持单次执行，不支持每日重复；4) 缺少独立的用户中心页面，用户无法管理个人信息、密码和设备。

## What Changes

### 多模态修复
- 前端聊天输入区新增图片/音频/视频附件上传能力
- ChatMessage 请求体扩展为支持 content parts 数组（兼容 OpenAI/Anthropic 多模态格式）
- 后端 agent/model_service 层按模型能力构建正确的多模态消息格式
- 确保图片（jpg/png/gif/webp）、音频（mp3/wav/ogg）、视频（mp4）均可正常输入

### 思考模式控制
- 聊天页面新增"启用思考"开关和 0-5 级思考深度滑块
- 后端按厂商映射思考参数：OpenAI o 系列 `reasoning_effort`（low/medium/high）、Anthropic `thinking.budget_tokens`、DeepSeek `thinking` 字段、GLM `thinking` 字段
- 思考参数通过 ChatMessage schema 传递，实时同步到请求参数

### 定时任务优化
- 创建任务表单新增"是否每日执行"复选框
- 开启后显示：时间选择器（精确到分钟，24 小时制）、多选星期（周一至周日）、Cron 表达式预览
- 后端改用 cron 调度，替代现有单次 `scheduled_at` 字段
- 创建/更新任务后返回下次执行时间戳

### 用户中心
- 右下角固定悬浮用户区域：头像、用户名、退出按钮
- 独立 `/user` 路由页面，含 JWT 鉴权
- 用户中心功能：AI 用户画像、修改密码、绑定邮箱/手机、设备管理
- 头像上传（1MB 以内 jpg/png，前端实时裁剪）
- 完全响应式 320-1920px

## Impact

- Affected specs: add-model-modality-display, implement-chat-output-mode-toggle
- Affected code:
  - **后端**: `api/schemas.py`（ChatMessage 扩展）、`api/routes/chat.py`、`api/routes/scheduled_tasks.py`、`api/routes/auth.py`、`core/agent.py`、`core/model_service.py`、`core/scheduled_task_manager.py`、`db/models.py`（User/ScheduledTask 扩展）
  - **前端**: `ChatPage.tsx`、`ChatInput.tsx`、`ScheduledTasksPage.tsx`、`Sidebar.tsx`、`App.tsx`（新增路由）、`authStore.ts`、`api.ts`、新增 `UserCenterPage.tsx` 等

---

## ADDED Requirements

### Requirement: 多模态输入支持
系统 SHALL 支持用户在聊天输入中上传图片、音频、视频文件，并将其作为多模态消息发送给支持对应能力的 AI 模型。

#### Scenario: 上传图片发送给多模态模型
- **WHEN** 用户在聊天输入区上传一张 jpg/png/gif/webp 图片（大小不超过 20MB）
- **THEN** 图片以缩略图形式显示在输入区附件预览栏
- **AND** 发送消息时，请求体包含图片的 base64 data URL 或 URL 引用
- **AND** 模型返回的回复可包含对图片内容的分析

#### Scenario: 非多模态模型收到图片
- **WHEN** 用户选择了不支持视觉的模型（如 deepseek-chat）并上传图片
- **THEN** 前端提示"当前模型不支持图片输入"并阻止发送

#### Scenario: 视频文件上传
- **WHEN** 用户上传 mp4 视频文件
- **THEN** 文件大小不超过 50MB，前端显示视频缩略图
- **AND** 发送时以多模态 content parts 格式传输

### Requirement: 思考模式控制
系统 SHALL 在聊天页面提供"启用思考"开关和 0-5 级思考深度控制，允许用户按厂商定义精确控制 AI 推理强度。

#### Scenario: 开启思考模式并设置深度
- **WHEN** 用户选择 OpenAI o3 模型并开启思考模式，将深度设为 3（中等）
- **THEN** 请求参数包含 `thinking: true` 和 `thinking_depth: 3`
- **AND** 后端映射 `thinking_depth` 到 `reasoning_effort: "medium"` 传给 OpenAI API
- **AND** 返回结果包含 `reasoning_content` 字段

#### Scenario: 不同厂商的深度映射
- **WHEN** 用户选择 Anthropic Claude 模型，深度设为 4
- **THEN** 后端映射为 `thinking: { type: "enabled", budget_tokens: 16000 }`
- **WHEN** 用户选择 DeepSeek R1 模型
- **THEN** 后端映射为 `thinking: { type: "enabled" }`（DeepSeek 不支持分档深度）

#### Scenario: 关闭思考模式
- **WHEN** 用户关闭思考开关
- **THEN** 请求参数不包含 thinking 相关字段
- **AND** 模型不返回 reasoning_content

### Requirement: 每日执行定时任务
系统 SHALL 支持创建按星期重复执行的定时任务，提供 cron 表达式预览和校验。

#### Scenario: 创建每日执行任务
- **WHEN** 用户勾选"是否每日执行"并选择时间 09:00，选择周一、周三、周五
- **THEN** 显示 cron 预览 `0 9 * * 1,3,5`
- **AND** 提交后前端展示"下次执行时间: 2026-04-27 09:00"

#### Scenario: Cron 表达式非法校验
- **WHEN** 用户未选择任何星期
- **THEN** 前端显示错误提示"请至少选择一天"

#### Scenario: 后端返回下次执行时间
- **WHEN** 创建每日任务成功
- **THEN** 后端响应包含 `next_execution_at` 时间戳字段
- **AND** 前端在任务卡片上即时展示

### Requirement: 用户中心页面
系统 SHALL 提供独立用户中心页面 `/user`，包含头像管理、密码修改、邮箱/手机绑定、设备管理和 AI 用户画像。

#### Scenario: 访问用户中心
- **WHEN** 用户点击右下角悬浮用户区域或导航到 `/user`
- **THEN** 展示用户中心页面，包含头像区、密码修改、绑定管理、设备列表、AI 画像五个模块
- **AND** 页面在 320-1920px 宽度范围内完全响应式

#### Scenario: 修改密码
- **WHEN** 用户输入旧密码、新密码、确认新密码（新密码长度至少 8 位，含大小写字母和数字）
- **THEN** 前端实时校验密码强度并显示强度指示器
- **AND** 提交后后端验证旧密码正确性，更新密码哈希

#### Scenario: 头像上传与裁剪
- **WHEN** 用户选择 1MB 以内的 jpg/png 图片上传
- **THEN** 前端显示裁剪框，支持拖拽调整，实时预览裁剪效果
- **AND** 确认后上传裁剪后的图片，后端保存并返回头像 URL

#### Scenario: 设备管理与远程登出
- **WHEN** 用户查看最近登录设备列表
- **THEN** 显示设备类型、IP 地址、登录时间、当前设备标识
- **WHEN** 用户点击"远程登出"
- **THEN** 对应设备的 JWT token 被加入黑名单，该设备需重新登录

## MODIFIED Requirements

### Requirement: ChatMessage Schema 扩展
原 `ChatMessage` 仅含 `message: str`，现扩展为支持多模态 content、thinking 参数。

```python
class ChatMessage(BaseModel):
    message: str = Field(..., max_length=32000)
    session_id: Optional[str] = "default"
    provider: Optional[str] = None
    model: Optional[str] = None
    mode: Optional[str] = "stream"
    # 新增字段
    attachments: Optional[List[AttachmentItem]] = None  # 多模态附件
    thinking_enabled: Optional[bool] = None  # 是否启用思考
    thinking_depth: Optional[int] = Field(None, ge=0, le=5)  # 思考深度 0-5
```

### Requirement: ScheduledTask 模型扩展
原 `scheduled_tasks` 仅支持单次 `scheduled_at`，现扩展为支持 cron 重复调度。

- 新增字段：`is_daily: bool`（是否每日执行）、`cron_expression: Optional[str]`（cron 表达式）、`weekdays: Optional[str]`（选中的星期，逗号分隔数字 0-6）、`daily_time: Optional[str]`（每日执行时间 HH:MM）
- API 响应新增：`next_execution_at: Optional[str]`（下次执行时间 ISO 格式）

### Requirement: User 模型扩展
原 `users` 表仅含 `username/password_hash/role`，现扩展为完整用户画像。

- 新增字段：`avatar_url: Optional[str]`、`nickname: Optional[str]`、`email: Optional[str]`、`phone: Optional[str]`、`profile_data: Optional[dict]`（AI 画像 JSON）
- 新增表：`login_devices`（设备 ID、用户 ID、设备类型、IP、User-Agent、登录时间、最后活跃时间、是否在线、JWT jti）
