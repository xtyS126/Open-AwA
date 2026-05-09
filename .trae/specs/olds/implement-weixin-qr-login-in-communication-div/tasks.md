# Tasks
- [x] Task 1: 梳理并固化二维码登录到页面交互的契约
  - [x] SubTask 1.1: 对照 openclaw-weixin 登录流程明确 start/wait 输入输出字段
  - [x] SubTask 1.2: 定义前端状态机与状态文案（wait/scaned/confirmed/expired/timeout）
  - [x] SubTask 1.3: 定义异常分类与前端可见错误提示结构

- [x] Task 2: 实现后端二维码登录与登录后管理接口
  - [x] SubTask 2.1: 新增二维码开始与等待接口并桥接 weixin 适配能力
  - [x] SubTask 2.2: 新增退出登录接口并清理账号凭据
  - [x] SubTask 2.3: 统一接口响应结构并补齐鉴权和参数校验

- [x] Task 3: 在通讯页 div 实现二维码登录和登录后功能区
  - [x] SubTask 3.1: 新增二维码展示与轮询交互
  - [x] SubTask 3.2: 登录成功后自动回填并展示账号状态
  - [x] SubTask 3.3: 集成保存配置、测试连接、重新登录、退出登录操作

- [x] Task 4: 完成回归验证与测试补齐
  - [x] SubTask 4.1: 增加后端接口测试（成功/失败/超时/过期）
  - [x] SubTask 4.2: 增加前端交互测试（二维码流程与登录后操作）
  - [x] SubTask 4.3: 验证现有通讯页配置能力和侧边栏入口无回归

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1 and Task 2
- Task 4 depends on Task 2 and Task 3
