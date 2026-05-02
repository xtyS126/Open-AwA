# 主流 AI 应用 AI 工具调用竞品调研报告

> 调研日期：2026-04-24
> 调研范围：ChatGPT、Claude.ai、DeepSeek Chat、通义千问、Kimi、Poe

---

## 目录

1. [ChatGPT (Web) --- chat.openai.com](#1-chatgpt-web)
2. [Claude.ai --- claude.ai](#2-claudeai)
3. [DeepSeek Chat --- chat.deepseek.com](#3-deepseek-chat)
4. [通义千问 --- tongyi.aliyun.com](#4-通义千问)
5. [Kimi --- kimi.moonshot.cn](#5-kimi)
6. [Poe --- poe.com](#6-poe)
7. [综合对比表格](#7-综合对比表格)
8. [关键发现与对 Open-AwA 项目的建议](#8-关键发现与对-open-awa-项目的建议)

---

## 1. ChatGPT (Web)

### 前端交互模式

| 维度 | 实现详情 |
|------|----------|
| **流式输出** | 基于 SSE (Server-Sent Events)，通过 `fetch` + `ReadableStream` 实现逐 token 推送。前端使用 `EventSource` 或自定义 SSE 解析器处理事件流 |
| **进度/状态指示** | 生成中显示"停止"按钮 + 闪烁光标动画；工具调用时显示加载态（"正在搜索..."等） |
| **中断/恢复** | 支持一键中断（AbortController），中断后不可恢复，需重新生成 |
| **多轮对话** | 消息列表结构，客户端维护完整 messages 数组，每次请求携带全部上下文 |
| **工具选择器 UI** | 输入框下方工具栏：文件上传（回形针图标）、联网搜索（地球图标）、DALL-E 图像生成、代码解释器、Canvas 编辑器；支持 GitHub/Google Drive 等第三方应用连接 |
| **代码/渲染** | Markdown 渲染使用 `marked` + `highlight.js`；支持代码块行号、复制按钮、语言标签 |
| **结果高亮** | 引用来源标注为角标，表格、列表、数学公式 (LaTeX) 完整渲染 |
| **反馈机制** | 点赞/点踩按钮（每条回复右下角），支持文本反馈；可报告有害内容 |
| **Canvas 功能** | 独立编辑界面，支持 Python 代码执行（浏览器内沙箱运行）、代码/文档协作编辑 |

### 后端架构

| 维度 | 公开信息 |
|------|----------|
| **API 网关** | 使用 Spring Boot 构建的 API Gateway，统一入口处理 chat 事件、工具请求、反馈。提供认证、配额、幂等性和请求校验 |
| **模型路由** | 自动路由到 GPT-4o / GPT-4 Turbo / GPT-4 / GPT-3.5 等；Plus 用户可手动选择模型。模型参数上下文窗口：GPT-4 Turbo 128K，GPT-4o 128K |
| **函数调用** | 原生支持 Function Calling，模型可输出结构化 JSON 调用外部工具。最新支持 MCP (Model Context Protocol) 协议标准 |
| **上下文管理** | 服务端维护上下文窗口，超限时自动截断（依据 Token 数）。Plus/Pro 用户拥有更大上下文配额 |
| **多租户隔离** | 基于 Organization + Project 两级隔离，API Key 绑定到具体 Project |
| **计费模式** | Free（有限 GPT-3.5/4o-mini）、Plus $20/月、Pro $200/月、Team/Enterprise 按席位定价 |

### 协议与安全

| 维度 | 公开信息 |
|------|----------|
| **通信协议** | HTTPS (REST API)、SSE (流式)、WebSocket (高级语音模式) |
| **鉴权方式** | API Key (Bearer Token)、OAuth2 (第三方应用连接)、Session Cookie (Web 端) |
| **数据格式** | JSON (请求/非流式响应)、SSE 事件流 (流式)、`text/event-stream` Content-Type |
| **错误码规范** | 400 (Bad Request)、401 (Invalid Auth)、403 (Forbidden)、404 (Not Found)、429 (Rate Limit)、500 (Server Error)。含详细的 `error` 对象和 `type` 字段 |
| **可观测性** | Console 面板提供 Token 用量、请求延迟、速率限制状态等监控指标 |

---

## 2. Claude.ai

### 前端交互模式

| 维度 | 实现详情 |
|------|----------|
| **流式输出** | 基于 SSE (Server-Sent Events)，定义了详细的事件类型体系：`message_start`、`content_block_start`、`content_block_delta`、`content_block_stop`、`message_delta`、`message_stop`。每个事件包含 `type`、`index`、`delta` 等结构化字段 |
| **进度/状态指示** | thinking（思考）阶段可视化，支持"Summarized Thinking"思维链摘要显示；生成中显示停止按钮 |
| **中断/恢复** | 支持中断，支持 Extended Thinking 模式下中断后恢复部分推理内容 |
| **多轮对话** | Messages API 方式，客户端携带完整消息历史，支持 Prompt Caching 优化重复前缀 |
| **工具选择器 UI** | 原生支持 Tool Use / Function Calling；文件上传（拖拽或点击，支持 PDF/图片/代码文件等）；Skills（技能）系统可在设置中启用/禁用特定能力 |
| **代码/渲染** | Markdown 完整渲染；Artifacts 功能可将代码/文档在右侧独立面板中实时预览，支持 React 组件渲染（sandboxed iframe）、HTML/CSS/JS 实时预览 |
| **结果高亮** | 来源引用编号标注，可点击展开；支持表格、列表、数学公式渲染 |
| **反馈机制** | 点赞/点踩按钮，支持附带文本描述反馈 |

### 后端架构

| 维度 | 公开信息 |
|------|----------|
| **API 网关** | Anthropic API Gateway，统一管理 Messages API、Streaming、Tool Use 等端点 |
| **模型路由** | Claude 3.5 Sonnet / Claude 3 Opus / Claude 3 Haiku 等模型系列，API 参数指定 model 名称。Enterprise 用户支持专属部署 |
| **函数调用** | 原生 Tool Use API：通过 `tools` 参数定义工具列表，模型返回 `tool_use` 类型的 content block，包含 `name`、`input` 字段。支持并行工具调用和链式调用 |
| **上下文管理** | 200K token 上下文窗口（Claude 3 系列），支持 Prompt Caching（前缀缓存降低延迟和成本） |
| **多租户隔离** | Organization > Workspace 层级隔离，API Key 绑定到 Workspace |
| **计费模式** | Free 有限使用、Pro $20/月、Team $25/月/席位、Enterprise 定制。API 按 Token 计费，Prompt Caching 提供 50% 折扣 |

### 协议与安全

| 维度 | 公开信息 |
|------|----------|
| **通信协议** | HTTPS (REST API)、SSE (流式)、WebSocket (部分场景) |
| **鉴权方式** | `x-api-key` 请求头 (API Key)、Bearer Token (OAuth) |
| **数据格式** | JSON (非流式)、SSE 结构化事件流（event + data 格式）、`text/event-stream` |
| **错误码规范** | 400 (Invalid Request)、401 (Unauthorized)、403 (Forbidden)、404 (Not Found)、429 (Rate Limit，含 `retry-after` 头部)、500 (Internal Error)、529 (Overloaded)。响应头中包含 `anthropic-ratelimit-*` 系列字段 |
| **可观测性** | Console 面板提供用量统计、速率限制状态、支出追踪；API 响应头包含 `request-id` 用于追踪 |

---

## 3. DeepSeek Chat

### 前端交互模式

| 维度 | 实现详情 |
|------|----------|
| **流式输出** | 基于 SSE 协议，兼容 OpenAI API 格式，设置 `stream: true` 启用。支持 asyncio + aiohttp 实现高并发 |
| **进度/状态指示** | 双阶段响应机制：思考过程可视化（深度思考模型 R1 显示推理链），生成中显示停止按钮 |
| **中断/恢复** | 支持中断（AbortSignal / stream.close），不支持下线后恢复 |
| **多轮对话** | 消息列表结构，使用 messages 数组维护上下文，每次请求携带完整历史 |
| **工具选择器 UI** | 输入框下方"联网搜索"开关（勾选启用）；文件上传（回形针图标，支持 PDF/Excel/Word/图片等，单文件最大 100MB）；深度思考模式切换 |
| **代码/渲染** | Markdown 渲染 + 代码语法高亮；代码块标题栏显示语言标签和复制按钮 |
| **结果高亮** | 联网搜索结果标注来源 URL 链接；引用溯源；表格、列表完整渲染 |
| **反馈机制** | 点赞/点踩按钮（每条回复下方） |

### 后端架构

| 维度 | 公开信息 |
|------|----------|
| **API 网关** | DeepSeek API Gateway，兼容 OpenAI Chat Completion API 格式，支持一键迁移 |
| **模型路由** | DeepSeek V3 (1M context)、DeepSeek R1 (128K context)、DeepSeek V2 (64K context) 等，API 参数指定 model |
| **函数调用** | 支持 Function Calling，与 OpenAI 兼容格式。工具定义采用 JSON Schema 描述，模型自主决策调用时机 |
| **上下文管理** | V3/V4 支持 1M token 上下文窗口；Context Caching 技术自动缓存重复前缀（system prompt、对话历史），降低成本和延迟 |
| **多租户隔离** | API Key 绑定到账户，支持多 Key 管理，可按组织隔离 |
| **计费模式** | 免费 Web 使用（有限制）；API 按 Token 计费，价格极具竞争力；Context Caching 提供额外折扣 |

### 协议与安全

| 维度 | 公开信息 |
|------|----------|
| **通信协议** | HTTPS REST API、SSE (Chat Completion 流式) |
| **鉴权方式** | API Key (Bearer Token，`Authorization: Bearer <key>`) |
| **数据格式** | JSON、SSE 事件流（OpenAI 兼容格式） |
| **错误码规范** | 遵循 OpenAI 兼容错误格式：`invalid_request_error`、`authentication_error`、`rate_limit_error` 等 |
| **可观测性** | API 控制台提供使用统计、API Key 管理和消费记录 |

---

## 4. 通义千问

### 前端交互模式

| 维度 | 实现详情 |
|------|----------|
| **流式输出** | 基于 SSE 协议，兼容 OpenAI Chat Completion 流式格式。后端设置 `stream: true` 后返回 `text/event-stream` |
| **进度/状态指示** | 生成中显示"停止"按钮，加载状态动画，联网搜索时显示"正在搜索..."指示器 |
| **中断/恢复** | 支持中断（AbortController），不可恢复 |
| **多轮对话** | 标准 messages 结构（role: user/assistant/system），客户端维护完整上下文列表。每次请求携带全部历史消息 |
| **工具选择器 UI** | 输入框下方工具栏：文件上传（回形针图标，支持 PDF/Word/Excel/PPT/图片/音频，单文件最大 120MB）；联网搜索开关；`@通义万相` 图像生成；代码解释器 |
| **代码/渲染** | Markdown 完整渲染，代码块语言识别 + 语法高亮（highlight.js），复制按钮，行号 |
| **结果高亮** | 表格渲染、列表、引用标注；支持数学公式 (LaTeX) |
| **反馈机制** | 点赞/点踩按钮 |

### 后端架构

| 维度 | 公开信息 |
|------|----------|
| **API 网关** | 阿里云百炼平台 API Gateway，统一管理模型调用、API Key 认证、流量控制。兼容 OpenAI 格式（`dashscope.aliyuncs.com/compatible-mode/v1`） |
| **模型路由** | Qwen 系列模型（Qwen-Max、Qwen-Plus、Qwen-Turbo 等），API 参数指定 model。支持自定义路由策略 |
| **函数调用** | 原生 Tool Calling / Function Calling 支持，兼容 OpenAI 工具定义格式。模型返回结构化 JSON 指定调用工具及参数 |
| **上下文管理** | 128K token 上下文窗口（Qwen2.5 系列）。通过 messages 参数手动维护对话历史 |
| **多租户隔离** | 阿里云 RAM (Resource Access Management) 体系，API Key 可绑定到子账户、限制权限、设置配额 |
| **计费模式** | 免费 Web 端（有限次数）；API 按 Token 计费（Qwen3.6-Plus：输入 ¥0.8/百万Token，输出 ¥2/百万Token）；百炼平台提供预付费资源包 |

### 协议与安全

| 维度 | 公开信息 |
|------|----------|
| **通信协议** | HTTPS REST API、SSE (流式) |
| **鉴权方式** | API Key (Bearer Token，`Authorization: Bearer <key>`)，阿里云 RAM 访问控制 |
| **数据格式** | JSON、SSE 事件流（OpenAI 兼容格式） |
| **错误码规范** | 标准 HTTP 状态码 + 阿里云错误码体系（InvalidParameter、Unauthorized、Throttling 等） |
| **可观测性** | 阿里云百炼控制台提供调用量统计、延迟监控、消费记录；支持日志服务 (SLS) 集成 |

---

## 5. Kimi

### 前端交互模式

| 维度 | 实现详情 |
|------|----------|
| **流式输出** | 基于 SSE 协议，兼容 OpenAI/Anthropic 流式格式。Kimi Code CLI Web UI 额外支持 WebSocket 双向通信 |
| **进度/状态指示** | 生成中显示停止按钮；文件处理时显示进度条；思考链可视化显示（K2 Thinking 模型可展示推理过程） |
| **中断/恢复** | 支持中断，不支持下线后恢复 |
| **多轮对话** | 标准 messages 结构，客户端手动管理上下文（Kimi API 本身无状态）。工具调用结果通过 tool role 消息回传 |
| **工具选择器 UI** | 文件上传（PDF 最多 500 页、Word、Excel、图片 OCR、URL 自动解析）；联网搜索开关（1000+ 网站实时检索）；支持拖拽上传 |
| **代码/渲染** | Markdown 完整渲染 + 代码语法高亮；工具输入参数 UI 支持展开查看详情和语法高亮 |
| **结果高亮** | 搜索结果标注来源链接；表格、列表完整渲染；数学公式支持 |
| **反馈机制** | 点赞/点踩按钮 |

### 后端架构

| 维度 | 公开信息 |
|------|----------|
| **API 网关** | Moonshot Platform API Gateway，兼容 OpenAI/Anthropic 接口格式 |
| **模型路由** | Kimi K2 (1T MoE，32B 激活)、Kimi K2 Thinking、Kimi K2 0905 (256K context) 等。高速版本支持 60-100 TPS 输出 |
| **函数调用** | 原生 Tool Calling 支持：四阶段流程（工具定义 -> 调用决策 -> 执行 -> 结果回传）。K2 Thinking 支持"边思考边调用工具"模式，单个任务可执行 200-300 次顺序工具调用 |
| **上下文管理** | 128K (K2) / 256K (K2 0905) token 上下文窗口。通过 messages 参数手动维护对话历史 |
| **多租户隔离** | API Key 绑定到账户，支持 Bearer Token 鉴权隔离 |
| **计费模式** | 免费 (20 次/小时，2000 tokens/回复)；API 从 $0.15/百万输入 Token，$2.50/百万输出 Token；Premium 约 $19/月 |

### 协议与安全

| 维度 | 公开信息 |
|------|----------|
| **通信协议** | HTTPS REST API、SSE (流式)、WebSocket (Kimi Code CLI) |
| **鉴权方式** | Bearer Token (API Key，`Authorization: Bearer <key>`) |
| **数据格式** | JSON、SSE 事件流（OpenAI/Anthropic 兼容格式） |
| **错误码规范** | 标准 HTTP 状态码，遵循 OpenAI 兼容错误格式 |
| **可观测性** | 平台控制台提供 API Key 管理、用量统计、消费记录 |

---

## 6. Poe

### 前端交互模式

| 维度 | 实现详情 |
|------|----------|
| **流式输出** | 基于 SSE 协议，支持多模型统一流式输出格式 |
| **进度/状态指示** | 生成中显示停止按钮；Points 余额指示器；Bot 切换时显示加载态 |
| **中断/恢复** | 支持中断，不可恢复 |
| **多轮对话** | 自动上下文管理，约 16K token 记忆窗口。跨平台同步对话历史（Web/iOS/Android/Vision Pro） |
| **工具选择器 UI** | 左侧边栏显示 Bot 列表（官方 + 自定义）；Bot 切换下拉选择器；图像生成 Bot 支持文生图；支持文件上传和联网搜索（取决于具体 Bot 能力） |
| **代码/渲染** | Markdown 渲染，代码块语法高亮（因具体 Bot 能力而异） |
| **结果高亮** | 引用来源标注；搜索结果显示来源链接 |
| **反馈机制** | 点赞/点踩（Poe 协议支持），Bot 评分系统 |

### 后端架构

| 维度 | 公开信息 |
|------|----------|
| **API 网关** | Poe Proxy / Orchestration Layer，统一中转所有模型 API 调用。核心职责：模型路由、API Key 管理、协议转换、用量计量 |
| **模型路由** | 动态模型路由引擎，基于查询意图选择最优模型（技术类 -> CodeLlama，创意类 -> GPT-4，对话类 -> Claude 等）。支持 200+ 模型接入 |
| **函数调用** | Poe Protocol：定义 Bot 与 Poe 之间的通信规范。Server Bot 通过 Webhook 接收消息并返回响应。支持自定义工具逻辑 |
| **上下文管理** | 约 16K token 上下文窗口，平台自动管理历史消息截断 |
| **多租户隔离** | API Key 绑定到用户账户，支持用户自己的 API Key 或平台提供的共享 Key |
| **计费模式** | Points（积分）制：Free (3,000 pts/天)、Basic $4.99/月 (10,000 pts/天)、Premium $19.99/月 (100 万 pts/月)、Ultra $49.99-$99.99/月 (250 万 ~ 500 万 pts/月)。不同模型消耗不同积分 |

### 协议与安全

| 维度 | 公开信息 |
|------|----------|
| **通信协议** | HTTPS REST API、SSE (流式)、WebSocket (部分场景)、GraphQL (内部) |
| **鉴权方式** | API Key (Bearer Token)、Poe-Formkey (Web 端)、`Authorization: Bearer <access_key>` (Poe Protocol) |
| **数据格式** | JSON、SSE 事件流、Poe Protocol 消息格式（支持 `text/plain`、`text/markdown` 等 Content-Type） |
| **错误码规范** | 标准 HTTP 状态码；Poe Protocol 定义详细的错误响应格式 |
| **可观测性** | 创作者控制台提供 Bot 使用统计、Points 消耗、用户活跃度等指标 |

---

## 7. 综合对比表格

### 前端交互模式对比

| 维度 | ChatGPT | Claude.ai | DeepSeek Chat | 通义千问 | Kimi | Poe |
|------|---------|-----------|---------------|---------|------|-----|
| **流式协议** | SSE (ReadableStream) | SSE (结构化事件) | SSE (OpenAI 兼容) | SSE (OpenAI 兼容) | SSE / WebSocket | SSE |
| **进度指示** | 停止按钮 + 光标动画 | thinking 可视化 + 停止按钮 | 双阶段(思考+回答) + 停止按钮 | 停止按钮 + 加载动画 | 思考链可视化 + 停止按钮 | 停止按钮 + Points 余额 |
| **中断机制** | AbortController | stream.close() | AbortSignal | AbortController | AbortController | 支持 |
| **文件上传** | 图片/PDF/代码/数据(DALL-E/Code Interpreter) | 图片/PDF/代码等 | PDF/Excel/Word/图片(100MB) | PDF/Word/Excel/PPT/图片/音频(120MB) | PDF(500页)/Word/Excel/图片/URL | 取决于 Bot 能力 |
| **联网搜索** | 内置 + Bing 集成 | 内置（Pro） | 开关按钮 | 开关按钮 | 开关按钮(1000+ 网站) | 取决于 Bot |
| **图像生成** | DALL-E 3 (内置) | Artifacts (代码生成 UI) | 不支持 | @通义万相 | 不支持 | 图像 Bot |
| **代码/渲染** | marked + highlight.js + Canvas | Artifacts (React sandbox iframe) | 代码高亮 + 复制按钮 | highlight.js + 复制按钮 | 语法高亮 + 展开详情 | 基础 Markdown |
| **反馈机制** | 赞/踩 + 文本反馈 | 赞/踩 | 赞/踩 | 赞/踩 | 赞/踩 | 赞/踩 + 评分 |
| **特殊功能** | Canvas 编辑器、Apps (MCP) | Skills、Artifacts、Extended Thinking | 深度思考(R1)双阶段 | 通义万相、代码解释器 | 200-300次连续工具调用、URL自动解析 | 200+模型切换、Bot 创建 |

### 后端架构对比

| 维度 | ChatGPT | Claude.ai | DeepSeek Chat | 通义千问 | Kimi | Poe |
|------|---------|-----------|---------------|---------|------|-----|
| **API 兼容** | 原生 | 原生 | OpenAI 兼容 | OpenAI 兼容 | OpenAI/Anthropic 兼容 | OpenAI 兼容 |
| **上下文窗口** | 128K | 200K | 1M (V3/V4) | 128K | 256K (K2 0905) | ~16K |
| **函数调用** | Function Calling + MCP | Tool Use API | Function Calling | Tool Calling | Tool Calling (200-300 顺序调用) | Poe Protocol |
| **缓存策略** | 无公开详情 | Prompt Caching | Context Caching | 无公开详情 | 无公开详情 | 无 |
| **多租户** | Org > Project | Org > Workspace | API Key 绑定 | RAM > 子账户 | API Key 绑定 | API Key 绑定 |
| **模型路由** | 自动 + 手动选择 | 手动指定 | 手动指定 | 手动指定 | 手动指定 | 动态意图路由 |

### 协议与安全对比

| 维度 | ChatGPT | Claude.ai | DeepSeek Chat | 通义千问 | Kimi | Poe |
|------|---------|-----------|---------------|---------|------|-----|
| **传输协议** | HTTPS/SSE/WebSocket | HTTPS/SSE | HTTPS/SSE | HTTPS/SSE | HTTPS/SSE/WebSocket | HTTPS/SSE/GraphQL |
| **鉴权方式** | Bearer Token / OAuth2 | x-api-key / Bearer | Bearer Token | Bearer Token | Bearer Token | Bearer Token / Formkey |
| **数据格式** | JSON / text/event-stream | JSON / SSE 事件流 | JSON / SSE | JSON / SSE | JSON / SSE | JSON / SSE / Poe Protocol |
| **错误码** | HTTP + OpenAI error type | HTTP + anthropic-ratelimit-* | OpenAI 兼容 | HTTP + 阿里云错误码 | 标准 HTTP | 标准 HTTP + Protocol 错误 |
| **可观测性** | Console 分析面板 | Console + Rate limit headers | API 控制台 | 阿里云 SLS + 控制台 | 平台控制台 | 创作者分析面板 |

---

## 8. 关键发现与对 Open-AwA 项目的建议

### 关键发现

#### 1. SSE 是行业标准的流式协议
所有 6 个竞品均采用 SSE (Server-Sent Events) 作为流式输出的核心协议。SSE 相较于 WebSocket 的优势在于：基于标准 HTTP 协议、实现简单、天然支持断线重连、浏览器原生 `EventSource` 支持。Kimi CLI 额外使用 WebSocket 主要用于双向实时通信。

#### 2. OpenAI API 格式成为事实标准
DeepSeek、通义千问、Kimi、Poe 均提供 OpenAI 兼容 API，降低开发者迁移成本。这意味着 Open-AwA 优先兼容 OpenAI 协议可覆盖最广泛的生态。

#### 3. Function Calling / Tool Calling 是核心差异化能力
- **Kimi K2 Thinking** 的"边思考边调用工具"模式（200-300 次顺序调用）代表了 tool use 的前沿方向
- **Claude** 的 Tool Use API 支持并行调用和链式调用，配合 Structured Output 实现精确控制
- **ChatGPT** 的 MCP (Model Context Protocol) 正在推动工具调用标准化

#### 4. 前端渲染栈趋于统一
React + TypeScript + Vite 是主流选择（Claude、Kimi、ChatGPT 桌面端）。Markdown 渲染（markdown-it / marked）配合代码高亮（highlight.js）是标准方案。

#### 5. 上下文窗口持续扩大
从 ChatGPT 的 128K 到 DeepSeek V3 的 1M token，上下文窗口的竞争持续升级。Context Caching 技术（DeepSeek、Claude）有效降低了长上下文的成本。

#### 6. 积分/Points 制和订阅制并行
ChatGPT/Claude 采用固定订阅制；Poe 采用 Points 积分制，按模型消耗差异化定价；DeepSeek/通义千问/Kimi 采用 API 按量计费 + 免费 Web 端组合模式。Points 制在聚合平台场景更具灵活性。

#### 7. 反馈机制标准化
所有平台均提供点赞/点踩作为核心反馈方式，这也是 RLHF 训练数据的重要来源。

### 对 Open-AwA 项目的建议

#### 架构层面

1. **采用 SSE 作为核心流式协议**
   - 兼容 OpenAI 事件流格式，降低第三方模型接入成本
   - 前端使用 `ReadableStream` + `fetch` 处理 SSE，避免依赖 EventSource（不支持自定义请求头）
   - 实现标准的 `data: [DONE]` 终止标记

2. **API 设计优先兼容 OpenAI 格式**
   - Chat Completion API `/v1/chat/completions` 作为核心端点
   - 支持 `stream`、`tools`、`tool_choice` 等标准参数
   - 兼容 `messages` 数组结构（system/user/assistant/tool role）

3. **实现灵活的模型路由引擎**
   - 参考 Poe 的动态路由设计，支持按意图/模型能力/成本自动路由
   - 支持多模型混排（同一对话中切换模型）
   - 抽象统一的 Tool Calling 接口适配层

4. **设计 Points/积分 计费系统**
   - 参考 Poe 的 Points 制，实现差异化定价
   - 免费用户每日赠送积分，不同模型/工具消耗不同积分
   - 支持订阅制（固定积分包月）

#### 前端层面

1. **技术栈选型**
   - React + TypeScript + Vite（行业标准组合）
   - markdown-it + highlight.js 用于内容渲染
   - Tailwind CSS 用于样式（Claude 最新实践）

2. **工具 UI 设计**
   - 输入框下方工具栏承载主要工具入口（参考通义千问/ChatGPT 设计）
   - 联网搜索作为开关按钮独立展示
   - 文件上传支持拖拽 + 点击（参考 Kimi 的 URL 自动解析功能）
   - 工具调用过程可视化（参考 DeepSeek Chat 的双阶段机制）

3. **交互体验**
   - 实现多级状态指示：思考中 -> 工具调用中 -> 生成中 -> 完成
   - 支持 AbortController 中断请求
   - 代码块统一支持：语法高亮、复制、语言标签、行号
   - 引用溯源标注（搜索结果的 URL 来源标注）

#### 安全与可观测性

1. **认证与鉴权**
   - API Key (Bearer Token) 作为主要鉴权方式
   - 支持 JWT 用于 Web 端会话管理
   - 细粒度权限控制（参考阿里云 RAM 模型）

2. **错误规范**
   - 自定义标准化错误码体系
   - 速率限制：429 + `retry-after` 头部
   - 错误响应中包含 `type`、`message`、`param`、`code` 字段

3. **可观测性**
   - 每次 API 响应返回 `request-id` 用于追踪
   - 响应头中包含速率限制状态字段（`ratelimit-remaining`、`ratelimit-reset`）
   - 提供管理控制台查看用量、延迟、消费

#### 创新差异化方向

1. **借鉴 Kimi K2 的"思考中调用工具"模式**
   - 实现工具调用与推理过程的混合展示
   - 让用户可见模型的思考链和工具选择逻辑

2. **参考 Claude Artifacts 的交互式预览**
   - 代码/文档在侧边栏实时渲染预览
   - Sandbox iframe 安全沙箱执行

3. **参考 Poe 的多模型生态**
   - 允许第三方开发者上传自定义 Bot
   - 提供 Bot 创建工具和市场化分发

4. **前瞻性支持 MCP 协议**
   - ChatGPT 推动的 MCP (Model Context Protocol) 正在成为工具调用标准
   - 原生支持 MCP 可实现与 ChatGPT Apps 生态的兼容

---

> 本报告基于公开信息和网络搜索整理，部分信息可能随产品更新而变化。建议定期更新本调研。
