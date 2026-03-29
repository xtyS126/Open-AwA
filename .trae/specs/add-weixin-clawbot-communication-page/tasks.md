# Tasks
- [x] Task 1: 明确通讯页面接入范围与交互方案
  - [x] SubTask 1.1: 确认“通讯页面”在现有路由中的落点与入口
  - [x] SubTask 1.2: 明确微信 Clawbot 配置字段与默认值
  - [x] SubTask 1.3: 明确保存、校验、健康检查的交互状态

- [x] Task 2: 实现前端微信 Clawbot 配置模块
  - [x] SubTask 2.1: 在通讯相关页面新增微信 Clawbot 配置区块
  - [x] SubTask 2.2: 实现表单校验、提交与错误提示
  - [x] SubTask 2.3: 增加健康检查触发与结果展示

- [x] Task 3: 打通前后端配置与检测接口
  - [x] SubTask 3.1: 新增或复用服务层 API 方法
  - [x] SubTask 3.2: 对接 weixin skill 适配健康检查能力
  - [x] SubTask 3.3: 统一前端显示的结构化错误信息

- [x] Task 4: 完成验证并确保无回归
  - [x] SubTask 4.1: 补充前端交互测试或关键逻辑测试
  - [x] SubTask 4.2: 进行端到端联调验证
  - [x] SubTask 4.3: 验证现有聊天与配置能力不受影响

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 2
- Task 4 depends on Task 2 and Task 3
