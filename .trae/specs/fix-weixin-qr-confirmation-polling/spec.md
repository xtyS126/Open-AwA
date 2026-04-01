# 修复微信扫码确认后网页轮询失效 Spec

## Why
当前通讯页二维码登录虽已具备基本流程，但在真实扫码场景中，手机端会弹出一串疑似认证 ID 的字符串，网页端没有进入登录成功，而是停留在轮询失败。这说明当前系统对 openclaw-weixin 实际扫码确认协议和确认后状态返回的兼容不足，需要补齐协议对齐与页面回显。

## What Changes
- 对齐 openclaw-weixin 二维码确认后的实际返回结构，修复后端 `wait` 接口对确认态、异常态和过渡态的解析。
- 调整二维码展示逻辑，明确区分“二维码内容”“确认链接”“认证 ID 文本”和“图片地址”，避免错误渲染。
- 补充前端对扫码后过渡态、确认态和异常态的提示，避免将可恢复状态误判为轮询失败。
- 增加针对“手机端弹出认证串但网页未完成登录”场景的测试覆盖。

## Impact
- Affected specs: 通讯页微信扫码登录状态机、二维码内容展示规则、扫码确认后的凭据回填流程
- Affected code: `backend/api/routes/skills.py`、`backend/skills/weixin_skill_adapter.py`、`frontend/src/pages/CommunicationPage.tsx`、`frontend/src/services/api.ts`、相关前后端测试

## ADDED Requirements
### Requirement: 扫码确认协议对齐
系统 SHALL 正确处理 openclaw-weixin 在扫码后返回的确认态、过渡态和附加认证信息，确保网页端状态与手机端行为一致。

#### Scenario: 手机端出现认证串但仍可继续确认
- **WHEN** 手机上扫码后出现一串认证 ID、确认串或中间态文本
- **THEN** 后端不得直接将其视为失败
- **AND** 前端应展示“已扫码，等待确认”或等价提示，而不是“轮询失败”

#### Scenario: 确认后完成登录
- **WHEN** 上游返回确认成功且包含账号凭据或可换取凭据的结果
- **THEN** 后端应将其规范化为确认成功响应
- **AND** 前端应自动停止轮询、回填配置并展示登录成功

### Requirement: 二维码内容渲染规则
系统 SHALL 正确区分二维码原始内容与可展示资源，避免错误地把确认串或认证 ID 作为图片地址或失败信息。

#### Scenario: 二维码内容为文本或链接
- **WHEN** 后端返回的是需要编码进二维码的文本或链接
- **THEN** 前端应基于该内容生成二维码图形
- **AND** 不得假设该字段一定是可直接访问的图片资源

#### Scenario: 上游返回额外提示字段
- **WHEN** 上游返回 message、auth_id、ticket、hint 或其他附加字段
- **THEN** 系统应根据字段语义映射到可见状态或调试信息
- **AND** 不得将未知但非致命字段直接视为失败

## MODIFIED Requirements
### Requirement: 二维码登录获取与状态跟踪
系统 SHALL 从“仅根据简化 status 字段判断结果”升级为“结合 status、message、附加字段和上游协议语义综合判断状态”：
- 对可恢复的中间态继续轮询。
- 对确认态立即回填凭据或进入下一步取凭据流程。
- 对真正不可恢复的错误才提示失败。

## REMOVED Requirements
### Requirement: 轮询接口仅通过单一状态字段判定成功或失败
**Reason**: 实际扫码协议包含中间态和附加认证信息，单字段判定过于脆弱。  
**Migration**: 改为基于协议字段映射表和状态机综合判断。