# 微信端 AI 交互功能补全 Spec

## Why

当前项目已实现微信二维码登录和基础配置管理，但缺少完整的微信手机端 AI 交互闭环能力。用户无法在微信客户端直接与 AI 对话、触发异步任务、接收实时回复。需要基于 `open-weixin-deep-research.md` 技术方案，补全消息收发、媒体处理、任务追踪、错误重试、性能监控等完整链路。

## What Changes

### 后端核心能力
- **消息处理管道**: 入站消息解析、斜杠指令处理、出站消息发送、Markdown转纯文本
- **长轮询监控循环**: 持续获取微信消息并路由到AI引擎处理
- **媒体处理模块**: CDN上传、AES-128-ECB加密、图片/视频/文件处理、语音SILK转码
- **会话上下文管理**: context_token持久化、get_updates_buf游标管理
- **斜杠指令系统**: /echo、/toggle-debug、/task等指令处理
- **异步任务追踪**: 任务创建、状态轮询、结果回调通知

### 前端能力增强
- **消息发送界面**: 在通讯页添加消息发送测试功能
- **任务状态展示**: 异步任务进度追踪UI
- **调试模式开关**: 前端调试信息展示

### 基础设施
- **错误重试机制**: 指数退避、熔断保护、错误通知
- **性能监控**: 全链路耗时追踪、结构化日志
- **灰度发布支持**: 功能开关、灰度策略配置
- **测试覆盖**: 单元测试、集成测试、E2E测试

### **BREAKING** 变更
- WeixinSkillAdapter 将重构为完整的消息处理引擎，现有接口保持兼容但内部实现大幅调整

## Impact

- Affected specs: `refactor-weixin-integration-from-source`, `finalize-weixin-binding-handoff-and-pairing`
- Affected code:
  - `backend/skills/weixin_skill_adapter.py` - 重构为核心消息处理引擎
  - `backend/api/routes/skills.py` - 新增消息发送、任务追踪接口
  - `frontend/src/features/chat/CommunicationPage.tsx` - 增强消息发送与任务追踪UI
  - 新增 `backend/skills/weixin/` 目录 - 模块化消息处理组件

## ADDED Requirements

### Requirement: 微信消息收发闭环

系统 SHALL 提供完整的微信消息收发能力，使用户可在微信手机客户端与AI进行自然语言对话。

#### Scenario: 用户发送文本消息
- **WHEN** 用户在微信客户端发送文本消息"帮我写一段Python代码"
- **THEN** 系统通过长轮询获取消息，路由到AI引擎处理，并将AI回复发送回微信客户端

#### Scenario: 用户发送语音消息
- **WHEN** 用户在微信客户端发送语音消息
- **THEN** 系统自动将SILK语音转码为文本，按文本消息流程处理

#### Scenario: AI回复包含代码块
- **WHEN** AI回复包含Markdown代码块
- **THEN** 系统自动转换为微信兼容的纯文本格式，保留代码内容但去除格式标记

### Requirement: 异步任务追踪

系统 SHALL 支持用户通过对话指令触发异步任务，并在任务完成后通知用户。

#### Scenario: 触发深度检索任务
- **WHEN** 用户发送"/task search 深度检索关键词"
- **THEN** 系统创建异步任务，立即回复"任务已创建，正在处理中..."，任务完成后发送结果通知

#### Scenario: 查询任务状态
- **WHEN** 用户发送"/task status 任务ID"
- **THEN** 系统返回任务当前状态、进度百分比、预计剩余时间

#### Scenario: 任务执行失败
- **WHEN** 异步任务执行失败
- **THEN** 系统发送错误通知，包含错误原因和重试建议

### Requirement: 媒体消息处理

系统 SHALL 支持发送和接收图片、视频、文件等媒体消息。

#### Scenario: AI生成图片发送
- **WHEN** AI生成图片需要发送给用户
- **THEN** 系统将图片AES加密后上传到微信CDN，构造媒体消息发送

#### Scenario: 用户发送图片
- **WHEN** 用户发送图片消息
- **THEN** 系统下载并解密图片，传递给AI进行图像理解处理

### Requirement: 斜杠指令系统

系统 SHALL 提供内置斜杠指令，用于测试通道、调试和任务管理。

#### Scenario: /echo测试指令
- **WHEN** 用户发送"/echo 你好"
- **THEN** 系统直接回复"你好"并附带通道耗时统计

#### Scenario: /toggle-debug调试指令
- **WHEN** 用户发送"/toggle-debug"
- **THEN** 系统切换调试模式，后续AI回复追加全链路耗时详情

### Requirement: 错误处理与重试

系统 SHALL 提供完善的错误处理机制，确保消息不丢失。

#### Scenario: 网络临时故障
- **WHEN** 发送消息遇到网络错误
- **THEN** 系统按指数退避策略重试，最多3次，失败后发送错误通知

#### Scenario: 会话过期
- **WHEN** 检测到会话过期（errcode=-14）
- **THEN** 系统暂停该账号请求1小时，并发送"会话已过期，请重新扫码登录"通知

### Requirement: 性能监控

系统 SHALL 提供全链路性能监控能力。

#### Scenario: 调试模式开启
- **WHEN** 调试模式开启
- **THEN** 每条AI回复追加耗时统计：平台到插件延迟、入站处理耗时、AI生成耗时、总耗时

### Requirement: 灰度发布支持

系统 SHALL 支持功能灰度发布。

#### Scenario: 新功能灰度
- **WHEN** 配置灰度比例为50%
- **THEN** 50%的用户启用新功能，其余用户使用旧版本

## MODIFIED Requirements

### Requirement: WeixinSkillAdapter消息处理

原有 WeixinSkillAdapter 仅支持基础的 send_message 和 get_updates，现扩展为完整的消息处理引擎：

- 新增 `start_monitor()` 方法启动长轮询监控循环
- 新增 `process_inbound_message()` 方法处理入站消息
- 新增 `send_media_message()` 方法发送媒体消息
- 新增 `handle_slash_command()` 方法处理斜杠指令
- 新增 `create_async_task()` 方法创建异步任务
- 新增 `get_task_status()` 方法查询任务状态

## REMOVED Requirements

### Requirement: 旧版推断式配置兼容

**Reason**: 新版基于 open-weixin 源码重构，不再需要推断式兼容逻辑
**Migration**: 清理 `_coerce_weixin_payload_dict` 中的推断逻辑，使用明确的协议解析
