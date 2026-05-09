# 任务列表

## 阶段一：内部实现审计

- [x] Task 1: 前端 AI 工具调用链路审计
  - [x] 审计 ChatPage.tsx 的 handleSend 方法（消息构造、模型选择、流式/非流式切换）
  - [x] 审计 api.ts 的 sendMessageStream（SSE 解析、AbortController、CSRF/X-Request-Id 注入）
  - [x] 审计 chatStore.ts 的消息/会话/模型状态管理
  - [x] 审计 executionMeta.ts 的 plan/task/tool/usage 事件解析
  - [x] 审计前端安全策略（Cookie Session、CSRF Double Submit Cookie、重试逻辑）
- [x] Task 2: 后端 AI 工具调用链路审计
  - [x] 审计 chat.py 路由层（请求接收、鉴权校验、参数反序列化、路由分发）
  - [x] 审计 agent.py 四阶段流程（理解-规划-执行-反馈）
  - [x] 审计 model\_service.py + litellm\_adapter.py（LiteLLM 网关、模型路由、超时配置）
  - [x] 审计 dependencies.py 鉴权中间件和 security/ 模块
  - [x] 审计日志系统（loguru 结构化日志、脱敏处理、request\_id 链路追踪）
  - [x] 审计可观测性（metrics.py、behavior\_logger.py、conversation\_recorder.py）
- [ ] Task 3: 输出内部审计报告
  - [ ] 编写 PlantUML 架构图（整体架构图、前端链路时序图、后端链路时序图）
  - [ ] 编写接口定义表和数据格式说明文档
  - [ ] 编写超时/重试/缓存/安全策略矩阵
  - [ ] 标注性能瓶颈与潜在风险点
  - [ ] 合并为完整的内部实现审计报告

## 阶段二：竞品与开源生态调研

- [x] Task 4: 竞品应用 AI 工具调用调研
  - [x] 调研 ChatGPT (Web) 的前端交互模式和/or 后端架构
  - [x] 调研 Claude.ai 的前端交互模式和/or 后端架构
  - [x] 调研 DeepSeek Chat 的前端交互模式和/or 后端架构
  - [x] 调研 通义千问 的前端交互模式和/or 后端架构
  - [x] 调研 Kimi 的前端交互模式和/or 后端架构
  - [x] 调研 Poe 的前端交互模式和/or 后端架构
  - [x] 汇总协议细节、鉴权方式、数据格式、错误码规范、可观测性实现的对比表格
  - [x] 输出竞品调研报告（含可视化对比图表）

## 阶段三：Python 开源库评估与集成方案

- [x] Task 5: 建立开源库评估矩阵
  - [x] 确定评估维度（许可证、活跃度、提交频率、Issue 响应、文档、测试覆盖率、性能、插件生态、安全）
  - [x] 评估 LangChain 并打分
  - [x] 评估 LlamaIndex 并打分
  - [x] 评估 Dify 并打分
  - [x] 评估 FastGPT 并打分
  - [x] 评估 CrewAI 并打分
  - [x] 评估 Agno 并打分
  - [x] 输出评估矩阵和评分对比
- [x] Task 6: 筛选候选并输出集成方案
  - [x] 筛选 3 个以上候选库
  - [x] 设计防腐层/适配器/接口隔离架构
  - [x] 制定数据模型映射方案
  - [x] 制定配置合并方案
  - [x] 评估冲突解决策略
  - [x] 编写集成方案文档
- [x] Task 7: 安全与性能调优方案
  - [x] 编写性能调优方案（连接池、批处理、异步、缓存、CDN、Gzip、HTTP/2）
  - [x] 编写安全加固方案（最小权限、沙箱、输入校验、注入防护、Rate-Limit、WAF）
  - [x] 编写监控告警方案（Prometheus、Grafana、Loki、Alertmanager、SLO/SLA）

# 任务依赖关系

- \[Task 1] 独立
- \[Task 2] 独立
- \[Task 3] 依赖于 \[Task 1, Task 2]
- \[Task 4] 独立
- \[Task 5] 独立
- \[Task 6] 依赖于 \[Task 4, Task 5]
- \[Task 7] 依赖于 \[Task 5]

# 并行执行说明

- 阶段一（Task 1-3）与 阶段二（Task 4）可完全并行
- Task 5（评估矩阵）与 Task 4（竞品调研）可并行
- Task 6-7 需等待 Task 4-5 完成后开始

