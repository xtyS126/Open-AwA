# Tasks
- [x] Task 1: 解析 openclaw-weixin 源码中的扫码绑定主链路
  - [x] SubTask 1.1: 盘点 `src/auth`、`src/api`、`src/monitor` 及相关入口文件，找出处理扫码回调、OAuth 授权与绑定推进的核心模块
  - [x] SubTask 1.2: 梳理扫码后从回调 URL、code、state 到 access_token、openid、账号绑定的完整时序与参数流转
  - [x] SubTask 1.3: 记录关键错误码、日志点、异常分支与重试/降级策略，形成源码侧流程基线

- [x] Task 2: 对照当前项目实现定位绑定失败根因
  - [x] SubTask 2.1: 对比当前项目后端 weixin 接口、适配器与前端通讯页在绑定阶段的实现差异
  - [x] SubTask 2.2: 明确导致绑定失败的具体代码位置、缺失逻辑、参数错误或状态校验问题
  - [x] SubTask 2.3: 输出可执行修复方案，说明修改范围、兼容性影响与验证重点

- [x] Task 3: 修复扫码绑定失败相关实现
  - [x] SubTask 3.1: 按源码真实流程修复后端扫码回调、授权换票、身份绑定或状态校验逻辑
  - [x] SubTask 3.2: 如有必要，修复前端回调处理、参数传递、错误展示或配置项使用方式
  - [x] SubTask 3.3: 补充必要日志与错误语义，确保绑定失败时能精确定位原因

- [x] Task 4: 补齐验证与回归覆盖
  - [x] SubTask 4.1: 增加或更新后端测试，覆盖扫码回调、OAuth 关键步骤、openid 绑定、异常 state/code 与错误码处理
  - [x] SubTask 4.2: 增加或更新前端测试或联调验证，覆盖扫码成功、绑定成功、绑定失败提示等关键交互
  - [x] SubTask 4.3: 运行相关测试、类型检查与必要校验，确认修复未破坏现有二维码登录闭环

- [x] Task 5: 输出绑定流程分析报告
  - [x] SubTask 5.1: 汇总源码模块映射、真实绑定流程、失败根因与修复说明
  - [x] SubTask 5.2: 汇总验证结果、已覆盖风险与剩余关注点，形成最终交付结论

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1 and Task 2
- Task 4 depends on Task 3
- Task 5 depends on Task 1, Task 2, Task 3 and Task 4
