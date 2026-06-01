# Open-AwA 与 QwenPaw 对比分析报告

> 创建时间：2026-06-01
> 基于 QwenPaw v1.1.9 参考代码（`reference/QwenPaw/`）与 Open-AwA 当前实现逐层对比
> QwenPaw 由 AgentScope 团队基于 AgentScope + AgentScope Runtime + ReMe 构建

---

## 一、项目概况

| 项目 | 说明 |
|------|------|
| **QwenPaw** | 阿里通义千问生态的个人AI助理，Apache 2.0 开源，支持多智能体、多频道、Skills扩展、本地/云端部署 |
| **Open-AwA** | 正在开发的AI Agent实验平台，后端 Python FastAPI，前端 React TypeScript，微内核+插件架构 |

---

## 二、用户交互层

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| Web 控制台聊天界面 | **已有** — React 前端聊天页，功能完善 | **无** |
| CLI 命令行交互 | **缺失** — 无独立的 CLI 交互界面（如 `qwenpaw` 命令体系） | **大** |
| 桌面应用 (Tauri, macOS/Windows) | **缺失** — 无原生桌面应用 | **大** |
| 多 IM 频道接入 (6+平台) | **仅微信** — 仅有微信集成，其余均缺失 | **极大** |
| Docker 一键部署 | **缺失** — 无官方 Docker 镜像 | **大** |
| 魔搭创空间/ECS 一键部署 | **缺失** — 无云端一键部署方案 | **大** |
| 脚本一键安装 (curl/irm) | **缺失** — 无可执行安装脚本 | **大** |

### QwenPaw 支持的 IM 频道 vs Open-AwA

| 平台 | QwenPaw | Open-AwA | 差距 |
|------|---------|----------|------|
| 钉钉 (DingTalk) | **已实现** (Stream模式+AI卡片流式) | 缺失 | **大** |
| 飞书 (Feishu/Lark) | **已实现** (CardKit流式+扫码创建) | 缺失 | **大** |
| 微信 (Weixin) | **已实现** | **已实现** | **无** |
| Discord | **已实现** | 缺失 | **大** |
| Telegram | **已实现** (流式输出+推理指示) | 缺失 | **大** |
| QQ | **已实现** (工具审批交互卡片) | 缺失 | **大** |
| Slack | 待实现 | 缺失 | **中** |
| iMessage | **已实现** | 缺失 | **大** |
| Matrix | **已实现** (E2EE+SAS验证) | 缺失 | **大** |
| 企业微信 | **已实现** (流式输出) | 缺失 | **大** |

---

## 三、安装与部署

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| pip 安装 (`pip install qwenpaw`) | **无** — 需要 clone 仓库 + 手动安装依赖 | **大** |
| 脚本一键安装 (curl/irm) | **缺失** | **大** |
| Docker 镜像 (Docker Hub + ACR) | **缺失** | **大** |
| Tauri 桌面应用 (零配置双击运行) | **缺失** | **大** |
| 魔搭创空间 (云端免费运行) | **缺失** | **大** |
| 阿里云 ECS 一键部署 | **缺失** | **大** |
| 卸载命令 (`qwenpaw uninstall`) | **缺失** | **中** |

---

## 四、Coding 模式 (IDE 化工作台)

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| Web IDE 三面板布局 (文件树+编辑器+聊天) | **缺失** — 无 IDE 模式 | **极大** |
| LSP 语言服务器 (定义跳转/引用查找) | **缺失** | **极大** |
| AST 结构化搜索 (`ast-grep`) | **缺失** | **极大** |
| 内联 Diff 预览 | **缺失** | **极大** |
| Git 面板 (分支管理/暂存/提交) | **缺失** | **极大** |
| 项目目录 vs 工作区目录隔离 | **缺失** | **极大** |
| 编码专属系统提示注入 | **缺失** | **大** |
| 直接打开目录 或 导入副本 (clone/zip/新建) | **缺失** | **大** |
| worktree 隔离 (fork=True 时自动 git worktree) | **缺失** | **大** |
| `.worktreeinclude` 配置文件自动复制 | **缺失** | **中** |

---

## 五、多智能体系统

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| 多智能体工作区 (多 Agent 独立配置/记忆/技能/频道) | **部分** — SubAgent 引擎已实现，但缺独立工作区 | **大** |
| 智能体切换器 (控制台左上角下拉切换) | **缺失** | **大** |
| 控制台智能体管理 (创建/编辑/删除/列表) | **缺失** | **大** |
| 智能体间协作 (`chat_with_agent`) | **部分** — SubAgentManager 有类似概念 | **中** |
| 子 Agent 派发 (`spawn_subagent`, fork/非fork) | **部分** — `task_runtime` 有基础实现 | **中** |
| Agent 实时/后台/多轮通信模式 | **缺失** | **大** |
| CLI `qwenpaw agents list/chat` | **缺失** | **中** |
| REST API 智能体管理端点 | **部分** — 有 SubAgent API | **中** |
| 按智能体隔离 chats/定时任务/技能 | **部分** — 有 session_id 隔离 | **中** |
| PROFILE.md 自动生成 | **缺失** | **中** |

---

## 六、记忆系统

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| MEMORY.md 长期记忆 (结晶化) | **已有** — 经验管理器 + 向量存储 | **小** |
| 每日日志 memory/YYYY-MM-DD.md | **部分** — 有对话历史持久化 | **中** |
| Auto-Memory (自动记忆写入) | **部分** — 经验提取器存在 | **中** |
| Auto-Dream (记忆优化去冗存精) | **缺失** — 无自动记忆整理优化 | **大** |
| Auto-Memory-Search (每次对话自动搜索) | **缺失** | **大** |
| 混合检索 (向量 + BM25 加权融合) | **部分** — 有向量搜索但无 BM25 混合 | **中** |
| 备份与恢复 (Auto-Dream 自动备份) | **缺失** — 无记忆备份机制 | **中** |
| ReMeLight 可插拔后端 | **已有** — ChromaDB 向量存储 | **小** |
| ADBPG 云端记忆后端 (AnalyticDB) | **缺失** | **中** |
| 记忆后端自动选择 (auto/local/chroma/sqlite) | **缺失** | **中** |

---

## 七、技能系统 (Skills)

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| 技能 CRUD (创建/编辑/启用/禁用/删除) | **已有** — 完整 CRUD API | **无** |
| 技能池 (共享技能仓库) + 工作区副本 两层架构 | **缺失** — 技能直接安装，无池/副本隔离 | **大** |
| 广播 (从技能池复制到多个工作区) | **缺失** | **大** |
| 技能市场 (ClawHub/ModelScope/Aliyun 跨市场搜索) | **缺失** — 无技能市场 | **极大** |
| URL 导入 (skills.sh/clawhub.ai/lobehub/github/modelscope) | **部分** — 支持 ZIP 安装 | **大** |
| ZIP 上传安装 | **已有** | **无** |
| `/make-skill` 从对话生成技能 | **缺失** | **大** |
| 频道路由 (技能可限制在特定频道生效) | **缺失** | **中** |
| Skill Config 运行时注入 (环境变量注入) | **缺失** | **中** |
| AI 优化技能 (Beta) | **缺失** | **中** |
| 内置技能包 (13个内置技能) | **缺失** — 无内置技能库 | **大** |
| 技能版本管理与冲突检测 | **缺失** | **中** |
| 技能内容校验 (安装前扫描) | **已有** — `skill_validator.py` | **无** |
| 社区生态 (13000+ 社区技能) | **缺失** — 无社区生态 | **极大** |

### QwenPaw 内置技能 vs Open-AwA

| 技能 | QwenPaw | Open-AwA | 说明 |
|------|---------|----------|------|
| browser_cdp (浏览器CDP) | 内置 | 缺失 | Chrome DevTools Protocol 自动化 |
| browser_visible (可见浏览器) | 内置 | 缺失 | 人工参与的浏览器场景 |
| channel_message (频道消息) | 内置 | 缺失 | 主动向频道发消息 |
| cron (定时任务管理) | 内置 | 部分 | Open-AwA 有 ScheduledTaskManager |
| dingtalk_channel (钉钉接入引导) | 内置 | 缺失 | |
| docx (Word文档处理) | 内置 | 缺失 | |
| file_reader (文件阅读) | 内置 | 已有 | `file_manager.py` |
| guidance (安装配置问答) | 内置 | 缺失 | |
| himalaya (邮件管理) | 内置 | 缺失 | IMAP/SMTP 邮件操作 |
| multi_agent_collaboration | 内置 | 部分 | SubAgent 基础能力 |
| news (新闻摘要) | 内置 | 缺失 | |
| pdf (PDF处理) | 内置 | 缺失 | |
| pptx (PPT处理) | 内置 | 缺失 | |
| xlsx (表格处理) | 内置 | 缺失 | |
| QA_source_index (源码索引) | 内置 | 缺失 | |

---

## 八、插件系统

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| Provider 插件 (新增 LLM 提供商) | **已有** — LiteLLM 适配支持多提供商 | **小** |
| Hook 插件 (启动/关闭自定义代码) | **已有** — 生命周期钩子系统 | **小** |
| Command 插件 (`/command` 魔法命令) | **缺失** — 无魔法命令系统 | **大** |
| HTTP API 插件 (FastAPI APIRouter) | **已有** — 插件可注册路由 | **小** |
| 前端页面插件 (侧边栏自定义页面) | **已有** — 插件系统支持前端扩展 | **小** |
| 对话工具渲染插件 | **缺失** | **中** |
| 组件行为修改 (模块注册表) | **缺失** | **中** |
| 官方插件分发 (网站浏览+一键安装) | **缺失** | **大** |
| 插件市场 (多来源搜索) | **部分** — `MarketplacePage` 已实现，缺远端下载 | **中** |
| 插件管理 CLI (`qwenpaw plugin install/list/info/uninstall`) | **缺失** | **中** |
| 插件管理控制台 UI (多语言/筛选/搜索) | **部分** — 有 PluginsPage | **中** |
| QwenPaw Pet 桌面宠物插件 | **缺失** | **小** |
| CloudPaw 阿里云部署插件 | **缺失** | **小** |

---

## 九、安全防护

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| 工具防护 (YAML正则规则 + Shell规避守卫) | **已有** — 命令黑名单 + 危险模式正则 | **小** |
| 文件访问守卫 (敏感路径拦截) | **已有** — 路径白名单防护 | **小** |
| 技能安全扫描 (提示注入/命令注入/密钥/外泄) | **部分** — 有技能验证但无专项安全扫描 | **中** |
| Web 登录认证 | **已有** — JWT + Cookie + CSRF | **无** |
| 按频道统一访问控制 (白名单/黑名单/待审批) | **缺失** | **大** |
| 工具审批流程 (拒绝后Agent收到反馈不重试) | **部分** — 有 `confirm` 机制 | **中** |
| 备份信任控制 (导入时完整性验证) | **缺失** | **中** |
| Docker 容器隔离 | **缺失** | **大** |
| PII/敏感信息过滤 | **缺失** | **大** |

---

## 十、控制台 (Web 管理界面)

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| 侧边栏四组导航 (聊天/控制/工作区/设置) | **已有** — 侧边栏布局类似 | **小** |
| 聊天页面 (会话管理/模型选择/附件/语音) | **已有** — 功能类似 | **小** |
| 收件箱 (审批消息 + 推送消息) | **缺失** | **大** |
| 定时任务日历视图 | **缺失** — 有列表视图 | **中** |
| 定时任务模板快速创建 | **缺失** | **中** |
| 聊天草稿保存 (切换页面自动保存) | **缺失** | **中** |
| 聊天历史抽屉固定 | **缺失** | **中** |
| 多语言支持 (中/英/日/俄/印尼/葡萄牙) | **缺失** — 仅中文 | **中** |
| Token 消耗统计 | **已有** — 计费面板 | **小** |
| 环境变量管理 UI | **缺失** | **中** |
| 语音输入 (Whisper) | **缺失** | **中** |

---

## 十一、魔法命令 (Magic Commands)

| QwenPaw 命令 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| `/compact` — 压缩当前对话+保存记忆 | **缺失** | **大** |
| `/new` — 清空上下文+保存记忆 | **缺失** | **大** |
| `/clear` — 仅清空上下文不保存 | **缺失** | **大** |
| `/stop` — 停止当前任务 | **已有** — 前端的停止按钮 (AbortController) | **无** |
| `/restart` — 重启服务 | **缺失** | **中** |
| `/make-skill` — 从对话生成技能 | **缺失** | **大** |
| `/make-plan` — 生成计划 | **部分** — Planner 存在 | **中** |
| 命令体系可扩展 (插件注册) | **缺失** | **大** |

---

## 十二、心跳与定时任务

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| 心跳 (按间隔自检+摘要) | **缺失** — 无心跳机制 | **大** |
| HEARTBEAT.md 自定义心跳查询内容 | **缺失** | **大** |
| 心跳结果发送到频道 (target: main/last/inbox) | **缺失** | **大** |
| 活跃时段限制 (activeHours) | **缺失** | **中** |
| 定时任务 CRUD | **已有** — ScheduledTaskManager | **小** |
| 一次性定时任务 | **缺失** | **中** |
| 日历视图 | **缺失** | **中** |
| 定时任务模板 | **缺失** | **中** |
| 定时任务执行历史+追踪 | **部分** — 有执行记录 | **中** |
| 定时任务结果保存至收件箱 | **缺失** | **中** |
| 定时任务超时控制 | **部分** | **中** |
| 定时任务隔离执行 (独立干净上下文) | **已有** — `scheduled_execution_isolated` | **无** |
| 多智能体独立心跳+定时任务 | **缺失** | **大** |

---

## 十三、上下文管理

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| 上下文自动压缩 | **缺失** | **大** |
| 用户可选压缩 (细粒度控制) | **缺失** | **大** |
| 手动 `/compact` 触发压缩 | **缺失** | **大** |
| 文件块上下文 (图片/音频/视频纳入Token计数) | **部分** — 文件上传存在 | **中** |
| 上下文智能压缩 (进行中) | **缺失** | **大** |

---

## 十四、Coding 能力与开发者体验

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| LSP 语言服务器集成 | **缺失** | **极大** |
| AST 结构化搜索 (`ast-grep`) | **缺失** | **极大** |
| 内联 Diff 预览 | **缺失** | **极大** |
| Git 面板 (分支/暂存/提交) | **缺失** | **极大** |
| Coding Mode 专用 Prompt | **缺失** | **大** |
| 项目工作区 (project_dir / workspace 隔离) | **缺失** | **大** |
| 兼容 Claude Code 等既有 Agent (路线图) | **缺失** | **中** |

---

## 十五、可观测性与运维

| QwenPaw 能力 | Open-AwA 现状 | 差距等级 |
|---|---|---|
| Token 消耗统计 | **已有** — 计费引擎 | **小** |
| 请求 ID 追踪 | **已有** — 中间件注入 | **无** |
| 健康检查 (`/health` endpoint) | **已有** — 系统诊断 API | **无** |
| `qwenpaw doctor` 诊断命令 | **缺失** | **中** |
| `qwenpaw doctor fix` 自动修复 | **缺失** | **中** |
| 遥测数据 (匿名使用统计) | **缺失** | **小** |

---

## 十六、总体评分汇总

| 维度 | QwenPaw | Open-AwA | 完成度 |
|------|---------|----------|--------|
| 用户交互层 (多渠道+桌面+CLI+部署) | 10 | 2 | **20%** |
| 安装与部署体验 | 10 | 1 | **10%** |
| Coding 模式 (IDE 化) | 10 | 0 | **0%** |
| 多智能体系统 | 10 | 4 | **40%** |
| 技能系统 | 10 | 5 | **50%** |
| 插件系统 | 10 | 7 | **70%** |
| 记忆系统 (含进化+主动) | 10 | 6 | **60%** |
| 安全防护 | 10 | 6 | **60%** |
| 控制台 (Web UI) | 10 | 7 | **70%** |
| 魔法命令系统 | 10 | 1 | **10%** |
| 心跳与定时任务 | 10 | 5 | **50%** |
| MCP 协议 | 10 | 7 | **70%** |
| 工作流引擎 | 10 | 8 | **80%** |
| 上下文管理 | 10 | 3 | **30%** |
| 可观测性 | 10 | 7 | **70%** |
| **综合** | **10** | **4.4** | **~44%** |

---

## 十七、缺失能力优先级排序

按 `影响范围 x 缺失程度 x 用户感知度` 排序：

| 优先级 | 缺失能力 | 涉及模块 | 预估工作量 | 对标 QwenPaw 版本 |
|--------|----------|----------|------------|-------------------|
| **P0** | **多渠道 IM 接入** (钉钉/飞书/Telegram/Discord/QQ) | 交互层 | 每个渠道 3-5 天 | v1.0.0 即已支持 |
| **P0** | **一键安装部署** (pip包/Docker镜像/安装脚本) | 部署层 | 3-5 天 | v1.0.0 即已支持 |
| **P0** | **技能市场** (跨市场搜索+URL导入+技能池架构) | 技能层 | 7-10 天 | v1.1.9 技能市场 |
| **P1** | **Coding 模式** (IDE 布局+LSP+AST搜索+Git面板) | 交互层 | 15-20 天 | v1.1.9 |
| **P1** | **多智能体工作区** (独立配置/记忆/技能/频道) | 智能体层 | 10-15 天 | v0.1.0 |
| **P1** | **魔法命令系统** (/compact /new /clear /make-skill) | 交互层 | 3-5 天 | v1.0.0 即已支持 |
| **P1** | **心跳机制** (定时自检+摘要+发频道) | 任务层 | 3-5 天 | v1.0.0 即已支持 |
| **P1** | **Auto-Dream 记忆优化** (去冗存精+自动备份) | 记忆层 | 5-7 天 | v1.0.0 即已支持 |
| **P1** | **上下文压缩** (自动+手动 /compact) | 上下文层 | 5-7 天 | v1.0.0 即已支持 |
| **P2** | **Tauri 桌面应用** | 客户端 | 10-15 天 | v1.1.9 Beta |
| **P2** | **收件箱系统** (审批+推送消息) | 控制台 | 3-5 天 | v1.1.7 |
| **P2** | **智能体间协作** (chat_with_agent + spawn_subagent) | 智能体层 | 5-7 天 | v0.1.0 / v1.1.10 |
| **P2** | **内置技能包** (PDF/Office/邮件/浏览器/新闻) | 技能层 | 10-15 天 | v1.0.0 即已支持 |
| **P2** | **统一访问控制** (按频道白名单/黑名单) | 安全层 | 3-5 天 | v1.1.9 |
| **P2** | **多语言支持** (中/英/日/俄等) | 前端 | 5-7 天 | v1.0.0 即已支持 |
| **P3** | **Whisper 语音输入** | 控制台 | 1-2 天 | v1.1.6 |
| **P3** | **CLI 命令体系** (`qwenpaw` 风格的命令) | CLI | 5-7 天 | v1.0.0 即已支持 |
| **P3** | **云服务一键部署** (魔搭创空间/ECS) | 部署层 | 3-5 天 | v1.0.0 即已支持 |
| **P3** | **定时任务增强** (日历视图/模板/收件箱) | 任务层 | 3-5 天 | v1.1.7 |
| **P3** | **聊天草稿保存** | 控制台 | 1-2 天 | v1.1.9 |

---

## 十八、核心结论

Open-AwA 在**后端核心架构**（MCP 协议、插件系统、工作流引擎、记忆系统、安全框架）上与 QwenPaw 已有较好对齐，综合完成度约 **44%**。但在「**让用户真正用起来**」的体验层面差距显著。

**最需要补强的三大领域：**

### 1. 多渠道 IM 接入 — 用户体验的第一道门槛
QwenPaw 的核心价值是「在你的聊天软件里与你对话」。它支持钉钉、飞书、微信、Discord、Telegram、QQ、iMessage、Matrix、企业微信等 9+ 平台。Open-AwA 目前仅支持微信，这是**用户体验维度的最大鸿沟**。

### 2. Coding 模式 — QwenPaw 最新的杀手级能力
v1.1.9 推出的 Coding 模式将 Agent 从「聊天助手」升级为「IDE 内的协作者」，集成了 LSP 跳转、AST 结构化搜索、内联 Diff、Git 面板等开发者刚需能力。Open-AwA 在这一维度完成度为 **0%**。

### 3. 技能市场 + 技能池架构 — 生态扩展的基础设施
QwenPaw 的「技能池→工作区副本」两层架构 + 跨市场技能搜索 (ClawHub/ModelScope/Aliyun) 构成了开放的技能生态。Open-AwA 的技能系统仍是「单机手动安装」模式，缺少市场发现和社区协作能力。

**相比 QwenPaw，Open-AwA 的核心优势领域：**
- **插件系统**：蓝绿热更新 + 完整生命周期状态机，比 QwenPaw 的插件系统更成熟
- **工作流引擎**：YAML/JSON 工作流定义 + 条件分支 + 模板渲染，比 QwenPaw 更完整
- **计费系统**：全链路计费（定价/预算/用量/报表），QwenPaw 无此能力
- **RBAC 权限**：admin/developer/viewer 三级角色，比 QwenPaw 更规范

**建议策略：** 优先突击 P0 项目，重点突破「多渠道 IM」和「安装部署体验」，让用户能真正「用起来」。同时可以发挥 Open-AwA 在插件体系和计费方面的已有优势，形成差异化竞争力。

---

## 附录：QwenPaw 版本演进参考

| 版本 | 日期 | 核心新增能力 |
|------|------|-------------|
| v1.1.9 | 2026-05-27 | Coding 模式、Tauri 桌面应用、统一访问控制、技能市场、后台任务超时 |
| v1.1.8 | 2026-05-19 | 官方插件分发、QwenPaw Pet 桌面宠物、钉钉/飞书/Telegram 流式卡片 |
| v1.1.7 | 2026-05-14 | 浏览器批量操作、OAuth 2.1 MCP、定时任务日历视图、多文件附件 |
| v1.1.6 | 2026-05-09 | Whisper 语音输入、GPT Image 2 插件、火山引擎 Provider、Mermaid 图表 |
| v1.1.0 | 2026-04 | Coding Mode 初步、/make-skill 命令 |
| v1.0.0 | 2026-04-12 | CoPaw 更名 QwenPaw，正式融入 Qwen 开源生态 |
| v0.1.0 | 2026-03 | 多智能体工作区、Agent 间通信、技能池架构 |
| v0.0.x | 2026-01~02 | 基础功能：频道接入、Skills、心跳、定时任务、MCP、记忆 |

---

## 附录：参考文件索引

| 类别 | 文件路径 |
|------|----------|
| QwenPaw README (中文) | `reference/QwenPaw/README_zh.md` |
| QwenPaw 项目介绍 | `reference/QwenPaw/website/public/docs/intro.zh.md` |
| QwenPaw 技能系统 | `reference/QwenPaw/website/public/docs/skills.zh.md` |
| QwenPaw 记忆系统 | `reference/QwenPaw/website/public/docs/memory.zh.md` |
| QwenPaw 多智能体 | `reference/QwenPaw/website/public/docs/multi-agent.zh.md` |
| QwenPaw Coding 模式 | `reference/QwenPaw/website/public/docs/coding-mode.zh.md` |
| QwenPaw 频道配置 | `reference/QwenPaw/website/public/docs/channels.zh.md` |
| QwenPaw 插件系统 | `reference/QwenPaw/website/public/docs/plugins.zh.md` |
| QwenPaw 安全 | `reference/QwenPaw/website/public/docs/security.zh.md` |
| QwenPaw 心跳 | `reference/QwenPaw/website/public/docs/heartbeat.zh.md` |
| QwenPaw 控制台 | `reference/QwenPaw/website/public/docs/console.zh.md` |
| QwenPaw 魔法命令 | `reference/QwenPaw/website/public/docs/commands.zh.md` |
| QwenPaw MCP | `reference/QwenPaw/website/public/docs/mcp.zh.md` |
| QwenPaw 配置 | `reference/QwenPaw/website/public/docs/config.zh.md` |
| QwenPaw 发布说明 v1.1.9 | `reference/QwenPaw/website/public/release-notes/v1.1.9.zh.md` |
| QwenPaw 发布说明 v1.1.8 | `reference/QwenPaw/website/public/release-notes/v1.1.8.zh.md` |
| QwenPaw 发布说明 v1.1.7 | `reference/QwenPaw/website/public/release-notes/v1.1.7.zh.md` |
| Open-AwA 架构: 后端 | `docs/架构/后端架构说明.md` |
| Open-AwA 架构: 前端 | `docs/架构/前端架构说明.md` |
| Open-AwA 未来路线图 | `docs/架构/未来路线图.md` |
| Open-AwA vs OpenClaw 对比 | `docs/research/Open-AwA与OpenClaw对比分析报告.md` |
| Open-AwA 竞品调研 | `docs/audit/竞品调研报告.md` |
