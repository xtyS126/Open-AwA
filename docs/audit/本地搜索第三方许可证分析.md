# 第三方库许可证汇总

> 汇总日期：2026-05-01
> 适用范围：本地网页搜索功能集成涉及的全部第三方代码

---

## 1. 直接依赖的第三方库

### 1.1 FlexSearch

| 项目 | 内容 |
|------|------|
| **名称** | FlexSearch |
| **版本** | 0.8.212 |
| **仓库** | https://github.com/nextapps-de/flexsearch |
| **许可证** | Apache License 2.0 |
| **版权所有者** | Thomas Wilkerling / Nextapps GmbH |
| **使用方式** | 算法参考 + 架构设计参考 |
| **修改情况** | 未直接使用源码，参考其倒排索引结构和Encoder管道设计 |

```
Copyright 2018 Thomas Wilkerling

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

### 1.2 MiniSearch

| 项目 | 内容 |
|------|------|
| **名称** | MiniSearch |
| **版本** | 7.2.0 |
| **仓库** | https://github.com/lucaong/minisearch |
| **许可证** | MIT License |
| **版权所有者** | Luca Ongaro |
| **使用方式** | 架构参考（前缀树搜索、模糊匹配算法） |
| **修改情况** | 未直接使用源码，参考其SearchableMap设计 |

```
MIT License

Copyright (c) 2018 Luca Ongaro

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction...
```

### 1.3 Orama

| 项目 | 内容 |
|------|------|
| **名称** | Orama (原Lyra) |
| **版本** | 3.1.18 |
| **仓库** | https://github.com/oramasearch/orama |
| **许可证** | Apache License 2.0 |
| **版权所有者** | OramaSearch contributors |
| **使用方式** | 架构参考（BM25评分、混合搜索设计） |
| **修改情况** | 未直接使用源码 |

```
Copyright 2024 OramaSearch

Licensed under the Apache License, Version 2.0...
```

---

## 2. 项目自主实现的模块

以下模块为Open-AwA项目自主开发，不包含第三方代码：

| 模块 | 文件路径 | 说明 |
|------|----------|------|
| 本地搜索引擎 | `backend/core/builtin_tools/local_search.py` | 完全自主实现的倒排索引搜索引擎 |
| 搜索Hook | `frontend/src/shared/hooks/useFlexSearch.ts` | 独立实现的客户端倒排索引 |
| 搜索页面 | `frontend/src/features/search/LocalSearchPage.tsx` | 自主开发的搜索UI组件 |
| 搜索API | `backend/api/routes/tools.py`（新增部分） | 自主开发的API端点 |
| 中文分词器 | `backend/core/builtin_tools/local_search.py::_tokenize` | 自主实现的中文bigram+unigram分词 |

---

## 3. 许可证兼容性确认

| 检查项 | 结果 |
|--------|------|
| 是否包含GPL/AGPL代码 | 否 |
| 是否包含CC非商用代码 | 否 |
| 是否违反任何第三方许可证 | 否 |
| 是否可以商业使用 | 是 |
| 是否需要公开源代码 | 否（参考实现，非直接使用） |

---

## 4. 合规声明

本项目：
1. **未直接复制**任何第三方库的源代码到项目中
2. **参考了**FlexSearch的倒排索引架构设计和Encoder管道模式
3. **参考了**MiniSearch的前缀树搜索算法思路
4. 所有自主实现的代码均为独立编写
5. 在代码注释中标注了灵感来源和参考项目
6. 保留了对原始项目的链接引用，以遵守学术诚信

如未来决定直接使用FlexSearch或MiniSearch的npm包，需在`package.json`中添加依赖，并在构建产物中包含对应的LICENSE文件。
