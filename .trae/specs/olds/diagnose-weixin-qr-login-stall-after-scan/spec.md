# 诊断微信扫码登录停滞链路 Spec

## Why
当前通讯页在二维码成功渲染后，用户扫码并在手机端操作时，网页端可能持续停留在初始状态或长期轮询而没有“已扫码 / 已授权 / 登录成功”反馈。需要基于 openclaw-weixin 源码、现有前后端实现、浏览器表现和后端日志，重新建立从扫码到登录成功反馈的完整诊断基线，并形成可执行修复方案。

## What Changes
- 诊断通讯页二维码渲染后，从前端轮询到后端状态转发再到插件上游状态变化的完整链路
- 对照 `d:\代码\Open-AwA\插件\openclaw-weixin\源码` 源码，核查二维码状态轮询、回调/授权、凭据换取与成功事件传播机制
- 补充基于公开视频或可检索演示资料的“手机端确认动作 ↔ 网页端状态变化”预期时序基线
- 输出修复方案，覆盖代码改动点、日志补强、状态机补全、前端事件监听与回归验证步骤
- 明确 3 秒内页面出现“登录成功”反馈并触发后续跳转所需的最小实现闭环

## Impact
- Affected specs: 通讯页微信扫码登录、二维码状态轮询、微信登录成功反馈、绑定后跳转流程
- Affected code: `frontend/src/pages/CommunicationPage.tsx`、`frontend/src/services/api.ts`、`backend/api/routes/skills.py`、`backend/skills/weixin_skill_adapter.py`、相关测试文件，以及 `插件/openclaw-weixin/源码` 中 `src/auth`、`src/api`、`src/monitor` 等源码模块

## ADDED Requirements
### Requirement: 扫码登录停滞链路诊断
系统 SHALL 提供一次完整诊断，覆盖二维码显示后前端发起状态轮询、后端调用插件上游接口、上游返回扫码/确认状态、系统保存登录结果并向前端传播成功状态的全过程。

#### Scenario: 页面停滞时定位缺失响应节点
- **WHEN** 二维码已在页面 `div` 中成功渲染，用户完成扫码或手机端确认，但网页端未出现“已扫码”或“登录成功”提示
- **THEN** 诊断结果必须明确指出缺失响应发生在前端轮询、后端状态转发、插件上游状态更新、授权换票、成功事件传播中的哪一个节点

### Requirement: 源码对照核查
系统 SHALL 以 `openclaw-weixin` 源码为基线，核查当前项目对二维码状态轮询、登录确认、授权凭据换取和成功事件反馈的实现是否一致。

#### Scenario: 轮询与授权机制核查
- **WHEN** 诊断任务执行源码比对
- **THEN** 结果必须分别说明二维码状态轮询或长连接、回调 URL 或授权确认机制、code/access_token 或等价凭据换取、前端成功事件通知是否存在实现偏差

### Requirement: 预期行为基准建立
系统 SHALL 基于可检索公开视频或公开演示资料，总结手机端“授权确认”瞬间与网页端状态变化的对应时序，并将其作为修复目标基线。

#### Scenario: 视频时序映射
- **WHEN** 检索到 openclaw-weixin 插件登录成功相关视频或公开演示材料
- **THEN** 诊断结果必须提炼出手机端操作、插件状态变化、网页端提示更新之间的预期时序关系

### Requirement: 修复方案输出
系统 SHALL 产出一份可执行修复方案，覆盖需要调整的代码位置、日志点、状态机补全策略、前端事件监听方案和回归测试步骤。

#### Scenario: 形成闭环修复方案
- **WHEN** 诊断完成并确认问题根因
- **THEN** 修复方案必须说明如何确保扫码后 3 秒内页面显示“登录成功”并触发后续跳转

## MODIFIED Requirements
### Requirement: 微信扫码登录成功反馈
系统在二维码登录流程中不仅要支持 `wait`、`scaned`、`confirmed`、`expired`、`timeout` 等状态，还必须保证扫码确认后的成功状态能被持续传播到前端页面，驱动用户可见提示与后续跳转，而不是仅在后端静默保存结果。

## REMOVED Requirements
### Requirement: 无
**Reason**: 本次为诊断与修复方案补齐，不移除既有能力。
**Migration**: 无
