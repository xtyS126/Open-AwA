# Tasks
- [x] Task 1: 梳理扫码确认后的真实协议与状态映射
  - [x] SubTask 1.1: 对照 openclaw-weixin 源码与现有日志，整理 start/wait 在扫码后可能返回的字段与状态
  - [x] SubTask 1.2: 定义“待扫码、已扫码待确认、确认成功、已过期、可恢复异常、不可恢复异常”的映射规则
  - [x] SubTask 1.3: 明确哪些字段用于二维码内容展示，哪些字段仅用于状态提示或凭据换取

- [x] Task 2: 修复后端二维码轮询协议兼容
  - [x] SubTask 2.1: 调整 `wait` 接口解析逻辑，兼容确认串、认证 ID、附加 message 和中间态
  - [x] SubTask 2.2: 规范化后端响应结构，确保前端能稳定区分继续轮询、确认成功和真正失败
  - [x] SubTask 2.3: 对真实不可恢复错误保留明确错误信息，对可恢复异常降级为继续等待

- [x] Task 3: 修复前端二维码与状态展示
  - [x] SubTask 3.1: 根据真实二维码内容生成页面二维码，不把附加认证文本误当图片或错误信息
  - [x] SubTask 3.2: 优化扫码后状态文案，正确展示“已扫码，等待确认”等中间态
  - [x] SubTask 3.3: 登录成功后正确停止轮询并自动回填账号信息

- [x] Task 4: 补齐回归验证
  - [x] SubTask 4.1: 增加后端测试覆盖认证串、中间态、确认成功与不可恢复错误
  - [x] SubTask 4.2: 增加前端交互验证覆盖扫码后状态变化和失败提示
  - [x] SubTask 4.3: 运行相关测试与类型检查，确认旧的通讯页能力无回归

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1 and Task 2
- Task 4 depends on Task 2 and Task 3
