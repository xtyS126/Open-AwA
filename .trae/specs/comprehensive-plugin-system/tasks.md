# Tasks

- [x] Task 1: 收敛现有插件核心模型（生命周期、上下文、错误码）
  - [x] SubTask 1.1: 定义统一状态机与状态迁移表
  - [x] SubTask 1.2: 增加幂等控制与回滚执行器
  - [x] SubTask 1.3: 为插件基类补齐生命周期钩子接口

- [x] Task 2: 实现多来源加载与沙箱执行
  - [x] SubTask 2.1: 实现本地 ZIP 与远程 URL 加载
  - [x] SubTask 2.2: 实现 npm 来源解析（含包名与版本校验）
  - [x] SubTask 2.3: 为插件实例绑定独立沙箱与资源限制

- [x] Task 3: 实现统一扩展点协议
  - [x] SubTask 3.1: 定义至少 8 类扩展点与注册接口
  - [x] SubTask 3.2: 增加 JSON Schema 校验器
  - [x] SubTask 3.3: 输出前端 TypeScript 类型声明

- [x] Task 4: 实现依赖解析与冲突诊断
  - [x] SubTask 4.1: 构建依赖图与 semver 解析器
  - [x] SubTask 4.2: 增加冲突检测与循环依赖检测
  - [x] SubTask 4.3: 生成可视化诊断数据与升级/降级建议

- [x] Task 5: 实现安全权限体系
  - [x] SubTask 5.1: 静态扫描危险模式并阻断安装
  - [x] SubTask 5.2: 运行时拦截敏感 API 调用
  - [x] SubTask 5.3: 实现授权弹窗、权限持久化与细粒度撤销

- [x] Task 6: 实现热更新与灰度发布
  - [x] SubTask 6.1: 实现双缓存更新与无感切换
  - [x] SubTask 6.2: 实现失败自动回滚
  - [x] SubTask 6.3: 实现按用户/地域/版本灰度策略

- [ ] Task 7: 打通可观测性与调试能力
  - [ ] SubTask 7.1: 每插件独立日志文件与级别动态开关
  - [ ] SubTask 7.2: 输出 API 调用、事件、性能指标
  - [ ] SubTask 7.3: 增加插件调试面板入口

- [x] Task 8: 完成 CLI 与发布链路
  - [x] SubTask 8.1: 实现 init/dev/typecheck/build 命令
  - [x] SubTask 8.2: 实现 sign/publish 命令
  - [x] SubTask 8.3: 校验插件包结构与签名文件

- [ ] Task 9: 交付文档与示例插件
  - [ ] SubTask 9.1: 完成《插件开发手册》核心章节
  - [ ] SubTask 9.2: 提供 SDK TypeScript 声明
  - [ ] SubTask 9.3: 交付 Hello World / 皮肤切换 / 数据图表示例

- [ ] Task 10: 验证与质量门禁
  - [ ] SubTask 10.1: 单元测试覆盖率达到目标（核心模块 ≥90%）
  - [ ] SubTask 10.2: 完成 Chrome/Edge/Firefox/Electron E2E 回归
  - [ ] SubTask 10.3: 校验性能与稳定性验收指标

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1
- Task 4 depends on Task 2
- Task 5 depends on Task 2 and Task 3
- Task 6 depends on Task 1 and Task 2
- Task 7 depends on Task 2
- Task 8 depends on Task 3 and Task 5
- Task 9 depends on Task 3 and Task 8
- Task 10 depends on Task 4, Task 5, Task 6, Task 7, Task 8, Task 9
