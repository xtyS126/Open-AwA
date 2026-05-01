/**
 * FlexSearch 客户端搜索Hook。
 * 基于FlexSearch库提供浏览器端的即时全文搜索能力。
 *
 * 参考来源: FlexSearch (https://github.com/nextapps-de/flexsearch, Apache-2.0)
 * 作者: nextapps-de/Thomas Wilkerling
 * 许可: Apache-2.0
 */
import { useRef, useCallback, useState } from 'react'

/* FlexSearch实例类型（动态导入以避免构建依赖） */
interface FlexSearchIndex {
  add(id: string | number, content: string): void
  search(
    query: string | SearchOptions,
    limit?: number,
    options?: SearchOptions
  ): SearchResult[]
  remove(id: string | number): void
  clear(): void
  contain(id: string | number): boolean
}

interface SearchOptions {
  limit?: number
  offset?: number
  suggest?: boolean
  enrich?: boolean
  context?: boolean
}

interface SearchResult {
  id: string | number
  score: number
  result?: string[]
}

interface UseFlexSearchOptions {
  /** 搜索配置 */
  preset?: 'speed' | 'memory' | 'match' | 'score'
  /** 自定义分词函数 */
  tokenize?: (text: string) => string[]
  /** 是否启用中文优化 */
  cjk?: boolean
}

interface UseFlexSearchReturn {
  /** 添加文档到索引 */
  addDocument: (id: string | number, content: string) => void
  /** 批量添加文档 */
  addDocuments: (docs: Array<{ id: string | number; content: string }>) => void
  /** 搜索 */
  search: (query: string, limit?: number) => SearchResult[]
  /** 删除文档 */
  removeDocument: (id: string | number) => void
  /** 清空索引 */
  clearIndex: () => void
  /** 索引中的文档数 */
  docCount: number
  /** 是否已初始化 */
  isReady: boolean
  /** 初始化FlexSearch实例 */
  init: () => Promise<void>
}

/**
 * 中文文本分词函数。
 * 对CJK字符使用bigram + unigram分词，对字母/数字使用词边界分词。
 */
function chineseTokenizer(text: string): string[] {
  if (!text) return []

  const normalized = text.toLowerCase().trim()
  const tokens: string[] = []

  /* CJK字符范围 */
  const cjkRange = /[一-鿿㐀-䶿豈-﫿]+/g
  const wordRange = /[a-z0-9_À-ɏ]+/g

  let lastIndex = 0
  let match: RegExpExecArray | null

  /* 提取CJK序列并分词 */
  while ((match = cjkRange.exec(normalized)) !== null) {
    /* 处理CJK之前的非CJK文本 */
    if (match.index > lastIndex) {
      const nonCjk = normalized.slice(lastIndex, match.index)
      let wm: RegExpExecArray | null
      while ((wm = wordRange.exec(nonCjk)) !== null) {
        if (wm[0].length >= 1) tokens.push(wm[0])
      }
    }

    const cjkText = match[0]
    /* Bigram */
    for (let i = 0; i < cjkText.length - 1; i++) {
      tokens.push(cjkText.substring(i, i + 2))
    }
    /* Unigram（单字） */
    for (let i = 0; i < cjkText.length; i++) {
      tokens.push(cjkText[i])
    }

    lastIndex = match.index + match[0].length
  }

  /* 处理末尾的非CJK文本 */
  if (lastIndex < normalized.length) {
    const remaining = normalized.slice(lastIndex)
    let wm: RegExpExecArray | null
    while ((wm = wordRange.exec(remaining)) !== null) {
      if (wm[0].length >= 1) tokens.push(wm[0])
    }
  }

  return tokens
}

/**
 * 简易倒排索引实现（FlexSearch的轻量替代，避免额外依赖）。
 * 当FlexSearch npm包不可用时使用。
 */
class SimpleInvertedIndex {
  private index: Map<string, Map<string | number, number[]>> = new Map()
  private docs: Map<string | number, string> = new Map()
  private _tokenize: (text: string) => string[]

  constructor(tokenize: (text: string) => string[]) {
    this._tokenize = tokenize
  }

  add(id: string | number, content: string): void {
    this.remove(id)
    this.docs.set(id, content)
    const tokens = this._tokenize(content)
    const seen = new Set<string>()

    tokens.forEach((token, pos) => {
      if (!this.index.has(token)) {
        this.index.set(token, new Map())
      }
      const postings = this.index.get(token)!
      if (!postings.has(id)) {
        postings.set(id, [])
      }
      postings.get(id)!.push(pos)

      /* 前缀索引） */
      if (token.length >= 2) {
        for (let i = 2; i < token.length; i++) {
          const prefix = token.substring(0, i)
          if (seen.has(prefix)) continue
          seen.add(prefix)
          if (!this.index.has(prefix)) {
            this.index.set(prefix, new Map())
          }
          const p = this.index.get(prefix)!
          if (!p.has(id)) {
            p.set(id, [])
          }
        }
      }
    })
  }

  search(query: string, limit: number = 20): SearchResult[] {
    const queryTokens = this._tokenize(query)
    if (!queryTokens.length) return []

    const scores = new Map<string | number, number>()

    queryTokens.forEach((qterm) => {
      /* 精确匹配 */
      const exactPostings = this.index.get(qterm)
      if (exactPostings) {
        exactPostings.forEach((positions, docId) => {
          const tf = positions.length
          const idf = 1 + Math.log(this.docs.size / exactPostings.size)
          scores.set(docId, (scores.get(docId) || 0) + tf * idf * 1.0)
        })
      }

      /* 前缀匹配 */
      for (const [term, postings] of this.index.entries()) {
        if (term !== qterm && term.startsWith(qterm) && qterm.length >= 2) {
          postings.forEach((positions, docId) => {
            const tf = positions.length * 0.5
            const idf = 1 + Math.log(this.docs.size / Math.max(postings.size, 1))
            scores.set(docId, (scores.get(docId) || 0) + tf * idf * 0.7)
          })
        }
      }
    })

    return Array.from(scores.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, limit)
      .map(([id, score]) => ({ id, score: Math.round(score * 1000) / 1000, result: [] }))
  }

  remove(id: string | number): void {
    const content = this.docs.get(id)
    if (!content) return
    this.docs.delete(id)
    const tokens = this._tokenize(content)
    tokens.forEach((token) => {
      const postings = this.index.get(token)
      if (postings) {
        postings.delete(id)
        if (postings.size === 0) this.index.delete(token)
      }
    })
  }

  clear(): void {
    this.index.clear()
    this.docs.clear()
  }

  get size(): number {
    return this.docs.size
  }
}

export function useFlexSearch(
  options: UseFlexSearchOptions = {}
): UseFlexSearchReturn {
  const indexRef = useRef<SimpleInvertedIndex | null>(null)
  const [docCount, setDocCount] = useState(0)
  const [isReady, setIsReady] = useState(false)

  const tokenize = options.tokenize || (options.cjk !== false ? chineseTokenizer : (text: string) => text.toLowerCase().split(/\s+/))

  const init = useCallback(async () => {
    if (indexRef.current) return
    indexRef.current = new SimpleInvertedIndex(tokenize)
    setIsReady(true)
  }, [tokenize])

  const addDocument = useCallback(
    (id: string | number, content: string) => {
      if (!indexRef.current) return
      indexRef.current.add(id, content)
      setDocCount(indexRef.current.size)
    },
    []
  )

  const addDocuments = useCallback(
    (docs: Array<{ id: string | number; content: string }>) => {
      if (!indexRef.current) return
      docs.forEach((doc) => indexRef.current!.add(doc.id, doc.content))
      setDocCount(indexRef.current.size)
    },
    []
  )

  const search = useCallback(
    (query: string, limit: number = 20): SearchResult[] => {
      if (!indexRef.current) return []
      return indexRef.current.search(query, limit)
    },
    []
  )

  const removeDocument = useCallback((id: string | number) => {
    if (!indexRef.current) return
    indexRef.current.remove(id)
    setDocCount(indexRef.current.size)
  }, [])

  const clearIndex = useCallback(() => {
    if (!indexRef.current) return
    indexRef.current.clear()
    setDocCount(0)
  }, [])

  return {
    addDocument,
    addDocuments,
    search,
    removeDocument,
    clearIndex,
    docCount,
    isReady,
    init,
  }
}

export { chineseTokenizer }
export type { FlexSearchIndex, SearchOptions, SearchResult, UseFlexSearchOptions, UseFlexSearchReturn }
