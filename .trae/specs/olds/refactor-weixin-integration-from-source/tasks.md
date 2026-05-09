# Tasks
- [x] Task 1: 解析 open-weixin 源码并沉淀协议清单
  - [x] SubTask 1.1: 盘点源码中的入口文件、配置结构、依赖前提与运行边界
  - [x] SubTask 1.2: 梳理二维码登录相关的请求参数、响应字段、状态机、超时与重试语义
  - [x] SubTask 1.3: 梳理消息发送、拉取更新、健康检查等能力的真实请求与响应约束

- [x] Task 2: 重构后端 weixin 适配层与接口实现
  - [x] SubTask 2.1: 按源码对齐 `weixin_skill_adapter.py` 的配置映射、请求构造与错误语义
  - [x] SubTask 2.2: 按源码对齐 `skills.py` 中二维码 start/wait/exit 相关接口的字段与状态处理
  - [x] SubTask 2.3: 清理不再需要的推断式兼容逻辑，保留必要封装并统一返回结构

- [x] Task 3: 重构前端通讯页与 API 调用
  - [x] SubTask 3.1: 按源码语义调整二维码展示、轮询状态与提示文案
  - [x] SubTask 3.2: 对齐前端 API 类型定义与后端新响应结构
  - [x] SubTask 3.3: 验证成功回填、取消登录、过期重试等关键交互

- [x] Task 4: 补齐源码驱动的测试与验证
  - [x] SubTask 4.1: 增加或更新后端测试，覆盖协议字段、状态映射、错误路径与配置校验
  - [x] SubTask 4.2: 增加或更新前端测试，覆盖二维码展示与轮询交互
  - [x] SubTask 4.3: 运行相关测试、类型检查与 lint，确认重构无回归

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1 and Task 2
- Task 4 depends on Task 2 and Task 3
