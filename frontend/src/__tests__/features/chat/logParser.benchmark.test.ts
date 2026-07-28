import { describe, expect, it } from 'vitest'
import { parseSubagentLogs } from '@/features/chat/utils/logParser'

/**
 * logParser 性能基准测试（SubTask 22.4）
 *
 * 测量 parseSubagentLogs 在不同输入规模下的解析时间：
 * - 100 行：典型短日志
 * - 1000 行：中等规模日志
 * - 5000 行：超长日志（压力测试）
 *
 * 阈值设定（基于开发机本地测量基线，留 3x 安全余量避免 flaky）：
 * - 100 行 < 5ms
 * - 1000 行 < 30ms
 * - 5000 行 < 100ms
 *
 * 使用 performance.now() 测量，每个用例重复运行 N 次取中位数以降低噪声。
 */

/** 生成混合类型的合成日志，模拟真实 subagent 输出 */
function generateSyntheticLogs(lineCount: number): string {
  const lines: string[] = []
  // 8 行为一个循环周期，覆盖思考/工具/任务/状态/计划/错误/普通文本/代码块
  const cycle = 8
  for (let i = 0; i < lineCount; i += 1) {
    const phase = i % cycle
    const index = i + 1
    switch (phase) {
      case 0:
        lines.push(`[思考] 第 ${index} 段推理：先观察系统状态再决定下一步动作`)
        break
      case 1:
        lines.push(`[工具] builtin_list_files: running`)
        break
      case 2:
        lines.push(`[工具] builtin_list_files: 调用完成，共返回 12 个文件`)
        break
      case 3:
        lines.push(`[任务] 阶段 ${index} 子任务 (in_progress)`)
        break
      case 4:
        lines.push(`[状态] 当前进度 ${Math.floor((i / lineCount) * 100)}%`)
        break
      case 5:
        lines.push(`[计划] 1. 收集信息 2. 分析数据 3. 输出结论`)
        break
      case 6:
        lines.push(`普通输出行 ${index}：根据工具结果，开始组织最终回答。`)
        break
      case 7:
        lines.push('```python')
        lines.push(`def step_${index}(x):`)
        lines.push(`    return x * 2 + ${index}`)
        lines.push('```')
        break
    }
  }
  return lines.join('\n')
}

/** 重复运行 parseSubagentLogs 多次，返回中位数耗时（ms） */
function measureParseMedian(logs: string, runs: number = 7): number {
  const samples: number[] = []
  // 预热：触发 V8 JIT 优化，避免首次解析的编译开销污染结果
  parseSubagentLogs(logs)

  for (let i = 0; i < runs; i += 1) {
    const start = performance.now()
    parseSubagentLogs(logs)
    const end = performance.now()
    samples.push(end - start)
  }

  samples.sort((a, b) => a - b)
  return samples[Math.floor(samples.length / 2)]
}

describe('logParser 性能基准', () => {
  it('100 行日志解析时间 < 5ms', () => {
    const logs = generateSyntheticLogs(100)
    const median = measureParseMedian(logs)

    // 输出实测数据便于 CI 日志观测
    console.warn(`[logParser benchmark] 100 行中位数解析耗时: ${median.toFixed(3)}ms`)

    expect(median).toBeLessThan(5)
  })

  it('1000 行日志解析时间 < 30ms', () => {
    const logs = generateSyntheticLogs(1000)
    const median = measureParseMedian(logs)

    console.warn(`[logParser benchmark] 1000 行中位数解析耗时: ${median.toFixed(3)}ms`)

    expect(median).toBeLessThan(30)
  })

  it('5000 行日志解析时间 < 100ms', () => {
    const logs = generateSyntheticLogs(5000)
    const median = measureParseMedian(logs)

    console.warn(`[logParser benchmark] 5000 行中位数解析耗时: ${median.toFixed(3)}ms`)

    expect(median).toBeLessThan(100)
  })

  it('解析结果正确性：5000 行日志应产出非空 segments', () => {
    const logs = generateSyntheticLogs(5000)
    const segments = parseSubagentLogs(logs)

    expect(segments.length).toBeGreaterThan(0)
    // 每段必须有 id 和 type
    for (const seg of segments) {
      expect(seg.id).toBeTruthy()
      expect(typeof seg.type).toBe('string')
    }
  })

  it('解析时间与输入规模大致线性相关（5000 行 / 1000 行 比率 < 15）', () => {
    const logs1000 = generateSyntheticLogs(1000)
    const logs5000 = generateSyntheticLogs(5000)
    const median1000 = measureParseMedian(logs1000)
    const median5000 = measureParseMedian(logs5000)

    const ratio = median5000 / median1000
    console.warn(
      `[logParser benchmark] 5000/1000 比率: ${ratio.toFixed(2)} ` +
      `(1000 行=${median1000.toFixed(3)}ms, 5000 行=${median5000.toFixed(3)}ms)`,
    )

    // 5 倍数据量不应导致 > 15 倍耗时
    // 阈值留足测量噪声余量（亚毫秒级测量对 GC/调度抖动敏感）
    expect(ratio).toBeLessThan(15)
  })
})
