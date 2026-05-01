# 本地搜索功能回滚方案

> 创建日期：2026-05-01
> 适用范围：本地搜索集成的紧急回滚操作

---

## 1. 回滚触发条件

出现以下任一情况时，执行回滚：
- 本地搜索功能导致CPU/内存异常飙升（>30%增长）
- 索引构建导致的磁盘I/O影响系统正常响应
- 搜索API响应时间超过500ms（原DuckDuckGo搜索<200ms）
- 前端加载时间因搜索模块增加超过500ms
- 出现数据损坏或搜索结果异常

---

## 2. 快速回滚（特性开关）

### 方式A：环境变量（推荐，无需重启）

```bash
# 设置环境变量禁用本地搜索，回退到DuckDuckGo
export LOCAL_SEARCH_ENABLED=false
```

### 方式B：修改配置文件

```bash
# 编辑 backend/.env.local
LOCAL_SEARCH_ENABLED=False
```

重启服务后生效。

---

## 3. Git回滚（完全移除代码）

### 3.1 回滚最近一次本地搜索相关提交

```bash
# 查看涉及本地搜索的提交
git log --oneline --all -- backend/core/builtin_tools/local_search.py

# 回滚特定提交（不影响其他代码）
git revert <commit-hash> --no-commit

# 手动验证后提交
git commit -m "[Revert] 回滚本地搜索功能集成"
```

### 3.2 回滚到集成前的状态

```bash
# 假设集成前最后的安全提交是 abc1234
git checkout abc1234 -- backend/core/builtin_tools/local_search.py
git checkout abc1234 -- backend/core/builtin_tools/manager.py
git checkout abc1234 -- backend/core/builtin_tools/__init__.py
git checkout abc1234 -- backend/api/routes/tools.py
git checkout abc1234 -- frontend/src/shared/hooks/useFlexSearch.ts
git checkout abc1234 -- frontend/src/features/search/
git checkout abc1234 -- backend/tests/test_local_search.py

# 删除新增的目录
rm -rf frontend/src/features/search/
rm -rf data/local_search_index/

git commit -m "[Revert] 完全回滚本地搜索功能到集成前状态"
```

### 3.3 使用git revert批量回滚

```bash
# 列出所有本地搜索相关的提交
git log --oneline --grep="local.search\|本地搜索\|LocalSearch" --reverse

# 从最新到最旧逐个回滚
git revert <newest-commit>
git revert <next-commit>
# ... 继续直到回滚所有相关提交
```

---

## 4. 部分回滚（保留有益部分）

### 4.1 仅回滚后端，保留前端

```bash
# 回滚后端搜索引擎
git revert <backend-search-commit> -- backend/

# 回滚后端API路由
git checkout main -- backend/api/routes/tools.py

# 清理后端索引数据
rm -rf data/local_search_index/
```

### 4.2 仅回滚前端，保留后端

```bash
# 回滚前端搜索组件
git checkout main -- frontend/src/features/search/
git checkout main -- frontend/src/shared/hooks/useFlexSearch.ts
git checkout main -- frontend/src/shared/api/toolsApi.ts

# 删除搜索组件目录
rm -rf frontend/src/features/search/
```

---

## 5. 数据清理

### 5.1 清理索引数据

```bash
# 删除本地索引目录
rm -rf backend/data/local_search_index/

# 如果使用了自定义目录
rm -rf <LOCAL_SEARCH_INDEX_DIR>
```

### 5.2 清理npm依赖（如果安装了FlexSearch包）

```bash
cd frontend
npm uninstall flexsearch   # 如果安装了
```

---

## 6. 验证回滚成功

回滚后执行以下验证：

```bash
# 1. 后端搜索API回退到DuckDuckGo
curl -X POST http://localhost:8000/api/tools/search/web \
  -H "Content-Type: application/json" \
  -H "Cookie: ..." \
  -d '{"query": "test"}'
# 期望：返回DuckDuckGo搜索结果

# 2. 本地搜索API应返回错误或不可用
curl -X POST http://localhost:8000/api/tools/search/local \
  -H "Content-Type: application/json" \
  -H "Cookie: ..." \
  -d '{"query": "test"}'
# 期望：返回错误

# 3. 前端构建正常
cd frontend && npm run build
# 期望：构建成功，无local_search相关错误

# 4. 单元测试全部通过
cd backend && pytest -v
# 期望：无local_search相关测试失败
```

---

## 7. 应急联系人

| 角色 | 负责模块 |
|------|----------|
| 后端开发 | `backend/core/builtin_tools/local_search.py` |
| 前端开发 | `frontend/src/features/search/` |
| DevOps | 特性开关 `LOCAL_SEARCH_ENABLED` |

---

## 8. 回滚时间预估

| 回滚方式 | 预计时间 | 服务中断 |
|----------|----------|----------|
| 特性开关 | <1分钟 | 无 |
| 部分回滚（git） | 5-10分钟 | <1分钟（重启） |
| 完全回滚（git） | 10-15分钟 | <2分钟（重启+构建） |
