# 微信扫码硬编码参数影响排查 Spec

## Why
近期仍出现“扫码返回仅为普通字符串”的现象，且用户怀疑是源码中的硬编码参数被本地改写后导致协议偏移。需要做一次可复现、可追溯的深度排查，并形成结论文档。

## What Changes
- 新增针对“硬编码参数是否导致扫码返回字符串”的专项排查流程。
- 对比 `插件/openclaw-weixin/别人解析` 与当前项目实现中的关键参数与请求构造。
- 结合终端日志与前后端链路，给出证据化根因判断与风险结论。
- 输出一份详尽排查文档，包含结论、证据、复现与建议动作。

## Impact
- Affected specs: weixin-qr-login, weixin-adapter-response-normalization, frontend-auth-session
- Affected code: `backend/api/routes/skills.py`, `backend/skills/weixin_skill_adapter.py`, `frontend/src/services/api.ts`, `frontend/src/pages/CommunicationPage.tsx`

## ADDED Requirements
### Requirement: 硬编码参数影响专项排查
系统 SHALL 提供一份基于源码与日志证据的专项排查结果，明确“硬编码参数改动”是否会导致扫码仅返回普通字符串。

#### Scenario: 证据化分析
- **WHEN** 用户提交终端日志与“硬编码参数导致异常”的怀疑
- **THEN** 排查结果必须包含参数对比表、调用链路、响应样例、证据出处与明确结论

### Requirement: 排查文档可执行性
系统 SHALL 输出可执行的排查与修复建议，避免仅给抽象结论。

#### Scenario: 交付文档
- **WHEN** 排查完成
- **THEN** 文档必须包含问题现象、根因判断、反证分析、复现步骤、回归验证建议与上线风险评估

## MODIFIED Requirements
### Requirement: 微信扫码异常定位流程
现有扫码异常定位流程需增加“硬编码参数漂移”检查项，并要求与上游参考实现逐项对照后再下结论。

## REMOVED Requirements
### Requirement: 无
**Reason**: 本变更为增量排查，不移除既有能力。
**Migration**: 无需迁移。
