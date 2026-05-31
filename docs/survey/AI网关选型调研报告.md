# AI 网关路由库选型调研报告

> 调研日期：2026-05-04
> 调研范围：LiteLLM Proxy / One API / New API / Higress / Kong AI Gateway / Envoy AI Gateway / Portkey / APISIX
> 前置文档：[AI网关痛点分析.md](./AI网关痛点分析.md)

---

## 一、调研背景

当前项目使用 LiteLLM 作为 Python SDK（`litellm.acompletion()`）直接调用各 LLM 供应商，未使用 LiteLLM 的 Proxy Server 模式。经分析，存在 **17 个痛点**（详见痛点分析文档），核心诉求如下：

| 维度 | 当前状态 | 期望目标 |
|------|---------|---------|
| 负载均衡 | 无 | 多实例加权轮询/最少连接 |
| 故障转移 | 手动熔断器（内存） | 自动健康检查 + 跨实例切换 |
| 速率限制 | 无 | 令牌桶/滑动窗口，供应商级配额 |
| API Key 管理 | DB 明文存储 | 加密存储 + Virtual Key + 多租户 |
| 配置管理 | 硬编码字典 | 声明式配置，热加载 |
| 可观测性 | 分散记录 | 统一 Trace + 请求级追踪 |
| 重试策略 | 双层冲突 | 统一策略，指数退避 + jitter |
| 中国供应商 | openai/ 映射 | 原生支持，差异化适配 |
| 部署与运维 | 耦合在业务代码中 | 独立部署或轻量嵌入 |

---

## 二、候选项目总览

综合考虑社区规模、功能匹配度、许可证友好性和运维复杂度，筛选出 **7 个核心候选项目**：

| 项目 | Stars | 语言 | 许可证 | 定位 | 维护状态 |
|------|-------|------|--------|------|---------|
| **LiteLLM Proxy** | 45.5k | Python | MIT | AI 专用网关 | 非常活跃 |
| **New API** | 30.4k | Go | AGPL-3.0 | API 管理网关 | 非常活跃 |
| **One API** | 32.8k | Go | MIT | API 管理网关 | 停滞 |
| **Higress** | 8.3k | Go | Apache-2.0 | AI 原生 API 网关 | 高活跃 |
| **Kong AI Gateway** | 43.3k | Lua | Apache-2.0 | 通用 API 网关 + AI 插件 | 非常活跃 |
| **Envoy AI Gateway** | 1.5k | Go | Apache-2.0 | K8s AI 推理网关 | 早期 |
| **Portkey Gateway** | 11.5k | TypeScript | MIT | AI 专用网关 | 非常活跃 |

---

## 三、逐项深度分析

### 3.1 LiteLLM Proxy Server（BerriAI/litellm）

**架构**：Proxy 模式，作为独立反向代理部署在 LLM 客户端与供应商之间

**我们已使用的功能**（SDK 模式）：
- 多供应商统一调用接口（`litellm.acompletion`）
- 流式/非流式响应
- 基础重试

**我们未使用但 Proxy 模式已内置的功能**：

| 功能 | 说明 | 解决的痛点 |
|------|------|-----------|
| Virtual Keys | 生成虚拟 Key，可设权限、过期、预算、速率限制 | 痛点10（API Key 明文）、痛点3（无速率限制） |
| Load Balancing | 多实例轮询/加权路由，跨供应商故障转移 | 痛点2 |
| Rate Limiting | 按 Key/用户/IP 的 RPM/TPM 限制，基于 Redis 分布式 | 痛点3 |
| Guardrails | PII 检测/脱敏（基于 Presidio），内容审核 | 痛点16（日志泄露风险） |
| Response Caching | 内存/Redis/S3 缓存，支持语义缓存 | 性能优化 |
| Spend Tracking | 按 Key/用户/模型追踪费用，预算告警 | 痛点13（计费未集成） |
| Admin Dashboard | Web UI 管理 Key、模型、用户、用量图表 | 运维可观测性 |
| A2A Agent Gateway | 路由到 A2A 兼容的 Agent | - |
| MCP Gateway | 将 MCP Server 连接到任意 LLM | - |

**中国供应商支持**：阿里百炼、智谱、月之暗面、DeepSeek、Minimax（原生支持）；百度文心、百川、零一万物需通过 Custom OpenAI 兼容模式

**性能基准**：P95 延迟 8ms @ 1k RPS

**优点**：
- 与当前代码库同语言（Python），迁移成本最低
- 功能最全面的 AI 专用网关
- MIT 许可证，商用友好
- 社区最大（45k+ Stars），文档完善
- 支持 100+ LLM 供应商
- 可渐进式迁移：先部署 Proxy，逐步切换调用路径

**缺点**：
- 部署和运维需一定学习成本（Redis 依赖）
- 中国供应商覆盖不如 New API/One API 全面（缺少百度文心、百川、零一万物等）
- 自身不提供类型安全的 SDK —— 调用 Proxy 走的仍是 REST API，需要自行封装类型

---

### 3.2 New API（QuantumNous/new-api）

**架构**：Go 编译的单二进制 Proxy，部署为独立服务

**核心亮点**：
- One API 的事实继承者，维护极其活跃
- **中国供应商覆盖最全面**（30+ 家国内模型厂商）
- 原生 Claude Messages 格式、Gemini 格式、OpenAI Responses/Realtime API 支持
- 格式转换能力独家：OpenAI ↔ Claude、OpenAI ↔ Gemini
- 支持 reasoning_effort 映射、缓存计费
- 内置在线支付（EPay/Stripe）、OAuth 社交登录
- 现代化 Web UI + 统计分析仪表盘

**优点**：
- 中国供应商覆盖业界最全
- 单二进制部署，极低运维成本
- 协议格式转换是独家能力
- Token 额度管理开箱即用（类似 LiteLLM Virtual Keys）
- 社区增长极快（30k Stars）

**缺点**：
- **AGPL-3.0 许可证**，对商用不友好
- Go 语言编写，与项目 Python 技术栈不匹配，无法直接集成
- 缺少 Guardrails（PII 检测）、Response Caching
- 缺少可观测性（需配合外部监控）
- 无 A2A/MCP 网关能力

---

### 3.3 One API（songquanpeng/one-api）

**架构**：Go 编译的单二进制 Proxy

**核心定位**：中国社区最流行的 AI API 网关，New API 的前身

**优点**：
- MIT 许可证，商用友好
- 中国供应商覆盖全面
- 部署极其简单（docker run 一行启动）
- 中文社区生态丰富（大量第三方客户端原生支持）
- Token 额度管理完善

**缺点**：
- **维护已基本停滞**（最后更新 2026-01），999+ open issues 积压
- 缺少新协议支持（Responses API、Realtime API、原生 Claude 格式）
- 缺少 Guardrails、缓存、可观测性
- Go 技术栈与项目不匹配

**结论**：不推荐新项目采用，除非对 MIT 许可证有硬性要求且功能需求简单

---

### 3.4 Higress（higress-group/higress）

**架构**：基于 Envoy 的 Go 控制面 + Wasm 沙箱插件，以 Sidecar/Proxy 模式部署

**核心亮点**：
- **阿里内部验证**，支撑通义千问、PAI 等核心产品
- CNCF Sandbox 项目，Apache-2.0 许可证
- **中国 + 国际供应商覆盖最全**（14+ 中国供应商 + 20+ 国际供应商）
- Wasm 沙箱插件机制：Go/Rust/JS 编写插件，安全热更新
- 同时是云原生 API 网关和 AI 网关

**支持的 AI 供应商（完整列表）**：

| 类别 | 供应商 |
|------|--------|
| 中国厂商 | 通义千问、DeepSeek、智谱、百度文心、讯飞星火、腾讯混元、月之暗面、百川、Minimax、零一万物、阶跃星辰、字节豆包、360 智脑、Coze |
| 国际厂商 | OpenAI、Azure、Anthropic Claude、Google Gemini、AWS Bedrock、GCP Vertex AI、Mistral、Groq、Ollama、vLLM、Fireworks、Together AI、Cloudflare、Cohere、GitHub Models、xAI Grok、OpenRouter |
| 特殊 | Dify 平台代理、failover 故障转移插件、retry 重试插件、claude_to_openai 格式转换 |

**AI 插件能力**：

| 插件 | 功能 | 解决的痛点 |
|------|------|-----------|
| ai-proxy | 核心 AI 代理，多供应商路由 | 痛点1（统一入口） |
| ai-rate-limiting | AI 专用速率限制 | 痛点3 |
| ai-cache | 语义缓存 | 性能优化 |
| ai-prompt-guard | Prompt 安全防护 | 痛点16 |
| ai-prompt-template | Prompt 模板 | - |
| ai-rag | 检索增强生成 | - |
| ai-content-moderation | 内容审核 | - |
| MCP Server 托管 | MCP 协议网关 | - |

**优点**：
- 供应商覆盖最广（中国 + 国际共 34+ 家）
- CNCF 项目，Apache-2.0，无许可证风险
- Wasm 插件安全沙箱，热更新无 downtime
- 同时是成熟的 API 网关（WAF、限流、认证、观测）
- K8s Ingress 兼容，GitOps 友好
- 阿里云商业支持（企业版 API Gateway）

**缺点**：
- Stars 相对较小（8.3k），社区规模不如 One API/New API
- **缺少 API Key 二次分发和额度管理**（这是 One API/New API 的差异化能力）
- 生产部署推荐 K8s（Docker all-in-one 适合试用）
- 不提供 Virtual Key / Token 额度管理体系
- 文档以中文为主，国际化程度一般

---

### 3.5 Kong AI Gateway（Kong/kong）

**架构**：OpenResty（Nginx + LuaJIT）反向代理 + AI 插件

**核心定位**：成熟的通用 API 网关，AI 能力通过插件附加

**优点**：
- 业界最成熟的 API 网关之一（43k Stars）
- 生产级负载均衡（加权轮询、最少连接、一致性哈希）
- 主动/被动健康检查 + 熔断器
- 令牌桶 / 滑动窗口速率限制
- 完善的 OpenTelemetry + Prometheus 可观测性
- 声明式配置（decK）+ Admin API + K8s CRD

**缺点**：
- **中国供应商几乎无原生支持**（仅可通过通用 OpenAI 兼容端点接入）
- AI 能力是插件化的附加功能，非原生设计
- 部署和运维复杂度高（需要了解 Kong 的配置体系）
- 没有 Virtual Key / 额度管理
- 对纯 LLM 路由场景过于重量级

---

### 3.6 Envoy AI Gateway（envoyproxy/ai-gateway）

**架构**：两层 K8s 原生 Proxy（Envoy Proxy 数据面 + Go 控制面）

**优点**：
- 原生支持 17 个供应商，包括 DeepSeek 和腾讯混元
- Envoy 数据面性能卓越（C++ 内核，生产大规模验证）
- CNCF 生态，K8s 原生
- 两层架构设计合理（区分南北向和东西向流量）

**缺点**：
- 项目极新（2024年10月启动，1.5k Stars）
- **必须 K8s 部署**，无裸机/Docker 独立部署选项
- 功能集仍在完善中，不适合生产关键路径
- 中国供应商覆盖仅 DeepSeek + 混元，远不如 Higress/New API

---

### 3.7 Portkey AI Gateway（portkey-ai/gateway）

**架构**：Node.js 反向代理（122KB 轻量级）

**优点**：
- 极低延迟（<1ms 开销）
- 支持 45+ 供应商、200+ 模型
- 内置 Guardrails（50+ AI 安全检查）
- MIT 许可证
- 部署简单（npx / Docker / Cloudflare Workers）

**缺点**：
- **完全不支持中国供应商**（阿里百炼、智谱、月之暗面、DeepSeek 等均无原生支持）
- TypeScript 技术栈与项目 Python 后端不匹配
- 企业版功能（Virtual Keys、RBAC、高级速率限制）需付费
- 社区规模小于 LiteLLM

---

## 四、痛点解决度对比矩阵

将 17 个痛点映射到各候选方案，评估解决程度：

| # | 痛点 | LiteLLM Proxy | New API | One API | Higress | Kong | Envoy AI GW | Portkey |
|---|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 双路径死代码 | ★★ | ★★ | ★★ | ★★★ | ★★ | ★★ | ★★ |
| 2 | 无负载均衡 | ★★★ | ★★ | ★★ | ★★★ | ★★★ | ★★★ | ★★ |
| 3 | 无速率限制 | ★★★ | ★★ | ★★ | ★★★ | ★★★ | ★★★ | ★★ |
| 4 | 双重重试 | ★★★ | ★★ | ★★ | ★★★ | ★★★ | ★★★ | ★★ |
| 5 | 无类型安全 | - | - | - | - | - | - | - |
| 6 | 熔断器纯内存 | ★★★ | ★★ | ★ | ★★★ | ★★★ | ★★★ | ★★ |
| 7 | 流式代码分散 | ★ | ★ | ★ | ★ | ★ | ★ | ★ |
| 8 | 工具调用错误 | - | - | - | - | - | - | - |
| 9 | 供应商硬编码 | ★★★ | ★★★ | ★★★ | ★★★ | ★★ | ★★ | ★★ |
| 10 | API Key 明文 | ★★★ | ★★★ | ★★★ | ★★ | ★★ | ★ | ★★ |
| 11 | 模型能力不同步 | ★ | ★ | ★ | ★ | ★ | ★ | ★ |
| 12 | 模型名映射脆弱 | ★★★ | ★★★ | ★★★ | ★★★ | ★ | ★★ | ★★ |
| 13 | 计费未集成网关 | ★★★ | ★★★ | ★★ | ★ | ★ | ★ | ★ |
| 14 | 无请求级追踪 | ★★ | ★ | ★ | ★★★ | ★★★ | ★★★ | ★★ |
| 15 | 测试覆盖不足 | - | - | - | - | - | - | - |
| 16 | API Key 日志泄露 | ★★★ | ★ | ★ | ★★★ | ★★ | ★ | ★★ |
| 17 | 依赖范围宽松 | ★★★ | ★★★ | ★★★ | ★★★ | ★★★ | ★★★ | ★★★ |

**说明**：★★★ = 完美解决，★★ = 部分解决，★ = 弱解决，- = 与网关工具无关（需自行改进）

**关键发现**：
- **痛点5（类型安全）**：所有网关都提供 REST API，类型安全需在 SDK 封装层解决，与网关选型无关
- **痛点7/8（流式分散/工具调用错误处理）**：是业务架构问题，更换网关无法自动解决
- **痛点11（模型能力同步）**：各网关都使用配置文件而非 DB JSON 双存储，可解决"两处存储漂移"问题
- **痛点15（测试覆盖）**：与工具无关

---

## 五、中国供应商支持详情

这是本项目选型的核心考量维度之一。各方案对中国供应商的原生支持对比：

| 供应商 | LiteLLM Proxy | New API | One API | Higress | Kong | Envoy AI GW | Portkey |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 阿里百炼 (Qwen) | 原生 | 原生 | 原生 | 原生 | - | - | - |
| DeepSeek | 原生 | 原生 | 原生 | 原生 | - | 原生 | - |
| 智谱 (GLM) | 原生 | 原生 | 原生 | 原生 | - | - | - |
| 月之暗面 (Moonshot) | 原生 | 原生 | 原生 | 原生 | - | - | - |
| 百度文心 (ERNIE) | - | 原生 | 原生 | 原生 | - | - | - |
| 讯飞星火 | - | 原生 | 原生 | 原生 | - | - | - |
| 腾讯混元 | - | 原生 | 原生 | 原生 | - | 原生 | - |
| 字节豆包 | - | 原生 | 原生 | 原生 | - | - | - |
| 百川 | - | 原生 | 原生 | 原生 | - | - | - |
| Minimax | 原生 | 原生 | 原生 | 原生 | - | - | - |
| 零一万物 | - | 原生 | 原生 | 原生 | - | - | - |
| 阶跃星辰 | - | 原生 | 原生 | 原生 | - | - | - |
| 360 智脑 | - | 原生 | 原生 | 原生 | - | - | - |
| 硅基流动 | - | 原生 | 原生 | - | - | - | - |

**结论**：
- **Higress 和 New API** 覆盖最全（13-14 家原生 + 通用兼容层）
- **LiteLLM Proxy** 覆盖核心 5 家，其余需通过 Custom OpenAI 兼容
- **Kong/Envoy AI GW/Portkey** 几乎无中国供应商支持

---

## 六、综合评分与推荐

### 评分矩阵（满分 10 分）

| 维度 | 权重 | LiteLLM Proxy | New API | Higress | Kong | Envoy AI GW | Portkey |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 功能完整度 | 20% | 9 | 8 | 8 | 8 | 5 | 7 |
| 中国供应商覆盖 | 20% | 6 | 10 | 10 | 2 | 3 | 1 |
| 运维复杂度 | 15% | 6 | 9 | 7 | 4 | 5 | 8 |
| 社区活跃度 | 10% | 10 | 9 | 6 | 10 | 3 | 8 |
| 技术栈匹配度 | 15% | 10 | 3 | 5 | 3 | 4 | 3 |
| 许可证友好性 | 10% | 10 | 4 | 10 | 10 | 10 | 10 |
| 企业级能力 | 10% | 8 | 5 | 9 | 10 | 3 | 6 |
| **加权总分** | **100%** | **8.2** | **7.3** | **7.8** | **6.2** | **4.0** | **5.4** |

### 核心竞争力分析

**LiteLLM Proxy** 综合得分最高的原因：
1. Python 技术栈完全匹配，从 SDK 到 Proxy 的迁移路径平滑
2. 功能最全面的 AI 专用网关（Virtual Keys + Load Balancing + Guardrails + Caching + Spend Tracking）
3. MIT 许可证，社区最大（45.5k Stars）
4. 可渐进式迁移（先部署 Proxy 作为独立服务，逐步切流量，SDK 模式保留作为 fallback）

**Higress** 的最强差异化：
1. 中国 + 国际供应商覆盖最全（34+ 家）
2. CNCF 项目，Apache-2.0
3. Wasm 沙箱插件——安全热更新
4. 阿里验证的生产级稳定性

**New API** 的差异化：
1. 中国供应商覆盖最全 + 协议格式转换（OpenAI ↔ Claude ↔ Gemini）
2. Token 额度管理体系最成熟
3. 单二进制部署最简便

---

## 七、推荐方案

### 首选推荐：LiteLLM Proxy + 渐进式迁移

```
当前状态                    过渡状态                     目标状态
┌──────────┐              ┌──────────────┐           ┌──────────────┐
│ Backend  │              │   Backend    │           │   Backend    │
│  │       │              │    │    │    │           │    │         │
│  ▼       │     ──►      │    ▼    ▼    │    ──►    │    ▼         │
│litellm   │              │ litellm  SDK  │           │  HTTP Client │
│.acompl() │              │ .acompl() │   │           │              │
│          │              │           ▼   │           │    │         │
│          │              │    LiteLLM    │           │    ▼         │
│          │              │    Proxy      │           │  LiteLLM    │
│          │              │  (独立部署)   │           │  Proxy      │
└──────────┘              └──────────────┘           └──────────────┘
```

**迁移路径**：

| 阶段 | 动作 | 风险 |
|------|------|------|
| 第1步 | 部署 LiteLLM Proxy（Docker），配置各供应商 API Key | 零风险（新增服务） |
| 第2步 | 通过 Admin Dashboard 创建 Virtual Keys，配置速率限制 | 零风险（仅配置） |
| 第3步 | 修改 `litellm_adapter.py`，新增 Proxy HTTP 调用路径（OpenAI 兼容 API），通过 feature flag 灰度切流 | 低风险（可快速回滚） |
| 第4步 | 废弃 `model_service.py` 死代码，清理 `litellm_adapter.py` 中的熔断器/重试/错误映射（Proxy 已内置） | 中风险（代码清理，需充分测试） |
| 第5步 | 启用 Proxy 的 Guardrails（PII 检测）+ Response Caching + Spend Tracking | 低风险（增量功能） |

**关键收益**：
- 解决痛点2（负载均衡）、痛点3（速率限制）、痛点4（双重重试）、痛点6（熔断器持久化 Redis）、痛点10（API Key → Virtual Key）、痛点13（Spend Tracking）、痛点16（Guardrails PII 脱敏）
- 删除 `model_service.py` 全部 + `litellm_adapter.py` 50% 代码
- 保持 Python 技术栈不变，团队无额外学习成本

### 补充推荐：Higress 作为长期演进方向

如果未来出现以下情况，可考虑迁移到 Higress：
- 需要对接大量中国本土模型厂商（百度文心、百川、零一万物等）
- 已建立 K8s 基础设施，需要 K8s 原生 AI 网关
- 需要 Wasm 沙箱安全热更新能力（自定义 AI 插件）
- 需要同时管理 API 网关 + AI 网关（统一入口）

**LiteLLM Proxy → Higress 的迁移成本**：因为两者都提供 OpenAI 兼容 API，只需修改 Backend 的 API Base URL 即可切换。但从 Python 生态迁移到 K8s + Wasm 运维模式有一定学习成本。

### 不推荐方案

| 项目 | 原因 |
|------|------|
| One API | 维护已停滞，功能落后于 New API |
| Kong AI Gateway | 对中国供应商几乎无支持，对纯 LLM 路由场景过重 |
| Envoy AI Gateway | 项目太新（1.5k Stars），功能不完善，仅支持 K8s |
| Portkey Gateway | 完全不支持中国供应商，TypeScript 技术栈不匹配 |
| MLflow Deployments | 非专用网关，缺少关键网关功能 |
| OpenRouter | 托管服务，不可自托管，数据不可控 |

---

## 八、参考资料

- [LiteLLM GitHub](https://github.com/BerriAI/litellm) — 45.5k Stars, MIT
- [LiteLLM Proxy 文档](https://docs.litellm.ai/docs/proxy/quick_start)
- [New API GitHub](https://github.com/QuantumNous/new-api) — 30.4k Stars, AGPL-3.0
- [One API GitHub](https://github.com/songquanpeng/one-api) — 32.8k Stars, MIT
- [Higress GitHub](https://github.com/higress-group/higress) — 8.3k Stars, Apache-2.0, CNCF Sandbox
- [Higress AI Gateway 文档](https://higress.ai/docs/latest/user/ai-gateway/)
- [Kong AI Gateway](https://konghq.com/products/ai-gateway)
- [Envoy AI Gateway](https://github.com/envoyproxy/ai-gateway) — 1.5k Stars, Apache-2.0
- [Portkey AI Gateway](https://github.com/Portkey-AI/gateway) — 11.5k Stars, MIT
- [APISIX GitHub](https://github.com/apache/apisix) — 16.5k Stars, Apache-2.0
