# Tasks

- [x] Task 1: 梳理后端启动入口的端口配置与绑定流程
  - [x] SubTask 1.1: 定位 `python main.py` 的启动入口与默认端口来源
  - [x] SubTask 1.2: 确认当前端口绑定失败是在启动前检测还是由运行时异常触发
  - [x] SubTask 1.3: 确认现有日志与退出行为，明确需要保留的初始化流程

- [x] Task 2: 实现端口冲突处理策略
  - [x] SubTask 2.1: 为默认端口占用场景增加统一检测或异常拦截逻辑
  - [x] SubTask 2.2: 输出面向开发者的清晰提示，包括冲突端口与处理建议
  - [x] SubTask 2.3: 保证处理策略与现有配置体系兼容，不破坏正常启动路径

- [x] Task 3: 补充验证并回归启动行为
  - [x] SubTask 3.1: 为端口冲突场景补充测试或可复现验证步骤
  - [x] SubTask 3.2: 验证默认端口可用时服务仍可正常启动
  - [x] SubTask 3.3: 运行项目约定的校验命令，确认未引入新的 lint、类型或测试问题

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 2