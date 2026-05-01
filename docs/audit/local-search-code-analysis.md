# 本地搜索引擎深度代码分析报告

> 分析日期：2026-05-01
> 分析项目：FlexSearch v0.8.212, MiniSearch v7.2.0, Orama v3.1.18
> 存放位置：references/other-projects/

---

## 1. FlexSearch 核心架构分析

### 1.1 核心模块调用关系

```
Index (index.js)
├── Encoder (encoder.js)          ← 文本编码/分词流水线
│   ├── normalize()               ← Unicode规范化 + 小写化
│   ├── prepare()                 ← 自定义预处理器
│   ├── numeric_split             ← 数字三元组分割
│   ├── split (RegExp/string)     ← 词条分割
│   ├── filter (Set/Function)     ← 停用词过滤
│   ├── stemmer (Map)             ← 词干提取
│   ├── mapper (Map)              ← 字符替换
│   ├── dedupe                    ← 字母去重（hello → helo）
│   ├── matcher (Map)             ← 词条替换
│   ├── replacer (Array<RegExp>)  ← 正则替换
│   └── finalize()                ← 自定义后处理器
├── index/add.js                  ← 文档添加 + 多种分词策略
│   ├── _push_index()             ← 写入倒排索引
│   └── get_score()               ← 评分计算
├── index/search.js               ← 搜索查询
│   ├── single_term_query()       ← 单词语快速路径
│   ├── _get_array()              ← 获取posting list
│   └── return_result()           ← 结果聚合与排序
├── index/remove.js               ← 文档删除
├── intersect.js                  ← 多词结果交集
├── cache.js                      ← LRU缓存
├── charset/                      ← 语言字符集配置
│   ├── cjk.js                    ← CJK配置 (split: "")
│   ├── latin/balance.js          ← 拉丁语系配置
│   └── ...
├── keystore.js                   ← 高效键值存储（TypedArray）
├── serialize.js                  ← 索引导入/导出
├── compress.js                   ← 词条压缩
├── resolver.js                   ← 延迟结果解析
└── worker/                       ← Web Worker支持
    ├── handler.js
    └── worker.js
```

### 1.2 倒排索引数据结构

```javascript
// 核心数据结构（简化版）
{
  // 主索引: term → score → [id1, id2, ...]
  map: Map<string, Array<string[]>>,

  // 上下文索引: ctxTerm → term → score → [ids]
  ctx: Map<string, Map<string, Array<string[]>>>,

  // 文档注册表: id → Set/Map
  reg: Set<string> | Map<string, Array[]>
}
```

**关键设计决策：**
- 使用`Map`而非普通对象：更好的性能和键类型支持
- 评分槽位数组：`arr[score] = [id1, id2, ...]` 实现O(1)的评分分组
- `KeystoreMap`/`KeystoreSet`：使用TypedArray减少内存占用
- Compile-time flags：`SUPPORT_*` 常量在构建时通过Babel条件编译

### 1.3 可复用核心算法

#### 评分算法 (index/add.js:301-330)
```
get_score(resolution, length, i, term_length, x)
  位置加权评分：
  - 文档开头匹配得分最高
  - 分辨率槽位拉伸：将评分映射到[0, resolution)范围
  - 短文档权重补偿
```

#### 交集算法 (intersect.js)
```
多词搜索结果交集：
1. 按posting list长度升序排列
2. 使用双指针/Set交集
3. 保留评分信息用于最终排序
4. 支持AND/OR/NOT逻辑组合
```

#### 上下文搜索 (index/add.js:147-180)
```
基于词邻近度的上下文索引：
- 仅"strict"分词模式支持
- 索引相邻词对(term, nextTerm)
- 搜索时匹配词对并加权
- bidirectional参数控制方向敏感性
```

### 1.4 关键配置项

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `encode` | `"balance"` | 编码器预设或自定义Encoder |
| `tokenize` | `"strict"` | 分词策略: strict/forward/reverse/full |
| `resolution` | `9` | 评分分辨率（槽位数） |
| `depth` | `0` | 上下文搜索深度 |
| `cache` | `null` | LRU缓存大小 |
| `fastupdate` | `false` | 快速更新模式（额外内存开销） |
| `compress` | `false` | 词条压缩存储 |

### 1.5 需要适配的依赖项

- **charset/polyfill.js**: IE11兼容层，现代项目可移除
- **lang/**: 英语/德语/法语语言包，需要添加中文语言包
- **worker/**: Web Worker支持，Node.js后端可忽略
- **compress.js**: 词条压缩算法（hash函数），可替换为更高效的实现

---

## 2. MiniSearch 核心架构分析

### 2.1 核心模块调用关系

```
MiniSearch (MiniSearch.ts)
├── SearchableMap (SearchableMap.ts)
│   ├── RadixTree实现
│   ├── fuzzySearch()           ← 模糊搜索（Levenshtein编辑距离）
│   └── TreeIterator            ← 前缀树遍历
├── QueryParser (内部)
│   ├── AND/OR/NOT 组合
│   └── 字段过滤
└── Scoring
    ├── TF-IDF 计算
    ├── 字段权重 (boost)
    └── 模糊/前缀权重
```

### 2.2 关键差异与FlexSearch对比

| 特性 | FlexSearch | MiniSearch |
|------|-----------|------------|
| 核心数据结构 | Map + 多层评分数组 | SearchableMap (RadixTree) |
| 分词 | Encoder流水线 | 简单的tokenize函数 |
| 模糊搜索 | 通过"tolerant"分词实现 | Levenshtein编辑距离 |
| 排序 | 位置加权评分 | TF-IDF + 字段权重 |
| 索引持久化 | serialize/deserialize | JSON序列化 |
| 体积 | ~15KB gzip | ~10KB gzip |
| Web Worker | 原生支持 | 需自行实现 |
| 上下文搜索 | 内置支持 | 不支持 |

### 2.3 MiniSearch可复用组件

1. **SearchableMap**: 基于前缀树的Map实现，支持高效前缀搜索和模糊搜索
2. **fuzzySearch算法**: 基于编辑距离的模糊匹配，可独立使用
3. **Query组合器**: AND/OR/AND_NOT逻辑的优雅实现

---

## 3. Orama 核心架构分析

### 3.1 核心模块

```
Orama
├── create()                    ← 创建索引实例
├── insert() / insertMultiple() ← 插入文档
├── search()                    ← 搜索
├── remove() / update()         ← 文档管理
└── save() / load()             ← 持久化
    ├── 前缀树 (Trie)
    ├── 倒排索引
    ├── BM25评分
    └── Facet过滤
```

### 3.2 Orama特色功能

- **混合搜索**: 全文 + 向量搜索（与Open-AwA的ChromaDB互补）
- **零依赖**: 纯TypeScript，无外部npm依赖
- **类型安全**: 完整的TypeScript泛型支持
- **插件系统**: 可扩展的tokenizer、stemmer等

---

## 4. 集成建议总结

### 推荐方案：FlexSearch为核心 + 自定义中文分词

**优势：**
- 性能最优（纯JS中最快的全文搜索）
- 体积最小（gzip后约15KB）
- Encoder流水线可灵活适配中文分词
- 支持Web Worker（不阻塞UI）
- MIT许可证

**适配清单：**
1. ✅ 创建中文Encoder（基于jieba或bigram）
2. ✅ 移除不需要的language pack和polyfill
3. ✅ 与现有ChromaDB向量搜索形成互补
4. ✅ 前端：React Hook封装 (`useFlexSearch`)
5. ✅ 后端：Node.js worker运行FlexSearch，或使用Python实现相同算法
