# 聊天页面 Markdown 与数学公式渲染 - 开发文档

## 1. 现状分析

### 1.1 当前消息渲染

当前聊天页面（`ChatPage.tsx`）的消息内容通过 `white-space: pre-wrap` 直接渲染纯文本。不支持：
- Markdown 语法（标题、列表、粗体、代码块等）
- 数学公式（LaTeX、KaTeX 语法）
- 代码高亮

### 1.2 当前依赖

`package.json` 中无任何 Markdown 或数学公式渲染库。

### 1.3 涉及文件

| 文件 | 说明 |
|------|------|
| `src/features/chat/ChatPage.tsx` | 聊天页面，消息渲染区域 |
| `src/features/chat/ChatPage.module.css` | 聊天页面样式 |
| `package.json` | 依赖管理 |

## 2. 技术选型

| 库 | 用途 | 大小 |
|------|------|------|
| `react-markdown` | Markdown 渲染核心 | ~12KB |
| `remark-math` | 识别数学公式语法 ($...$ 和 $$...$$) | ~3KB |
| `rehype-katex` | 将数学节点渲染为 KaTeX HTML | ~5KB |
| `katex` | 数学公式渲染引擎 | ~280KB CSS+字体 |
| `rehype-highlight` | 代码块语法高亮 | ~15KB |
| `highlight.js` | 语法高亮引擎 | 按需加载语言包 |
| `remark-gfm` | GitHub Flavored Markdown（表格、删除线等） | ~5KB |

## 3. 实现方案

### 3.1 安装依赖

```bash
cd frontend
npm install react-markdown remark-math rehype-katex katex remark-gfm rehype-highlight highlight.js
npm install -D @types/katex
```

### 3.2 创建 MessageContent 组件

新建 `src/features/chat/components/MessageContent.tsx`：

```tsx
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import 'katex/dist/katex.min.css'

interface MessageContentProps {
  content: string
  role: 'user' | 'assistant'
}

export function MessageContent({ content, role }: MessageContentProps) {
  // 用户消息保持纯文本渲染
  if (role === 'user') {
    return <span style={{ whiteSpace: 'pre-wrap' }}>{content}</span>
  }

  return (
    <ReactMarkdown
      remarkPlugins={[remarkMath, remarkGfm]}
      rehypePlugins={[rehypeKatex, rehypeHighlight]}
    >
      {content}
    </ReactMarkdown>
  )
}
```

### 3.3 集成到 ChatPage

在 ChatPage.tsx 的消息渲染部分，替换纯文本输出为 `<MessageContent>` 组件。

### 3.4 Markdown 样式

新建 `src/features/chat/components/MessageContent.module.css`，为 Markdown 元素定义样式：

```css
/* 代码块样式 */
.markdown-body pre {
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-sm);
  padding: 12px 16px;
  overflow-x: auto;
  margin: 8px 0;
}

.markdown-body code {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.9em;
}

/* 行内代码 */
.markdown-body :not(pre) > code {
  background: var(--color-bg-tertiary);
  padding: 2px 6px;
  border-radius: 4px;
}

/* 表格样式 */
.markdown-body table {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
}

.markdown-body th, .markdown-body td {
  border: 1px solid var(--color-border);
  padding: 8px 12px;
  text-align: left;
}

/* 列表样式 */
.markdown-body ul, .markdown-body ol {
  padding-left: 1.5em;
  margin: 4px 0;
}

/* 引用块 */
.markdown-body blockquote {
  border-left: 3px solid var(--color-primary);
  margin: 8px 0;
  padding: 4px 12px;
  color: var(--color-text-secondary);
}

/* 数学公式块 */
.markdown-body .katex-display {
  overflow-x: auto;
  padding: 8px 0;
}
```

## 4. 实施步骤

1. 安装 npm 依赖
2. 创建 `MessageContent` 组件和样式
3. 在 ChatPage 中集成组件
4. 验证 Markdown、代码高亮、数学公式渲染
5. 确保流式输出模式下增量渲染正常

## 5. 验证标准

- Markdown 标题、列表、表格、代码块正确渲染
- 行内公式 `$E = mc^2$` 和块级公式 `$$\sum_{i=1}^n$$` 正确渲染
- 代码块有语法高亮
- 流式输出模式下内容逐步更新无闪烁
- 用户消息保持纯文本渲染
- 深色/浅色主题均正常
- TypeScript 编译无错误
