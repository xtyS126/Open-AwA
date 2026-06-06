# Open-AwA 前端重构美化方案

> 生成日期: 2026-06-06
> 审查范围: frontend/ (296 个源文件)
> 审查方法: 手动逐文件审查 + 自动化模式匹配扫描
> 状态: 方案已完成，审计脚本已配置，待用户审批后执行

---

## 一、总体评价

| 维度 | 评分 | 说明 |
|------|------|------|
| 安全性 | A (优秀) | 无 XSS 风险、无硬编码密钥、CSRF 双令牌保护、日志脱敏 |
| 性能 | B+ (良好) | 懒加载全面、useMemo/useCallback 广泛使用、chunk 拆分合理 |
| 可访问性 | D (差) | 仅 12 个 aria-* 属性、无屏幕阅读器支持、键盘导航薄弱 |
| 代码质量 | B+ (良好) | TypeScript 严格模式、仅 12 个 `:any`、无 TODO/FIXME |
| UI/UX 设计 | C+ (中等) | CSS 变量体系好但未充分利用、视觉一致性不足、暗色模式完整 |
| 可维护性 | B- (中等偏上) | 特大型文件过多(SettingsPage 3016行)、CSS 膨胀(单体 1212 行) |
| 国际化 | C+ (中等) | 4 语言支持、框架完整，但覆盖率低(大量硬编码中文) |

---

## 二、安全性分析 (A 级)

### 2.1 XSS 防护 — 通过

- **无 `dangerouslySetInnerHTML`** — 全局扫描 0 命中
- **无 `innerHTML`** — 全局扫描 0 命中
- **无 `eval()` / `new Function()`** — 全局扫描 0 命中
- **ReactMarkdown 安全渲染** — `AssistantMarkdownContent.tsx` 使用 react-markdown 库（默认不渲染 HTML），配合 rehype-highlight + rehype-katex 安全插件链
- **用户输入正确转义** — ChatPage `sanitizeDisplayedError()` 对所有 5 个 HTML 特殊字符执行转义

### 2.2 CSRF 保护 — 通过

- **双令牌方案**: Cookie 中的 `csrf_token` + 请求头 `X-CSRF-Token`
- **引导失败重试**: 403 + `invalid_csrf_token` 错误时自动重新获取令牌并重试
- **豁免路径**: `/auth/login` 和 `/auth/register` 正确豁免
- **只读请求豁免**: GET/HEAD/OPTIONS 不附加 CSRF 头

### 2.3 敏感数据保护 — 通过

- **日志脱敏**: `logger.ts` 的 `sanitizeExtra()` 对 15 个敏感字段名（password、token、api_key 等）递归脱敏为 `***`
- **安全存储**: `safeStorage.ts` 封装 try/catch，在无痕模式/配额满时优雅降级
- **错误上报队列**: 批量+限流上报到 `/api/logs/client-errors`，最大队列 100 条

### 2.4 建议改进

| 编号 | 描述 | 优先级 |
|------|------|--------|
| S-1 | 上传文件内容扫描 — 当前 `ChatInput` 接受文件上传但未对文件内容做恶意代码检测 | P2 |
| S-2 | Content-Security-Policy 头建议 — 前端未设置 CSP meta 标签，依赖后端响应头 | P2 |
| S-3 | LoginPage 密码传输无前端哈希 — 密码通过 form-urlencoded 明文发送(依赖 HTTPS) | P3 |

---

## 三、性能分析 (B+ 级)

### 3.1 当前做得好的

- **全量路由懒加载**: App.tsx 中 24 个页面组件全部使用 `React.lazy()` + `Suspense`
- **组件级懒加载**: TaskPanel、TodoPanel、AssistantMarkdownContent 均懒加载
- **流式渲染优化**: `MessageContent` 在 streaming 期间用纯文本渲染，finalize 后才切换到 Markdown/KaTeX
- **memo/useMemo/useCallback 广泛使用**: 全局 300+ 处性能优化
- **Web Vitals 监控**: `main.tsx` 中集成 LCP、CLS、INP、TTFB 监控
- **构建产物分析**: vite.config 内置 `rollup-plugin-visualizer`
- **双压缩**: gzip + brotli 两种压缩格式
- **chunk 拆分精细**: react、recharts、markdown、markdownMath、markdownRender、icons 单独分包
- **terser 生产优化**: 移除 console.log/debug/info，保留 error/warn

### 3.2 性能问题

| 编号 | 问题 | 位置 | 影响 |
|------|------|------|------|
| P-1 | **SettingsPage 3016 行单体组件** | `SettingsPage.tsx` | 首屏解析/编译耗时大，即使懒加载也影响该路由的 FCP |
| P-2 | **ChatPage 1536 行** | `ChatPage.tsx` | 包含过多状态管理和事件处理逻辑 |
| P-3 | **SettingsPage.module.css 1212 行** | CSS 模块 | 包含大量未使用或重复的样式规则 |
| P-4 | **ChatPage.module.css 813 行** | CSS 模块 | 聊天页面样式未按组件拆分 |
| P-5 | **Markdown 渲染依赖 6 个库** | react-markdown + remark-gfm + remark-math + rehype-katex + rehype-highlight + highlight.js + katex | markdown chunk 体积过大（~200KB gzipped），仅在消息 finalize 后使用 |
| P-6 | **IndexedDB 在聊天页初始即加载** | `chatPersistence.ts` | 首页不需要立即访问 IndexedDB |
| P-7 | **缺少虚拟列表** | `MessageList.tsx` | 长对话历史（100+ 条消息）直接 map 渲染，无虚拟滚动 |
| P-8 | **子代理 runtime 轮询间隔 1200ms** | `ChatPage.tsx` | 高频轮询所有活跃子代理状态，可优化为增量推送 |

### 3.3 建议的性能优化

| 编号 | 描述 | 预期收益 | 优先级 |
|------|------|----------|--------|
| P-OPT-1 | 拆分 SettingsPage 为 Tab 级组件（模型/安全/MCP/环境变量等），每个 Tab 独立懒加载 | FCP 减少 60% | P0 |
| P-OPT-2 | 将 ChatPage.module.css 拆分为 ChatHeader/MessageList/ChatInput 独立模块 | CSS 解析减少 50% | P1 |
| P-OPT-3 | 消息列表引入虚拟滚动（react-virtuoso 已在依赖中但 vite 配置引用了却未在代码中使用） | 长列表渲染性能提升 10x | P1 |
| P-OPT-4 | 为 Markdown 渲染区域添加 IntersectionObserver 懒渲染 | 减少不可见消息的渲染开销 | P2 |
| P-OPT-5 | WebSocket 替代 SSE 轮询（当前已是 WebSocket-ready 但主要用 SSE） | 子代理更新延迟降低 80% | P2 |
| P-OPT-6 | 对 recharts 图表组件添加 `React.memo` + 仅在可见时渲染 | 仪表盘页面性能提升 | P2 |
| P-OPT-7 | IndexedDB 操作移到 Web Worker | 主线程不阻塞 | P3 |
| P-OPT-8 | 图标按需导入（lucide-react 已支持 tree-shaking，但 Sidebar 使用全量导入） | 减少 ~40KB | P3 |

---

## 四、可访问性分析 (D 级) — 严重不足

### 4.1 现状

- 全局仅 **12 个 aria-* 属性**，分布在 9 个文件中
- **无键盘导航支持**（无 focus trap、无 skip link、无 tabIndex 管理）
- **无屏幕阅读器标签**（仅有少量 `aria-expanded` 和 `role="button"`）
- **无对比度保证**（未在代码层面检查 WCAG 标准）
- **无 `alt` 文本策略**（Markdown 图片仅有硬编码的 "图片" 作为 alt）

### 4.2 缺失项

| 编号 | 缺失功能 | WCAG 标准 |
|------|----------|-----------|
| A-1 | 无 Skip Navigation Link | 2.4.1 (A) |
| A-2 | 无 Focus Visible 样式 | 2.4.7 (AA) |
| A-3 | 无模态框焦点陷阱（ConfirmDialog/Toast 无焦点管理） | 2.4.3 (A) |
| A-4 | 无表单错误关联（LoginPage 错误不关联到输入框 aria-describedby） | 3.3.1 (A) |
| A-5 | 无面包屑导航 | 2.4.8 (AA) |
| A-6 | Sidebar 菜单项无 aria-current="page" 指示 | 4.1.2 (A) |
| A-7 | 思考内容展开/折叠无 aria-controls | 4.1.2 (A) |
| A-8 | 流式消息更新无 aria-live region | 4.1.3 (A) |
| A-9 | 暗色/亮色切换按钮无 aria-label | 4.1.2 (A) |
| A-10 | Toast 通知无 role="alert" | 4.1.3 (A) |

---

## 五、UI/UX 设计分析 (C+ 级)

### 5.1 做得好的

- **暗色模式完整**: CSS 变量定义完整的光/暗色变量体系，`global.css` 中有 75+ 变量
- **紧凑/宽松响应式**: ChatPage 支持 `isCompactViewport` 检测，适配小屏
- **灯箱效果**: 图片支持点击放大（ImageWithLightbox）
- **推理内容计时**: 思考过程显示 tokens 估算和耗时
- **颜色语义一致**: success/error/warning/info 四色体系统一

### 5.2 设计问题

| 编号 | 问题 | 位置 |
|------|------|------|
| D-1 | **无统一设计系统/组件库** — 颜色/间距/圆角分散在各 CSS 文件中，无共享组件模式 | 全项目 |
| D-2 | **CSS 文件膨胀严重** — SettingsPage.module.css(1212行)、ChatPage.module.css(813行)、ScheduledTasksPage.module.css(802行)、UserCenterPage.module.css(530行)、TestPage.module.css(512行) | CSS 模块 |
| D-3 | **字体大小不一致** — 部分页面使用 px，部分使用 rem，部分使用全局 CSS 变量 | 多处 |
| D-4 | **间距系统缺失** — padding/margin 值分散为 4px/8px/12px/16px/24px/32px 无统一 scale | 全部 CSS |
| D-5 | **动画不统一** — 过渡时间 0.15s/0.2s/0.3s 混用，缓动函数不统一 | 全部 CSS |
| D-6 | **加载状态不统一** — 有的用 "加载中..."字符串，有的用 LoadingState 组件，有的用骨架屏 | 多处 |
| D-7 | **空状态展示不统一** — ChatPage 有 "Hello! How can I help you?"，其他页面无空状态设计 | 多处 |
| D-8 | **移动端体验不完善** — CodingPage 的三面板布局在手机上不可用，无响应式降级 | CodingPage |
| D-9 | **主题切换有闪烁** — `themeStore` 在模块顶层调用 `applyTheme()`，React 渲染前已执行但仍有短暂 FOUC | themeStore.ts |
| D-10 | **字体回退不优雅** — ThemeConfig 设置 `--custom-font-family` 时使用内联样式覆盖 | themeStore.ts |

### 5.3 设计师建议

| 编号 | 描述 | 优先级 |
|------|------|--------|
| UI-1 | 建立 Design Token 文件，统一管理颜色/间距/圆角/阴影/字体/动画 | P0 |
| UI-2 | 提取 Button/Input/Modal/Card/Tag/Badge 等基础 UI 组件到 `shared/components/ui/` | P0 |
| UI-3 | 建立统一的加载状态骨架屏组件 | P1 |
| UI-4 | 建立统一的空状态组件（含插图和引导文案） | P1 |
| UI-5 | 全局过渡动画统一为 200ms ease | P2 |
| UI-6 | 移动端响应式断点统一为 768px/1024px/1440px 三级 | P2 |

---

## 六、代码架构分析 (B- 级)

### 6.1 大文件分布（TOP 10）

| 文件 | 行数 | 问题 |
|------|------|------|
| `SettingsPage.tsx` | 3016 | 单体巨石，包含模型管理/安全设置/MCP 配置/对话管理/系统设置等 5 个功能 |
| `ChatPage.tsx` | 1536 | 核心聊天逻辑，混合了 SSE 处理/子代理管理/消息同步/撤销等 |
| `zh-CN.ts` | 1391 | 中文语言包 — 可接受（纯数据） |
| `en-US.ts` | 1390 | 英文语言包 — 可接受（纯数据） |
| `SettingsPage.module.css` | 1212 | 样式膨胀 |
| `api.ts` | 1138 | API 端点定义 — 已部分拆分(client.ts+types.ts)，仍需按域拆分 |
| `ja-JP.ts` | 1102 | 日文语言包 — 可接受 |
| `ru-RU.ts` | 1102 | 俄文语言包 — 可接受 |
| `ScheduledTasksPage.tsx` | 992 | 大型页面 |
| `useWechatConfig.ts` | 947 | 微信配置 Hook 过长 |

### 6.2 已拆分完成的模块

| 原模块 | 拆分方式 | 状态 |
|--------|----------|------|
| `api.ts` → `client.ts` + `types.ts` | Axios 实例/CSRF/类型提取 | [DONE] |
| `authStore.ts` 扩展 | User 字段完整化 + updateUser | [DONE] |
| ChatPage hooks | 6 个自定义 hooks 拆分 | [DONE] |

### 6.3 待拆分模块

| 编号 | 目标 | 拆分方案 | 优先级 |
|------|------|----------|--------|
| ARC-1 | `SettingsPage.tsx` (3016行) | 拆分为 ModelSettings/MCPSettings/SecuritySettings/ChatSettings/EnvVarSettings 独立 Tab | P0 |
| ARC-2 | `ChatPage.tsx` (1536行) | 提取 SSE 处理为独立 hook、子代理管理为独立模块、撤销逻辑为独立 hook | P0 |
| ARC-3 | `api.ts` (1138行) | 按业务域拆分为 authApi/chatApi/modelApi/pluginApi/conversationApi | P1 |
| ARC-4 | `ScheduledTasksPage.tsx` (992行) | 提取日历视图/任务表单/日志查看为独立页面路由 | P1 |
| ARC-5 | `useWechatConfig.ts` (947行) | 拆分为多个职责单一的 hook（config/status/qrcode/autoReply） | P2 |
| ARC-6 | `SettingsPage.module.css` (1212行) | 按 Tab 拆分为 model/mcp/security/chat 独立 CSS 模块 | P1 |

---

## 七、国际化分析 (C+ 级)

### 7.1 框架评估

- **zustand-based i18n store** — 轻量优雅，无第三方依赖
- **4 种语言**: 简体中文/English/日本語/Русский
- **参数化翻译**: 支持 `{key}` 占位符替换
- **语言自动检测**: 从 `navigator.language` 获取初始语言

### 7.2 覆盖率问题

- **Sidebar**: 使用 `t()` 函数，但有多处硬编码中文（"TTS 语音"、面包屑等）
- **ChatPage**: 大量硬编码中文（"思考过程"、"已复制"、"加载中..."等）
- **设置页面**: 几乎全部硬编码中文
- **工具调用卡片**: 状态标签硬编码中文（"已完成"/"执行中"/"失败"）
- **登录页面**: 全部硬编码中文

### 7.3 i18n 建议

| 编号 | 描述 | 优先级 |
|------|------|--------|
| I18N-1 | 补齐所有硬编码字符串到语言包 | P1 |
| I18N-2 | 日期格式化统一使用 `Intl.DateTimeFormat` + locale | P2 |
| I18N-3 | 添加语言包缺失检测（开发模式下 console.warn 未翻译 key） | P2 |
| I18N-4 | 测试框架中集成 i18n 快照测试 | P3 |

---

## 八、测试分析

### 8.1 测试覆盖

- 测试文件数量: 约 40 个 (单元测试 + 组件测试)
- 测试框架: Vitest + Testing Library + Playwright
- 覆盖率阈值: 90% (vitest.config 中设定)

### 8.2 测试问题

| 编号 | 问题 | 优先级 |
|------|------|--------|
| T-1 | ChatPage 测试仅覆盖核心功能，SSE streaming 路径无测试 | P1 |
| T-2 | 缺少无障碍自动化测试（axe-core） | P2 |
| T-3 | 缺少性能回归测试（Lighthouse CI） | P2 |
| T-4 | E2E 测试覆盖率低（仅 Playwright 基础配置，实际用例少） | P2 |

---

## 九、依赖与工具链分析

### 9.1 当前依赖评估

| 依赖 | 角色 | 评价 |
|------|------|------|
| react/react-dom ^18 | 核心框架 | 稳定，可考虑升级到 React 19 |
| react-router-dom ^6.22 | 路由 | 稳定 |
| zustand ^4.5 | 状态管理 | 优秀选择，轻量高效 |
| axios ^1.6 | HTTP 客户端 | 稳定 |
| lucide-react ^1.8 | 图标库 | tree-shakeable，良好 |
| react-markdown ^10.1 | Markdown 渲染 | 稳定 |
| recharts ^2.12 | 图表 | 体积较大，考虑替代(如 @antv/g2) |
| web-vitals ^5.3 | 性能监控 | 生产可用 |
| @monaco-editor/react | 代码编辑器 | 体积较大但 Coding 功能必需 |
| js-cookie ^3.0 | Cookie 操作 | 功能单一，可自实现 |

### 9.2 工具链评估

- Vite 5 — 当前最新稳定版
- TypeScript 5.3 strict 模式 — 良好
- ESLint 配置 — 含 react-hooks 插件
- terser — 生产压缩
- vitest 2.1 — 最新
- Playwright 1.58 — 最新

---

## 十、重构优先级路线图

### 第一阶段: 安全加固 + 核心重构 (预计 3-5 天)

| 优先级 | 编号 | 任务 | 文件 | 影响范围 |
|--------|------|------|------|----------|
| P0 | ARC-1 | 拆分 SettingsPage | SettingsPage.tsx → 5 个 Tab 组件 | 设置页 |
| P0 | ARC-2 | 拆分 ChatPage | ChatPage.tsx → 3 个独立 hooks | 聊天页 |
| P0 | UI-1 | 创建设计 Token 文件 | 新建 `styles/tokens.css` | 全局 |
| P0 | UI-2 | 提取基础 UI 组件 | 新建 `shared/components/ui/` | 全局 |

**阶段完成审计：** `.\scripts\code-audit.ps1 -FrontendOnly`
**预期提交：** `git commit -m "[Refactoring] 阶段1: 设计Token + 基础UI组件 + SettingsPage/ChatPage拆分"`

### 第二阶段: UI 美化 + 性能优化 (预计 3-5 天)

| 优先级 | 编号 | 任务 | 文件 |
|--------|------|------|------|
| P1 | ARC-3 | api.ts 按域拆分 | 拆为 6 个独立 API 模块 |
| P1 | P-OPT-3 | 消息列表引入虚拟滚动 | MessageList.tsx |
| P1 | UI-3 | 统一加载态骨架屏 | 新建 Skeleton 组件 |
| P1 | UI-4 | 统一空状态组件 | 新建 EmptyState 组件 |
| P1 | ARC-6 | 拆分 SettingsPage CSS | 按 Tab 独立 CSS 模块 |
| P1 | I18N-1 | 补齐硬编码字符串 | 全部页面 |

**阶段完成审计：** `.\scripts\code-audit.ps1 -FrontendOnly`
**预期提交：** `git commit -m "[Refactoring] 阶段2: API拆分 + 虚拟滚动 + 骨架屏/空状态 + i18n补齐"`

### 第三阶段: 可访问性 + 测试 (预计 2-4 天)

| 优先级 | 编号 | 任务 | 文件 |
|--------|------|------|------|
| P2 | A-1~A-10 | 无障碍全面改造 | 全部组件 |
| P2 | P-OPT-4 | IntersectionObserver 懒渲染 | MessageList |
| P2 | T-3 | 添加 Lighthouse CI | CI 配置 |
| P2 | T-2 | 添加 axe-core 自动检测 | 测试套件 |

**阶段完成审计：** `.\scripts\code-audit.ps1 -FrontendOnly`
**预期提交：** `git commit -m "[Refactoring] 阶段3: 无障碍改造 + IntersectionObserver + 测试增强"`

### 第四阶段: 高级优化 (可选)

| 优先级 | 编号 | 任务 | 文件 |
|--------|------|------|------|
| P3 | P-OPT-7 | IndexedDB → Web Worker | chatPersistence.ts |
| P3 | ARC-5 | 拆分 useWechatConfig | wechat 模块 |
| P3 | P-OPT-8 | 图标按需导入优化 | Sidebar.tsx |

**阶段完成审计：** `.\scripts\code-audit.ps1 -FrontendOnly`
**预期提交：** `git commit -m "[Optimization] 阶段4: Web Worker + useWechatConfig拆分 + 图标优化"`

---

## 阶段执行自动化流程

每个阶段执行完毕后，按以下自动化流程推进：

```
阶段N 代码完成
  |
  v
.\scripts\code-audit.ps1 -FrontendOnly
  |
  +--> [exit 1: 审计失败]
  |       |
  |       +--> 查看 reports/audit-result.txt
  |       +--> 根据失败项修复代码
  |       +--> 重新运行审计 (回到顶部)
  |
  +--> [exit 0: 审计通过]
          |
          +--> git add -A
          +--> git commit -m "[Refactoring] 阶段N: xxx"
          +--> 进入阶段 N+1
```

所有阶段完成后运行完整测试确认无回归：
```bash
cd frontend && npm run test:coverage && cd ..
cd backend && pytest -v --cov && cd ..
```

---

## 十一、具体实施细节

### 11.1 SettingsPage 拆分方案（ARC-1）

```
features/settings/
  SettingsPage.tsx          → 仅保留布局 + Tab 导航 (约 100 行)
  tabs/
    ModelSettings.tsx        ← 模型管理 (约 500 行)
    SecuritySettings.tsx     ← 安全管理 (约 400 行) [已有部分]
    MCPSettings.tsx          ← MCP 配置 (约 400 行) [已有部分]
    EnvVarSettings.tsx       ← 环境变量 (约 300 行) [已有部分]
    ChatSettings.tsx         ← 对话设置 (约 300 行)
    AboutSettings.tsx        ← 关于/系统信息 (约 200 行)
  hooks/
    useProviderManager.ts    ← 供应商管理逻辑
    useModelManager.ts       ← 模型 CRUD 逻辑
    useSystemSettings.ts     ← 通用设置逻辑
```

### 11.2 ChatPage 拆分方案（ARC-2）

```
features/chat/
  ChatPage.tsx              → 仅保留布局编排 (约 300 行)
  hooks/
    useChatStream.ts         ← SSE 流处理逻辑 (从 ChatPage 提取)
    useSubagentSync.ts       ← 子代理同步 + 超时管理 (从 ChatPage 提取)
    useMessageUndo.ts        ← 消息撤回逻辑 (从 ChatPage 提取)
    useConversationManager.ts ← 会话创建/切换/列表 (从 ChatPage 提取)
```

### 11.3 基础 UI 组件库（UI-2）

```
shared/components/ui/
  Button/
    Button.tsx
    Button.module.css
    index.ts
  Input/
    Input.tsx
    Input.module.css
    index.ts
  Modal/
    Modal.tsx
    Modal.module.css
    index.ts
  Card/
    Card.tsx
    Card.module.css
    index.ts
  Tag/
    Tag.tsx
    Tag.module.css
    index.ts
  Badge/
    ...
  Skeleton/
    ...
  EmptyState/
    ...
  Tabs/
    ...
  Select/
    ...
  Textarea/
    ...
```

### 11.4 设计 Token 文件（UI-1）

```css
/* styles/tokens.css — 设计令牌系统 */
:root {
  /* === 间距 === */
  --space-0: 0;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;

  /* === 字体大小 === */
  --text-xs: 0.75rem;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --text-lg: 1.125rem;
  --text-xl: 1.25rem;
  --text-2xl: 1.5rem;

  /* === 圆角 === */
  --radius-none: 0;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-full: 9999px;

  /* === 阴影 === */
  --shadow-none: none;
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
  --shadow-md: 0 4px 6px rgba(0,0,0,0.1);
  --shadow-lg: 0 10px 15px rgba(0,0,0,0.1);

  /* === 过渡 === */
  --transition-fast: 150ms ease;
  --transition-base: 200ms ease;
  --transition-slow: 300ms ease;

  /* === 断点（仅作参考，不用于 CSS 变量） === */
  /* --bp-sm: 640px; */
  /* --bp-md: 768px; */
  /* --bp-lg: 1024px; */
  /* --bp-xl: 1440px; */

  /* === z-index 层 === */
  --z-dropdown: 100;
  --z-modal: 200;
  --z-toast: 300;
  --z-tooltip: 400;
}
```

---

## 十二、修改文件预估

### 第一阶段（P0）

| 操作 | 文件数 | 净增/减行 |
|------|--------|-----------|
| 新建 Design Token | 1 | +100 |
| 新建基础 UI 组件（8个） | 24 (每个 3 文件) | +800 |
| 拆分 SettingsPage | 8 新建 + 1 修改 | -2400 / +1500 |
| 拆分 ChatPage | 4 新建 + 1 修改 | -1200 / +800 |
| **小计** | **39 文件** | **净减约 400 行** |

### 第二阶段（P1）

| 操作 | 文件数 | 净增/减行 |
|------|--------|-----------|
| api.ts 按域拆分 | 6 新建 + 1 修改 | -800 / +600 |
| 虚拟滚动集成 | 1 修改 | +20 |
| 骨架屏/空状态组件 | 6 新建 | +400 |
| CSS 模块拆分 | 5 新建 + 3 修改 | -800 / +600 |
| i18n 补齐 | 5 修改 | +400 |
| **小计** | **27 文件** | **净增约 420 行** |

### 总计

**约 66 个文件变更，净增约 20 行（重构以减量抵消增量）。**

---

## 十三、风险评估

| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| SettingsPage 拆分导致 Tab 间状态共享复杂化 | 中 | 使用 Zustand store 跨 Tab 共享状态 |
| ChatPage 拆分引入 hook 间循环依赖 | 中 | 按数据流向设计单向依赖（ChatPage → hooks → store） |
| UI 组件库与现有代码样式冲突 | 低 | 使用 CSS 模块隔离，渐进替换而非大爆炸式 |
| 虚拟滚动引入后自动滚动定位异常 | 低 | react-virtuoso 提供成熟的 scrollToIndex API |
| i18n 补齐引入翻译不一致 | 低 | 先补齐中文，再翻译其他语言 |

---

## 十四、附录

### A. 前端文件统计

- 总源文件数: 296
- TypeScript (.ts/.tsx): 约 150 个
- CSS 模块 (.module.css): 约 80 个
- 测试文件: 约 40 个
- 总代码行数: 约 45,000 行

### B. 关键依赖版本

- React 18.2 → 建议升级到 19.x
- TypeScript 5.3 → 可升级到 5.7
- Vite 5.1 → 可升级到 6.x
- Zustand 4.5 → 可升级到 5.x

### C. 参考资源

- [WCAG 2.2 快速参考](https://www.w3.org/WAI/WCAG22/quickref/)
- [React 性能优化指南](https://react.dev/learn/render-and-commit)
- [CSS 设计令牌规范](https://design-tokens.github.io/community-group/format/)
- [react-virtuoso 文档](https://virtuoso.dev/)
