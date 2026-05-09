# Tasks

- [x] Task 1: 梳理当前微信入站消息链路与自动回复接入点
  - [x] SubTask 1.1: 盘点 `weixin_skill_adapter.py`、微信路由与通讯页当前已具备的绑定、轮询、发送、状态展示能力
  - [x] SubTask 1.2: 明确自动回复链路的最小闭环：消息拉取、文本提取、AI 调用、回复发送、游标保存、异常恢复
  - [x] SubTask 1.3: 明确微信渠道与普通聊天页在输出模式、思维链处理、日志粒度上的差异

- [x] Task 2: 实现后端微信自动回复运行时
  - [x] SubTask 2.1: 在后端增加面向单个绑定账号的长轮询处理器，能够持续获取微信新消息
  - [x] SubTask 2.2: 增加消息过滤与幂等处理，仅消费可回复且未处理过的消息
  - [x] SubTask 2.3: 接入微信发送能力，基于 `context_token` 将 AI 最终回复发回原用户
  - [x] SubTask 2.4: 增加游标持久化、重启恢复、超时重试与结构化日志

- [x] Task 3: 为微信渠道接入“无思维链”AI 回复模式
  - [x] SubTask 3.1: 明确微信自动回复调用 OpenAwA AI 的统一入口，避免绕开现有对话能力
  - [x] SubTask 3.2: 为微信渠道强制使用 direct/final-only 等价模式，禁止把 `reasoning_content` 发送到微信
  - [x] SubTask 3.3: 增加发送前内容清洗，过滤正文中可能混入的思维链标记、调试片段或内部推理文本
  - [x] SubTask 3.4: 对空回复、异常回复、超长回复给出最小可用的兜底策略

- [x] Task 4: 补齐微信自动回复的管理与可观测性
  - [x] SubTask 4.1: 在通讯页或等价入口展示“绑定状态”与“运行状态”的区别
  - [x] SubTask 4.2: 提供启动、停止、重启自动回复链路的最小控制能力
  - [x] SubTask 4.3: 展示最近轮询时间、最近错误摘要、最近一次成功发送结果或等价运行诊断

- [x] Task 5: 增加测试与回归验证
  - [x] SubTask 5.1: 增加后端测试，覆盖入站文本消息自动回复、缺字段跳过、重复消息去重、游标恢复、异常重试
  - [x] SubTask 5.2: 增加后端测试，覆盖模型返回 `reasoning_content` 或正文混入思维链时的过滤行为
  - [x] SubTask 5.3: 如涉及前端改动，增加前端测试覆盖运行状态展示与启停交互
  - [x] SubTask 5.4: 运行相关测试、类型检查与必要校验，并形成基于真实用户路径的回归步骤

- [x] Task 6: 补齐独立验收发现的剩余缺口
  - [x] SubTask 6.1: 让微信自动回复调用链真正消费 `output_mode/final_only` 或等价标志，而不只依赖发送前清洗
  - [x] SubTask 6.2: 增加后端测试，覆盖长轮询超时与临时网络失败时服务持续运行的行为
  - [x] SubTask 6.3: 形成可追溯的真实回归步骤文档，覆盖“微信发消息 -> OpenAwA AI 回复且不带思维链”
  - [x] SubTask 6.4: 重新运行相关测试并复核 checklist 未通过项

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1 and Task 2
- Task 4 depends on Task 2
- Task 5 depends on Task 2, Task 3 and Task 4
- Task 6 depends on Task 2, Task 3, Task 4 and Task 5
