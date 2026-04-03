# Tasks
- [x] Task 1: 复盘当前实现与既有诊断结论，收敛完整修复边界
  - [x] SubTask 1.1: 对照现有前端、后端、插件适配与源码基线，列出仍未真正落地的缺口
  - [x] SubTask 1.2: 整理二维码展示、轮询中间态、确认成功、绑定结果、跳转触发、运行态授权各环节的输入输出字段
  - [x] SubTask 1.3: 明确需要保留的既有兼容逻辑与需要重构的脆弱逻辑

- [x] Task 2: 修复后端微信二维码登录协议与状态机
  - [x] SubTask 2.1: 调整二维码开始与轮询接口，使其完整兼容上游二维码内容、redirect host、确认态与附加字段
  - [x] SubTask 2.2: 将 `confirmed` 缺凭据场景改造为半成功/可恢复状态，而不是直接报 502
  - [x] SubTask 2.3: 补齐 `account_id`、`token`、`base_url`、`user_id`、`binding_status` 等字段的统一保存与返回
  - [x] SubTask 2.4: 增加结构化日志，覆盖二维码开始、每次轮询、状态切换、凭据补齐、配置保存和失败分类

- [x] Task 3: 修复前端通讯页二维码登录交互闭环
  - [x] SubTask 3.1: 确保页面根据真实二维码内容生成二维码，并正确管理会话键与轮询基址
  - [x] SubTask 3.2: 重构前端状态机，稳定展示待扫码、已扫码待确认、切换节点、半成功等待补全、登录成功、失败与过期状态
  - [x] SubTask 3.3: 登录成功后自动停止轮询、回填配置、展示绑定结果，并触发后续跳转或成功后流程
  - [x] SubTask 3.4: 针对可恢复异常避免直接中断用户流程，保留明确提示与重试能力

- [x] Task 4: 补齐登录成功后的运行态授权闭环
  - [x] SubTask 4.1: 对照源码 pairing / allowFrom 逻辑，梳理当前项目登录成功后仍不可用的原因
  - [x] SubTask 4.2: 在当前项目中补齐最小可用授权闭环，确保登录成功后后续消息链路可用或被明确提示
  - [x] SubTask 4.3: 验证绑定状态、授权状态与成功提示之间的关系，避免假成功

- [x] Task 5: 增加测试与回归验证
  - [x] SubTask 5.1: 增加后端测试，覆盖待扫码、中间态、redirect host、半成功、确认成功、不可恢复错误和绑定结果返回
  - [x] SubTask 5.2: 增加前端验证，覆盖二维码展示、扫码后状态推进、成功提示、失败提示和跳转触发
  - [x] SubTask 5.3: 运行项目可用的测试、lint、typecheck 或等价校验，修复所有相关问题
  - [x] SubTask 5.4: 按真实用户路径给出回归步骤，验证扫码确认后 3 秒内页面显示成功并完成后续流程

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1 and Task 2
- Task 4 depends on Task 2 and Task 3
- Task 5 depends on Task 2, Task 3 and Task 4
