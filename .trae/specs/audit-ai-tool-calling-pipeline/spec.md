# AI 工具调用链路审计与集成方案规格

## Why

当前 Open-AwA 项目作为 AI Agent 执行层网关，其 AI 工具调用链路（前端发起到后端推理返回）缺少完整的内部实现文档和架构审计；同时随着 LLM 生态快速发展，需要对主流竞品和开源库进行系统性评估，为后续架构演进提供决策依据。

## What Changes

### 阶段一：内部实现审计
- 梳理前端到后端的完整 AI 工具调用链路，输出带流程图和时序图的内部实现报告
- 记录每个环节的接口定义、数据格式、超时策略、重试机制、缓存策略、安全策略
- 标注性能瓶颈与潜在风险点

### 阶段二：竞品与开源生态调研
- 选取 5 个以上主流 AI 应用的调用案例，分析前端交互模式和/or 后端架构
- 汇总协议细节、鉴权方式、数据格式、错误码规范、可观测性实现

### 阶段三：Python 开源库评估与集成方案
- 建立评估矩阵（许可证、社区活跃度、最近提交、Issue 响应等）
- 筛选 3 个以上可集成候选，给出集成方案
- 提供可运行的原型（Docker-Compose、测试、压测脚本、安全扫描、文档）

## Impact

- **Affected specs**: 项目文档体系、测试策略、部署配置
- **Affected code**: 后端 core/ 引擎层、前端 chat/ 功能模块、API 路由层

## 阶段一：内部实现审计

### Requirement: 前端调用链路审计

The system SHALL 完整记录从用户输入到 API 请求的完整前端链路。

**Scenario: 审计前端调用入口 ChatPage**
- **WHEN** 审计 ChatPage.tsx 的 handleSend 方法
- **THEN** 记录消息构造逻辑、模型选择、会话上下文传递、流式/非流式模式切换

**Scenario: 审计 API 客户端**
- **WHEN** 审计 api.ts 的 sendMessageStream
- **THEN** 记录 fetch + ReadableStream 解析 SSE 的实现、AbortController 取消机制、CSRF/X-Request-Id 注入

**Scenario: 审计状态管理**
- **WHEN** 审计 chatStore.ts (Zustand)
- **THEN** 记录消息/会话/模型选择的状态管理、executionMeta 的 plan/task/tool/usage 事件解析

**Scenario: 审计前端安全策略**
- **WHEN** 审计 Cookie Session + CSRF Double Submit Cookie 实现
- **THEN** 记录自动注入 X-Request-Id 和重试逻辑（网络错误最多 1 次、有部分输出时不重试）

### Requirement: 后端调用链路审计

The system SHALL 完整记录从 API 路由到模型推理的完整后端链路。

**Scenario: 审计聊天路由**
- **WHEN** 审计 chat.py 路由 (HTTP + WebSocket)
- **THEN** 记录请求接收、鉴权校验、参数反序列化、路由分发

**Scenario: 审计 Agent 引擎**
- **WHEN** 审计 agent.py 的四阶段流程
- **THEN** 记录理解层 (comprehension.py) -> 规划层 (planner.py) -> 执行层 (executor.py) -> 反馈层 (feedback.py) 的完整链路

**Scenario: 审计模型服务适配**
- **WHEN** 审计 model_service.py 和 litellm_adapter.py
- **THEN** 记录 LiteLLM 统一网关的模型路由、API Key 管理、超时配置、流式封装

**Scenario: 审计安全与日志**
- **WHEN** 审计 dependencies.py (鉴权)、security/ 模块、日志系统
- **THEN** 记录 JWT HttpOnly Cookie 鉴权、CSRF 防护、RBAC 权限、CORS 配置、loguru 结构化日志、脱敏处理

**Scenario: 审计性能与可观测性**
- **WHEN** 审计 metrics.py、behavior_logger.py、conversation_recorder.py
- **THEN** 记录 Prometheus 指标、行为日志、会话记录、链路追踪 (request_id)

### Requirement: 输出审计报告

The system SHALL 输出一份带流程图和时序图的内部实现报告（PlantUML 源文件 + Markdown 报告）。

**Scenario: 报告结构**
- **WHEN** 生成报告
- **THEN** 报告应包含：整体架构图、关键链路时序图、接口定义表、数据格式说明、超时/重试/缓存/安全策略矩阵、性能瓶颈标注、风险点列表

## 阶段二：竞品与开源生态调研

### Requirement: 竞品应用调研

The system SHALL 选取 5 个以上主流 AI 应用进行调研。

**Accepted apps**: ChatGPT (Web)、Claude.ai、DeepSeek Chat、通义千问、Kimi、Poe、You.com

**Scenario: 前端交互模式**
- **WHEN** 调研各竞品
- **THEN** 记录流式输出实现方式、进度条/状态指示、中断/恢复机制、多轮对话管理、工具选择器 UI、结果高亮、可复制代码块、反馈机制（点赞/点踩）

**Scenario: 后端架构**
- **WHEN** 调研各竞品
- **THEN** 记录 API 网关设计、负载均衡策略、模型路由、插件系统、函数调用编排、上下文记忆管理、多租户隔离、计量计费方案

**Scenario: 协议与安全对比**
- **WHEN** 对比各竞品协议
- **THEN** 汇总 HTTP/HTTPS、gRPC、WebSocket、SSE、GraphQL 使用情况；JWT、OAuth2、AK/SK、mTLS 鉴权方式；JSON、MessagePack、Protobuf、Multipart 数据格式；错误码规范、重试退避策略、可观测性实现（Trace/Metric/Log）

### Requirement: 输出调研报告

The system SHALL 输出竞品调研报告。

**Scenario: 报告格式**
- **WHEN** 生成报告
- **THEN** 报告应包含竞品对比表格、可视化对比图表、关键发现与建议

## 阶段三：Python 开源库评估与集成方案

### Requirement: 建立评估矩阵

The system SHALL 建立完整的开源库评估矩阵。

**Evaluation dimensions**: 许可证兼容性、社区活跃度（Star/PR/Issue）、最近提交频率、Issue 响应时间、文档完整度、测试覆盖率、性能基准、插件生态丰富度、安全审计报告

**Candidates**: LangChain、LlamaIndex、Marvin、Outlines、SemanticKernel (Python)、AutoGPT、Dify、FastGPT、CrewAI、Agno

### Requirement: 筛选并给出集成方案

The system SHALL 筛选 3 个以上可集成候选，给出完整集成方案。

**Scenario: 依赖引入**
- **WHEN** 确定候选
- **THEN** 给出 pip、poetry 引入方式，评估 Docker 化部署方案

**Scenario: 代码边界**
- **WHEN** 设计集成架构
- **THEN** 定义防腐层 (Anti-Corruption Layer)、适配器模式 (Adapter Pattern)、接口隔离 (Interface Segregation)、依赖倒置 (Dependency Inversion)

**Scenario: 数据模型映射**
- **WHEN** 处理数据兼容
- **THEN** 记录字段兼容性映射、枚举转换、版本演进策略、迁移脚本方案

**Scenario: 配置合并**
- **WHEN** 处理配置
- **THEN** 给出环境变量、YAML、.env、K8s ConfigMap/Secret 的合并方案

**Scenario: 冲突解决**
- **WHEN** 解决集成冲突
- **THEN** 评估重复路由、端口占用、日志格式、时区、序列化协议的冲突风险与解决方案

**Scenario: 性能调优**
- **WHEN** 优化性能
- **THEN** 评估连接池、批处理、异步、缓存、CDN、Gzip、HTTP/2、QUIC 的优化效果

**Scenario: 安全加固**
- **WHEN** 加固安全
- **THEN** 评估最小权限原则、沙箱隔离、输入校验、SQL/NoSQL 注入防护、XSS、CSRF、CORS、Rate-Limit、WAF 规则

**Scenario: 监控告警**
- **WHEN** 配置监控
- **THEN** 设计 Prometheus 指标、Grafana 面板、Loki 日志、Alertmanager 规则、SLO/SLA 定义

### Requirement: 提供可运行原型

The system SHALL 提供包含完整可运行原型的实现分支。

**Scenario: Docker-Compose 一键启动**
- **WHEN** 构建原型
- **THEN** 提供包含 mock 模型服务、Redis、PostgreSQL、MinIO、Traefik 网关的 docker-compose.yml

**Scenario: 多层级测试**
- **WHEN** 编写测试
- **THEN** 提供单元测试、集成测试、端到端测试用例，覆盖正常/异常/边界场景，目标覆盖率 >= 80%

**Scenario: 性能压测**
- **WHEN** 执行压测
- **THEN** 提供 k6/Locust 脚本，在 1k/10k/50k 并发下验证 P99 延迟、错误率、内存占用、GC 停顿

**Scenario: 安全扫描**
- **WHEN** 安全扫描
- **THEN** 提供 Bandit、Safety、Trivy 扫描结果，高危漏洞清零

**Scenario: 文档包**
- **WHEN** 编写文档
- **THEN** 提供 API 文档 (OpenAPI 3.1)、SDK 使用示例 (Python/JavaScript/curl)、运维手册、贡献指南
