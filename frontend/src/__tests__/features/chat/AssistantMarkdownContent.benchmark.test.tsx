import '@testing-library/jest-dom/vitest'
import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import AssistantMarkdownContent from '@/features/chat/components/AssistantMarkdownContent'

/**
 * AssistantMarkdownContent 渲染性能基准测试（SubTask 22.4）
 *
 * 测量不同长度 Markdown 消息的首次渲染耗时：
 * - 短消息（~200 字符）：典型聊天回复
 * - 中等消息（~2000 字符）：详细解答
 * - 长消息（~10000 字符）：超长技术文档（含代码块、表格、公式、嵌套列表）
 *
 * 阈值设定（基于开发机本地测量基线，留 3-5x 安全余量避免 flaky）：
 * - 短消息 < 100ms
 * - 中等消息 < 500ms
 * - 长消息 < 2000ms
 *
 * 测试方法：
 * - 使用 performance.now() 包裹 render() 调用
 * - 每个用例重复运行 N 次，取中位数降低噪声
 * - 渲染后立即 unmount 释放 DOM 节点，避免累积影响
 */

/** 生成短 Markdown 消息（~200 字符） */
function generateShortMarkdown(): string {
  return [
    '## 简短回答',
    '',
    '这是一段**普通文本**，包含 *斜体* 和 `行内代码`。',
    '',
    '- 列表项 1',
    '- 列表项 2',
    '',
    '> 引用块示例',
  ].join('\n')
}

/** 生成中等长度 Markdown 消息（~2000 字符） */
function generateMediumMarkdown(): string {
  const lines: string[] = []
  lines.push('## 详细解答')
  lines.push('')
  lines.push('本节将详细说明解决方案的核心思路。')
  lines.push('')
  lines.push('### 1. 问题分析')
  lines.push('')
  for (let i = 0; i < 5; i += 1) {
    lines.push(`第 ${i + 1} 点：需要在系统中实现 **关键能力 ${i + 1}**，` +
      `通过 ` + '`utility_' + i + '` 函数封装核心逻辑，确保可复用。')
  }
  lines.push('')
  lines.push('### 2. 代码示例')
  lines.push('')
  lines.push('```typescript')
  lines.push(`function process(data: Input): Output {`)
  lines.push(`  const result = transform(data)`)
  lines.push(`  return validate(result)`)
  lines.push(`}`)
  lines.push('```')
  lines.push('')
  lines.push('### 3. 数学公式')
  lines.push('')
  lines.push('行内公式 $E = mc^2$ 与块级公式：')
  lines.push('')
  lines.push('$$')
  lines.push('\\int_{0}^{\\infty} e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}')
  lines.push('$$')
  lines.push('')
  lines.push('### 4. 表格')
  lines.push('')
  lines.push('| 字段 | 类型 | 说明 |')
  lines.push('| --- | --- | --- |')
  for (let i = 0; i < 6; i += 1) {
    lines.push(`| field_${i} | string | 字段 ${i} 的描述文本 |`)
  }
  return lines.join('\n')
}

/** 生成超长 Markdown 消息（~10000 字符） */
function generateLongMarkdown(): string {
  const lines: string[] = []
  lines.push('# 完整技术文档')
  lines.push('')
  // 5 个大段，每段包含代码块、表格、列表、公式
  for (let section = 0; section < 5; section += 1) {
    lines.push(`## 第 ${section + 1} 章：实现细节`)
    lines.push('')
    lines.push(`本章描述第 ${section + 1} 部分的实现，包含多个子模块。`)
    lines.push('')
    // 段落文本
    for (let p = 0; p < 4; p += 1) {
      lines.push(
        `段落 ${p + 1}：在 *模块 ${section}.${p}* 中，我们需要确保 ` +
        `**数据一致性**与 *并发安全*。` +
        `使用 \`sync_mutex_${section}_${p}\` 原语协调多线程访问。`,
      )
      lines.push('')
    }
    // 列表
    lines.push('### 关键步骤')
    lines.push('')
    for (let s = 0; s < 6; s += 1) {
      lines.push(`${s + 1}. 步骤 ${s + 1}：执行 \`action_${section}_${s}()\`，处理状态转换`)
    }
    lines.push('')
    // 代码块
    lines.push('### 代码实现')
    lines.push('')
    lines.push('```python')
    lines.push(`def section_${section}_handler(ctx):`)
    for (let line = 0; line < 8; line += 1) {
      lines.push(`    # 处理逻辑第 ${line + 1} 行`)
      lines.push(`    value_${line} = ctx.get('field_${line}')`)
    }
    lines.push('    return sum([value_0, value_1, value_2, value_3])')
    lines.push('```')
    lines.push('')
    // 表格
    lines.push('### 参数表')
    lines.push('')
    lines.push('| 参数 | 类型 | 默认值 | 说明 |')
    lines.push('| --- | --- | --- | --- |')
    for (let r = 0; r < 8; r += 1) {
      lines.push(`| param_${r} | ${r % 2 === 0 ? 'int' : 'string'} | ${r} | 参数 ${r} 用途描述 |`)
    }
    lines.push('')
    // 公式
    lines.push('### 数学模型')
    lines.push('')
    lines.push('$$')
    lines.push(`f_${section}(x) = \\sum_{i=0}^{n} \\alpha_i x^i + \\beta`)
    lines.push('$$')
    lines.push('')
  }
  return lines.join('\n')
}

/** 重复渲染并返回中位数耗时（ms） */
function measureRenderMedian(
  content: string,
  runs: number = 5,
  streaming: boolean = false,
): number {
  const samples: number[] = []

  for (let i = 0; i < runs; i += 1) {
    const start = performance.now()
    const { unmount } = render(
      <AssistantMarkdownContent content={content} streaming={streaming} />,
    )
    const end = performance.now()
    samples.push(end - start)
    unmount()
  }

  samples.sort((a, b) => a - b)
  return samples[Math.floor(samples.length / 2)]
}

describe('AssistantMarkdownContent 渲染性能基准', () => {
  it('短消息（~200 字符）渲染时间 < 100ms', () => {
    const content = generateShortMarkdown()
    const median = measureRenderMedian(content)

    console.warn(
      `[markdown benchmark] 短消息（${content.length} 字符）中位数渲染耗时: ${median.toFixed(3)}ms`,
    )

    expect(median).toBeLessThan(100)
  })

  it('中等消息（~2000 字符）渲染时间 < 500ms', () => {
    const content = generateMediumMarkdown()
    const median = measureRenderMedian(content)

    console.warn(
      `[markdown benchmark] 中等消息（${content.length} 字符）中位数渲染耗时: ${median.toFixed(3)}ms`,
    )

    expect(median).toBeLessThan(500)
  })

  it('长消息（~10000 字符）渲染时间 < 2000ms', () => {
    const content = generateLongMarkdown()
    const median = measureRenderMedian(content)

    console.warn(
      `[markdown benchmark] 长消息（${content.length} 字符）中位数渲染耗时: ${median.toFixed(3)}ms`,
    )

    expect(median).toBeLessThan(2000)
  })

  it('渲染结果正确性：标题与列表应出现在 DOM 中', () => {
    const content = generateShortMarkdown()
    const { getByText, getAllByRole, unmount } = render(
      <AssistantMarkdownContent content={content} />,
    )

    // 标题应被渲染为 h2
    expect(getByText('简短回答').tagName).toBe('H2')
    // 列表项应被渲染
    const listItems = getAllByRole('listitem')
    expect(listItems.length).toBeGreaterThanOrEqual(2)

    unmount()
  })

  it('流式模式渲染时间与非流式相近（差异 < 2x）', () => {
    const content = generateMediumMarkdown()
    const nonStreamingMedian = measureRenderMedian(content, 5, false)
    const streamingMedian = measureRenderMedian(content, 5, true)

    console.warn(
      `[markdown benchmark] 流式 vs 非流式: ` +
      `非流式=${nonStreamingMedian.toFixed(3)}ms, 流式=${streamingMedian.toFixed(3)}ms`,
    )

    // 流式模式额外做容错预处理，但不应导致 > 2x 耗时
    const ratio = streamingMedian / nonStreamingMedian
    expect(ratio).toBeLessThan(2)
  })
})
